"""The nemlig.com client."""

from __future__ import annotations

import os
import re
import time
import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from . import auth
from ._env import get_setting
from ._http import GW, WWW, Http
from .auth import Token, TokenManager
from .errors import ApiError, NotLoggedInError
from .models import (
    Account,
    Basket,
    DeliveryContext,
    DeliveryDay,
    Order,
    OrderSummary,
    Product,
    ProductDetails,
    SearchResult,
    ShoppingList,
    ShoppingListSummary,
    SlotReservation,
    Suggestions,
)
from .models.basket import validation_failures
from .session import SessionStore, user_key

ProductId = str | int

# Concurrent requests for search_many(); enough for a shopping list, gentle on the site.
MAX_PARALLEL_SEARCHES = 8

# The anonymous delivery context depends on the time of day, so refetch it now and then.
CONTEXT_TTL = 600
# How far ahead get_slot_context looks for a slot id.
SLOT_LOOKUP_DAYS = 30
# GetShoppingLists page size.
LISTS_PAGE = 50

# A product page path: letters, digits and dashes, so a slug can never reach another www path.
_SLUG = re.compile(r"[\w-]+")


class NemligClient:
    """Synchronous client for nemlig.com's website API.

    Searching, product pages, delivery days and offers work anonymously. The basket, orders,
    favourites and shopping lists need an account: give credentials, or reuse a saved session.
    With credentials the client logs in lazily and logs in again when the session has expired,
    because an expired session does not fail; it silently turns into an empty anonymous basket.

    The cookie jar is saved to ``session_file`` (``~/.config/nemlig/session.json`` by default), so
    later runs do not have to log in. The password is never written to disk.

    Checkout and payment are deliberately not supported. A client is not thread-safe; use one
    per thread.
    """

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        *,
        session_file: str | os.PathLike[str] | None = None,
        persist: bool = True,
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._username = username
        self._password = password
        self._user = user_key(username) if username and password else None
        self._http = Http(timeout=timeout, transport=transport, sleep=sleep)
        self._tokens = TokenManager(self._http, clock=clock)
        self._clock = clock
        self._store = SessionStore(session_file) if persist else None
        if self._store:
            # With credentials, only this user's saved session is used.
            self._store.load(self._http.cookies.jar, self._user)
        self._context: DeliveryContext | None = None
        self._context_at = 0.0

    @classmethod
    def from_env(cls, env_file: str | os.PathLike[str] | None = ".env", **kwargs: Any) -> NemligClient:
        """Credentials from ``NEMLIG_USER`` / ``NEMLIG_PASS``, in the environment or ``env_file``."""
        path = Path(env_file) if env_file is not None else None
        return cls(get_setting("NEMLIG_USER", path), get_setting("NEMLIG_PASS", path), **kwargs)

    # -- lifecycle ----------------------------------------------------------------------------

    def __enter__(self) -> NemligClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._save_session()
        finally:
            self._http.close()

    # -- session ------------------------------------------------------------------------------

    @property
    def has_credentials(self) -> bool:
        return bool(self._username and self._password)

    def login(self) -> None:
        """Log in with the configured credentials. Raises `AuthError` if they are rejected."""
        if not self.has_credentials:
            raise NotLoggedInError("no username and password configured")
        assert self._username and self._password
        auth.login(self._http, self._username, self._password)
        self._tokens.invalidate()
        self._context = None
        if not self._tokens.get().is_customer:
            raise NotLoggedInError("login succeeded but the session is not a customer session")
        self._save_session()

    def logout(self) -> None:
        """Forget the session locally: clear cookies and delete the session file."""
        self._http.cookies.clear()
        self._tokens.invalidate()
        self._context = None
        if self._store:
            self._store.delete()

    def is_logged_in(self) -> bool:
        """True when the current cookies belong to an account. Does not log in."""
        return self._tokens.get().is_customer

    def _token(self, *, require_login: bool) -> Token:
        """A valid bearer token, logging in if we have credentials and the session is anonymous."""
        token = self._tokens.get()
        if token.is_customer:
            return token
        if self.has_credentials:
            self.login()
            return self._tokens.get()
        if require_login:
            raise NotLoggedInError(
                "this needs a logged-in nemlig.com account; pass username and password, or call login() first"
            )
        return token

    def _require_login(self) -> None:
        self._token(require_login=True)

    def _bearer(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token(require_login=False).value}"}

    def _save_session(self) -> None:
        if self._store and any(c.name == ".ASPXAUTH" for c in self._http.cookies.jar):
            self._store.save(self._http.cookies.jar, self._user or self._store.user)

    # -- delivery context ---------------------------------------------------------------------

    def get_delivery_context(self) -> DeliveryContext:
        """The delivery zone and slot used to price search results.

        Logged in, it is the basket's (the account's real zone and reserved slot). Anonymous, it is
        the site's default zone.
        """
        fresh = self._clock() - self._context_at < CONTEXT_TTL
        if self._context is not None and fresh:
            return self._context
        if self._token(require_login=False).is_customer:
            self.get_basket()  # sets self._context
        if self._context is None or self._clock() - self._context_at >= CONTEXT_TTL:
            settings = self._http.get(f"{WWW}/", params={"GetAsJson": 1})["Settings"]
            self._set_context(
                DeliveryContext(timeslot_utc=settings["TimeslotUtc"], zone_id=int(settings["DeliveryZoneId"]))
            )
        assert self._context is not None
        return self._context

    def get_slot_context(self, slot_id: int) -> DeliveryContext:
        """The delivery context of any slot in the next month (``DeliverySlot.id``).

        Search and offers priced with it show that slot's prices and offers, without reserving it.
        Raises ``ValueError`` when the slot is not in the delivery days.
        """
        zone_id = self.get_delivery_context().zone_id
        for day in self.get_delivery_days(days=SLOT_LOOKUP_DAYS):
            for slot in day.slots:
                if slot.id == int(slot_id) and slot.timeslot_utc:
                    return DeliveryContext(timeslot_utc=slot.timeslot_utc, zone_id=zone_id, slot_id=slot.id)
        raise ValueError(f"no delivery slot {slot_id} in the next {SLOT_LOOKUP_DAYS} days")

    def _context_for(self, slot_id: int | None) -> DeliveryContext:
        return self.get_delivery_context() if slot_id is None else self.get_slot_context(slot_id)

    def _set_context(self, context: DeliveryContext | None) -> None:
        if context is not None:
            self._context = context
            self._context_at = self._clock()

    def _basket(self, data: Any) -> Basket:
        basket = Basket.from_api(_object(data, "basket"))
        self._set_context(basket.delivery_context)
        return basket

    # -- search and products ------------------------------------------------------------------

    def search(
        self, query: str, limit: int = 20, offset: int = 0, slot_id: int | None = None
    ) -> SearchResult:
        """Search products. Prices and stock are for the current delivery zone and slot, or for
        ``slot_id`` (see `get_slot_context`)."""
        return self.search_many([query], limit=limit, offset=offset, slot_id=slot_id)[0]

    def search_many(
        self, queries: Sequence[str], limit: int = 20, offset: int = 0, slot_id: int | None = None
    ) -> list[SearchResult]:
        """Run several searches at once and return the results in the order of ``queries``.

        The session and delivery context are resolved once, up front. The searches then run in
        parallel threads that only send GETs over the shared connection pool and touch no client
        state. If any search fails, the error is raised.
        """
        ctx = self._context_for(slot_id)
        headers = self._bearer()

        def one(query: str) -> SearchResult:
            data = self._http.get(
                f"{GW}/searchgateway/api/search",
                headers=headers,
                params={
                    "query": query,
                    "take": limit,
                    "skip": offset,
                    "timeslotUtc": ctx.timeslot_utc,
                    "deliveryZoneId": ctx.zone_id,
                    "TimeSlotId": ctx.slot_id,
                },
            )
            return SearchResult.from_api(data or {}, query)

        if len(queries) <= 1:
            return [one(q) for q in queries]
        with ThreadPoolExecutor(max_workers=min(len(queries), MAX_PARALLEL_SEARCHES)) as pool:
            return list(pool.map(one, queries))

    def suggest(self, query: str) -> Suggestions:
        """Autocomplete: search-term suggestions and matching categories."""
        data = self._http.get(
            f"{GW}/searchgateway/api/quick",
            headers=self._bearer(),
            params={"query": query, "correlationId": str(uuid.uuid4())},
        )
        return Suggestions.from_api(data or {}, query)

    def get_product(self, product: ProductId | Product) -> ProductDetails:
        """Full product page: description, ingredients, nutrition, allergens.

        Takes a product id, a slug (``Product.slug``) or a `Product`.
        """
        if isinstance(product, Product):
            path = product.slug or product.id
        else:
            path = str(product).strip().removeprefix(WWW).strip("/")
        if not _SLUG.fullmatch(path):
            raise ValueError(f"not a product id or slug: {product!r}")
        if path.isdigit():
            # Any "<text>-<id>" path redirects to the product's canonical slug.
            path = f"p-{path}"
        page = self._http.get(f"{WWW}/{path}", params={"GetAsJson": 1}, follow_redirects=True) or {}
        for block in page.get("content") or []:
            if isinstance(block, dict) and block.get("TemplateName") == "productdetailspot":
                return ProductDetails.from_api(block)
        raise ApiError(404, f"product not found: {product}")

    # -- basket -------------------------------------------------------------------------------

    def get_basket(self) -> Basket:
        self._require_login()
        return self._basket(self._http.get(f"{WWW}/webapi/basket/GetBasket"))

    def set_quantity(self, product_id: ProductId, quantity: int) -> Basket:
        """Set a product's quantity in the basket. The quantity is absolute; 0 removes the line."""
        _check_int(quantity, "quantity")
        if quantity < 0:
            raise ValueError("quantity must be 0 or more")
        self._require_login()
        data = self._http.post(
            f"{WWW}/webapi/basket/AddToBasket",
            json={
                "ProductId": _pid(product_id),
                "quantity": quantity,
                # Needed to remove sold-out lines that sit at quantity 0.
                "AffectPartialQuantity": quantity == 0,
                "disableQuantityValidation": False,
            },
        )
        return self._basket(data)

    def add_to_basket(self, product_id: ProductId, quantity: int = 1) -> Basket:
        """Add ``quantity`` on top of what is already in the basket. Negative subtracts.

        Not idempotent: calling it twice adds twice. Use `set_quantity` when retrying.
        """
        _check_int(quantity, "quantity")
        if quantity == 0:
            return self.get_basket()
        self._require_login()
        data = self._http.post(
            f"{WWW}/webapi/basket/AddToBasket",
            json={"productId": _pid(product_id), "quantity": quantity, "addToExisting": True},
        )
        return self._basket(data)

    def remove_from_basket(self, product_id: ProductId) -> Basket:
        return self.set_quantity(product_id, 0)

    def remove_sold_out(self) -> Basket:
        """Remove lines left at quantity 0, e.g. sold-out products after a reorder."""
        basket = self.get_basket()
        for line in basket.lines:
            if line.quantity == 0:
                basket = self.set_quantity(line.product_id, 0)
        return basket

    def clear_basket(self) -> Basket:
        """Empty the basket. The reserved delivery slot stays reserved."""
        self._require_login()
        self._http.post(f"{WWW}/webapi/basket/ClearBasket")
        return self.get_basket()

    # -- delivery -----------------------------------------------------------------------------

    def get_delivery_days(self, days: int = 7, start: date | None = None) -> list[DeliveryDay]:
        """Delivery days and their slots, from ``start`` (default today)."""
        self._token(require_login=False)  # log in first if we can, so the account's zone is used
        data = self._http.get(
            f"{WWW}/webapi/v2/Delivery/GetDeliveryDays",
            params={
                "startDate": start.isoformat() if start else "undefined",
                "days": days,
                "showForSubscriptions": False,
            },
        )
        return [DeliveryDay.from_api(d) for d in (data or {}).get("DayRangeHours") or []]

    def reserve_slot(self, slot_id: int) -> SlotReservation:
        """Reserve a delivery slot for the basket (``DeliverySlot.id``)."""
        self._require_login()
        data = self._http.post(
            f"{WWW}/webapi/Delivery/TryUpdateDeliveryTime", params={"timeslotId": int(slot_id)}
        )
        if not isinstance(data, dict):
            data = {}  # the response is undocumented; the basket read below decides
        basket = self.get_basket()
        slot = basket.delivery_slot
        reserved = (
            bool(data.get("IsReserved"))
            if "IsReserved" in data
            else bool(slot and slot.id == int(slot_id) and slot.reserved)
        )
        message = data.get("Message") or data.get("ErrorMessage") or None
        return SlotReservation(reserved=reserved, slot=slot, message=message)

    # -- orders -------------------------------------------------------------------------------

    def get_orders(self, limit: int = 10, page: int = 1) -> list[OrderSummary]:
        """Past orders, newest first. ``page`` is 1-based, with ``limit`` orders per page."""
        self._require_login()
        data = self._http.get(
            f"{WWW}/webapi/order/GetBasicOrderHistory", params={"skip": max(page, 1), "take": limit}
        )
        return [OrderSummary.from_api(o) for o in (data or {}).get("Orders") or []]

    def get_order(self, order_id: int) -> Order:
        """One past order with its product lines. ``order_id`` is `OrderSummary.id`."""
        self._require_login()
        data = self._http.get(f"{WWW}/webapi/v2/order/GetOrderHistory/{int(order_id)}")
        return Order.from_api(_object(data, "order"))

    def reorder(self, order_id: int) -> Basket:
        """Add every product of a past order to the basket, on top of what is there.

        Sold-out products stay as quantity-0 lines (see `remove_sold_out`); warnings are in
        ``Basket.validation_failures``.
        """
        self._require_login()
        # The field is called OrderNumber, but it takes the numeric order id.
        data = self._http.post(f"{WWW}/webapi/order/CopyOrder", json={"OrderNumber": str(int(order_id))})
        if isinstance(data, dict) and "Lines" in data:
            return self._basket(data)
        basket = self.get_basket()
        failures = validation_failures(data.get("ValidationFailures") if isinstance(data, dict) else None)
        if failures:
            basket = basket.model_copy(update={"validation_failures": basket.validation_failures + failures})
        return basket

    # -- favourites and offers ----------------------------------------------------------------

    def get_favourites(self) -> list[Product]:
        """The account's favourite products."""
        self._require_login()
        return self._productbff_page("/favoritter", self.get_delivery_context())

    def get_offers(self, limit: int | None = None, slot_id: int | None = None) -> list[Product]:
        """Offers for the current delivery slot, or for ``slot_id`` (see `get_slot_context`).

        Offers change from slot to slot. The full list is over a thousand products; ``limit`` trims it.
        """
        products = self._productbff_page("/tilbud", self._context_for(slot_id))
        return products[:limit] if limit is not None else products

    def _productbff_page(self, path: str, ctx: DeliveryContext) -> list[Product]:
        data = self._http.get(
            f"{GW}/productbff/api/web/page",
            headers=self._bearer(),
            params={"path": path, "timeslotId": ctx.slot_id},
        )
        seen: set[str] = set()
        products: list[Product] = []
        for section in (data or {}).get("pageContent") or []:
            for item in section.get("products") or []:
                product = Product.from_productbff(item)
                if product.id not in seen:
                    seen.add(product.id)
                    products.append(product)
        return products

    # -- shopping lists -----------------------------------------------------------------------

    def get_shopping_lists(self) -> list[ShoppingListSummary]:
        self._require_login()
        lists: list[ShoppingListSummary] = []
        seen: set[int] = set()
        # Unlike order history, ``skip`` counts lists, not pages: the first page is skip=0.
        skip = 0
        while True:
            data = self._http.get(
                f"{WWW}/webapi/ShoppingList/GetShoppingLists", params={"skip": skip, "take": LISTS_PAGE}
            )
            items = [
                ShoppingListSummary.from_api(x)
                for x in (data or {}).get("ShoppingListOverViewViewModels") or []
            ]
            new = [x for x in items if x.id not in seen]
            lists += new
            seen.update(x.id for x in new)
            if len(items) < LISTS_PAGE or not new:
                return lists
            skip += LISTS_PAGE

    def get_shopping_list(self, list_id: int) -> ShoppingList:
        self._require_login()
        data = self._http.get(f"{WWW}/webapi/ShoppingList/getShoppingList", params={"listId": int(list_id)})
        return ShoppingList.from_api(_object(data, "shopping list"))

    def create_shopping_list(self, name: str) -> ShoppingList:
        self._require_login()
        data = self._http.post(f"{WWW}/webapi/ShoppingList/CreateShoppingList", params={"name": name})
        return ShoppingList.from_api(_object(data, "shopping list"))

    def set_shopping_list_item(self, list_id: int, product_id: ProductId, quantity: int) -> ShoppingList:
        """Set a product's quantity in a shopping list. Absolute; 0 removes it."""
        _check_int(quantity, "quantity")
        if quantity < 0:
            raise ValueError("quantity must be 0 or more")
        self._require_login()
        data = self._http.post(
            f"{WWW}/webapi/ShoppingList/UpdateProductInShoppingList",
            params={"listId": int(list_id), "productId": _pid(product_id), "amount": quantity},
        )
        data = _object(data, "shopping list")
        return ShoppingList.from_api(data.get("List") or data)

    def delete_shopping_list(self, list_id: int) -> None:
        self._require_login()
        self._http.post(f"{WWW}/webapi/ShoppingList/RemoveShoppingList", params={"listId": int(list_id)})

    def add_shopping_list_to_basket(self, list_id: int) -> Basket:
        """Add a shopping list's products to the basket, on top of what is there."""
        self._require_login()
        data = self._http.post(
            f"{WWW}/webapi/basket/addShoppingListToBasket",
            json={"ListId": int(list_id), "ConfirmMissingProducts": False},
        )
        return self._basket(data)

    # -- account ------------------------------------------------------------------------------

    def get_account(self) -> Account:
        """Whether the session is logged in, without any personal details."""
        self._require_login()
        return Account.from_api(self._http.get(f"{WWW}/webapi/user/GetCurrentUser") or {})


def _object(data: Any, what: str) -> dict[str, Any]:
    """The decoded body, which must be a JSON object; an empty 200 raises instead of crashing a model."""
    if not isinstance(data, dict):
        raise ApiError(200, f"expected a {what} object, got {type(data).__name__}")
    return data


def _pid(product_id: ProductId) -> str:
    pid = str(product_id).strip()
    if not pid:
        raise ValueError("empty product id")
    return pid


def _check_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
