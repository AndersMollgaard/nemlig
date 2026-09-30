"""Command-line interface to nemlig.com, meant to be driven by an agent (or a person).

Every command prints one JSON document on stdout, or a compact text view with ``--text``. Errors
go to stderr as ``{"error": ..., "message": ...}`` with a non-zero exit code (see ``EPILOG``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from . import preferences
from ._version import __version__
from .client import NemligClient
from .errors import ApiError, AuthError, NemligError, NotLoggedInError
from .models import (
    Basket,
    BasketLine,
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
from .preferences import Preferences, Rule

EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_LOGIN = 3

# Fields left out of the JSON output: long URLs that cost tokens and are not needed to act.
_NOISE = {"image", "slug", "delivery_context", "details"}

DESCRIPTION = "Search nemlig.com and manage the basket. Unofficial; checkout is not supported."

EPILOG = """\
typical flow:
  nemlig search "havregryn" --limit 5     pick a product "id" from the results
  nemlig search mælk "hakket oksekød" æg   several queries in parallel: a list of results
  nemlig search minimælk kaffe --cheaper-than 701013 5027015
                                           per query, only what costs less per kg/l/stk than that
                                           basket line (not per pack)
  nemlig basket add 5050406:2 5043017      add 2 of one product and 1 of another
  nemlig basket                            show the basket and its totals

notes:
  basket add is additive (running it twice adds twice); basket set is absolute (0 removes).
  After an error or a timeout, check `nemlig basket` and use `basket set` rather than
  repeating `basket add`.
  Prices, stock and offers depend on the delivery slot. They are for the basket's slot (or the
  site's default when anonymous); search and offers take --slot SLOT_ID to see another one.
  Output is JSON on stdout; --text gives a compact human view. Fields that are null or empty
  are left out.
  Credentials: NEMLIG_USER and NEMLIG_PASS in the environment, in --env-file, in ./.env, or in
  ~/.config/nemlig/.env. The session is saved, so later runs skip the login.
  Preferences: preferences.toml next to that .env (or NEMLIG_PREFS_FILE). `prefs keep` and
  `prefs avoid` add rules that search --cheaper-than applies.

exit codes:
  0 ok, 1 nemlig.com or network error, 2 bad usage, 3 not logged in or login rejected.
  Errors are printed to stderr as {"error": ..., "message": ...}.
"""


SLOT_HELP = "price for this delivery slot (from `delivery`) without reserving it"


class UsageError(Exception):
    """Bad arguments that argparse cannot catch by itself."""


class PartialError(Exception):
    """A multi-item command failed after applying some of its items."""

    def __init__(self, cause: Exception, applied: list[str]) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.applied = applied


# -- argument types ---------------------------------------------------------------------------


def _item(spec: str, *, need_qty: bool) -> tuple[str, int]:
    pid, sep, qty = spec.partition(":")
    pid = pid.strip()
    if not pid or (need_qty and not sep):
        want = "ID:QTY" if need_qty else "ID or ID:QTY"
        raise argparse.ArgumentTypeError(f"expected {want}, got {spec!r}")
    if not sep:
        return pid, 1
    try:
        return pid, int(qty)
    except ValueError:
        raise argparse.ArgumentTypeError(f"quantity must be a whole number in {spec!r}") from None


def add_item(spec: str) -> tuple[str, int]:
    return _item(spec, need_qty=False)


def set_item(spec: str) -> tuple[str, int]:
    return _item(spec, need_qty=True)


def iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a date like 2026-09-30, got {value!r}") from None


# -- commands ---------------------------------------------------------------------------------


def _each(items: Sequence[tuple[str, int]], apply: Callable[[str, int], Basket]) -> Basket:
    applied: list[str] = []
    basket: Basket | None = None
    for pid, qty in items:
        try:
            basket = apply(pid, qty)
        except Exception as exc:
            raise PartialError(exc, applied) from exc
        applied.append(f"{pid}:{qty}")
    assert basket is not None
    return basket


def _confirm(args: argparse.Namespace, what: str) -> None:
    if not args.yes:
        raise UsageError(f"{what} is not undoable; pass --yes to confirm")


def _basket_lines(nc: NemligClient, ids: Sequence[str], queries: Sequence[str]) -> list[BasketLine]:
    if len(ids) != len(queries):
        raise UsageError(
            f"--cheaper-than needs one basket product id per query ({len(queries)} queries, {len(ids)} ids)"
        )
    lines = {line.product_id: line for line in nc.get_basket().lines}
    missing = [pid for pid in ids if pid not in lines]
    if missing:
        raise UsageError(f"not in the basket: {', '.join(missing)}")
    return [lines[pid] for pid in ids]


def _cheaper(result: SearchResult, line: BasketLine, prefs: Preferences) -> SearchResult:
    """Only in-stock products in the line's unit (kr/kg, kr/l, kr/stk) that cost less per kg, l or
    piece, offers included, and that no avoid rule matches. Shelf prices are not compared, so a
    bigger pack can cost more in total."""
    if line.unit_price is None:
        return result

    def best(p: Product) -> float | None:
        prices = [x for x in (p.unit_price, p.offer_unit_price) if x is not None]
        return min(prices) if prices else None

    keep = [
        p
        for p in result.products
        if p.available
        and p.id != line.product_id
        and p.unit_price_label == line.unit_price_label
        and (unit := best(p)) is not None
        and unit < line.unit_price
        and not prefs.avoided(p.id, p.name, p.brand)
    ]
    return result.model_copy(update={"products": keep})


def _search_cheaper(nc: NemligClient, a: argparse.Namespace) -> list[SearchResult]:
    """Search only for the lines no keep rule protects, and filter what comes back."""
    prefs = preferences.load(_prefs_file(a))
    lines = _basket_lines(nc, a.cheaper_than, a.queries)
    kept = [prefs.kept_by(line.product_id, line.name, line.brand) for line in lines]
    todo = [q for q, rule in zip(a.queries, kept, strict=True) if rule is None]
    found = iter(nc.search_many(todo, limit=a.limit, offset=a.offset, slot_id=a.slot) if todo else [])
    return [
        SearchResult(query=q, total=0, products=[], skipped=f"keep rule {rule.describe()}")
        if rule is not None
        else _cheaper(next(found), line, prefs)
        for q, line, rule in zip(a.queries, lines, kept, strict=True)
    ]


def cmd_search(nc: NemligClient, a: argparse.Namespace) -> Any:
    if a.cheaper_than:
        results = _search_cheaper(nc, a)
    else:
        results = nc.search_many(a.queries, limit=a.limit, offset=a.offset, slot_id=a.slot)
    return results[0] if len(results) == 1 else results


def cmd_suggest(nc: NemligClient, a: argparse.Namespace) -> Any:
    return nc.suggest(a.query)


def cmd_product(nc: NemligClient, a: argparse.Namespace) -> Any:
    return nc.get_product(a.product)


def cmd_basket_show(nc: NemligClient, a: argparse.Namespace) -> Any:
    return nc.get_basket()


def cmd_basket_add(nc: NemligClient, a: argparse.Namespace) -> Any:
    return _each(a.items, nc.add_to_basket)


def cmd_basket_set(nc: NemligClient, a: argparse.Namespace) -> Any:
    return _each(a.items, nc.set_quantity)


def cmd_basket_remove(nc: NemligClient, a: argparse.Namespace) -> Any:
    return _each([(pid, 0) for pid in a.ids], nc.set_quantity)


def cmd_basket_remove_sold_out(nc: NemligClient, a: argparse.Namespace) -> Any:
    return nc.remove_sold_out()


def cmd_basket_clear(nc: NemligClient, a: argparse.Namespace) -> Any:
    _confirm(a, "clearing the basket")
    return nc.clear_basket()


def cmd_delivery(nc: NemligClient, a: argparse.Namespace) -> Any:
    days = nc.get_delivery_days(days=a.days, start=a.start)
    if a.available:
        days = [d.model_copy(update={"slots": [s for s in d.slots if s.is_available]}) for d in days]
        days = [d for d in days if d.slots]
    return days


def cmd_delivery_reserve(nc: NemligClient, a: argparse.Namespace) -> Any:
    return nc.reserve_slot(a.slot_id)


def cmd_orders(nc: NemligClient, a: argparse.Namespace) -> Any:
    return nc.get_orders(limit=a.limit, page=a.page)


def cmd_orders_show(nc: NemligClient, a: argparse.Namespace) -> Any:
    return nc.get_order(a.order_id)


def cmd_orders_reorder(nc: NemligClient, a: argparse.Namespace) -> Any:
    return nc.reorder(a.order_id)


def cmd_favourites(nc: NemligClient, a: argparse.Namespace) -> Any:
    return nc.get_favourites()


def cmd_offers(nc: NemligClient, a: argparse.Namespace) -> Any:
    return nc.get_offers(limit=a.limit or None, slot_id=a.slot)


def cmd_lists(nc: NemligClient, a: argparse.Namespace) -> Any:
    return nc.get_shopping_lists()


def cmd_lists_show(nc: NemligClient, a: argparse.Namespace) -> Any:
    return nc.get_shopping_list(a.list_id)


def cmd_lists_create(nc: NemligClient, a: argparse.Namespace) -> Any:
    return nc.create_shopping_list(a.name)


def cmd_lists_set(nc: NemligClient, a: argparse.Namespace) -> Any:
    applied: list[str] = []
    result: ShoppingList | None = None
    for pid, qty in a.items:
        try:
            result = nc.set_shopping_list_item(a.list_id, pid, qty)
        except Exception as exc:
            raise PartialError(exc, applied) from exc
        applied.append(f"{pid}:{qty}")
    return result


def cmd_lists_delete(nc: NemligClient, a: argparse.Namespace) -> Any:
    _confirm(a, "deleting a shopping list")
    nc.delete_shopping_list(a.list_id)
    return {"ok": True}


def cmd_lists_to_basket(nc: NemligClient, a: argparse.Namespace) -> Any:
    return nc.add_shopping_list_to_basket(a.list_id)


class PrefsView(BaseModel):
    file: str
    exists: bool
    preferences: Preferences


def _prefs_view(a: argparse.Namespace) -> PrefsView:
    path = _prefs_file(a)
    return PrefsView(file=str(path.resolve()), exists=path.is_file(), preferences=preferences.load(path))


def cmd_prefs(nc: NemligClient, a: argparse.Namespace) -> Any:
    return _prefs_view(a)


def cmd_prefs_add(nc: NemligClient, a: argparse.Namespace) -> Any:
    rule = Rule(id=a.id, brand=a.brand, name=a.name, note=a.note)
    preferences.add_rule(_prefs_file(a), a.kind, rule)
    return _prefs_view(a)


def _status(nc: NemligClient) -> dict[str, Any]:
    logged_in = nc.is_logged_in()
    out: dict[str, Any] = {"logged_in": logged_in, "has_credentials": nc.has_credentials}
    if logged_in:
        account = nc.get_account()
        out["has_upcoming_order"] = account.has_upcoming_order
    return out


def cmd_status(nc: NemligClient, a: argparse.Namespace) -> Any:
    return _status(nc)


def cmd_login(nc: NemligClient, a: argparse.Namespace) -> Any:
    nc.login()
    return _status(nc)


def cmd_logout(nc: NemligClient, a: argparse.Namespace) -> Any:
    nc.logout()
    return {"ok": True}


# -- parser -----------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    # --text is accepted before or after the subcommand; SUPPRESS keeps a subparser from resetting it.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--text", action="store_true", default=argparse.SUPPRESS, help="compact human-readable output"
    )

    p = argparse.ArgumentParser(
        prog="nemlig",
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[common],
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--env-file", help="file with NEMLIG_USER / NEMLIG_PASS (see credentials below)")
    p.add_argument("--session-file", help="where the login session is saved (default ~/.config/nemlig)")
    p.add_argument("--no-session", action="store_true", help="do not read or save the login session")
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def cmd(parent: Any, name: str, func: Callable[..., Any], help: str) -> argparse.ArgumentParser:
        sp = parent.add_parser(name, help=help, description=help, parents=[common])
        sp.set_defaults(func=func)
        return sp

    sp = cmd(sub, "search", cmd_search, "search products; several queries run in parallel")
    sp.add_argument("queries", nargs="+", metavar="QUERY", help="one or more queries (quote multi-word ones)")
    sp.add_argument("--limit", type=int, default=10, help="products per query (default 10)")
    sp.add_argument("--offset", type=int, default=0, help="products to skip, for paging")
    sp.add_argument("--slot", type=int, metavar="SLOT_ID", help=SLOT_HELP)
    sp.add_argument(
        "--cheaper-than",
        nargs="+",
        metavar="ID",
        help="basket product ids, one per query in order: keep only in-stock products in the same "
        "unit that cost less per kg, l or piece (kr/kg, kr/l, kr/stk; offers included), not per pack. "
        "Put it after the queries",
    )

    sp = cmd(sub, "suggest", cmd_suggest, "autocomplete: search terms and categories")
    sp.add_argument("query")

    sp = cmd(sub, "product", cmd_product, "product details: text, ingredients, nutrition, allergens")
    sp.add_argument("product", help="product id or slug")

    basket = cmd(sub, "basket", cmd_basket_show, "show or change the basket (default: show)")
    bsub = basket.add_subparsers(metavar="ACTION")
    cmd(bsub, "show", cmd_basket_show, "show the basket")
    sp = cmd(bsub, "add", cmd_basket_add, "add on top of what is there (ID or ID:QTY; negative subtracts)")
    sp.add_argument("items", nargs="+", type=add_item, metavar="ID[:QTY]")
    sp = cmd(bsub, "set", cmd_basket_set, "set absolute quantities (ID:QTY; 0 removes)")
    sp.add_argument("items", nargs="+", type=set_item, metavar="ID:QTY")
    sp = cmd(bsub, "remove", cmd_basket_remove, "remove products from the basket")
    sp.add_argument("ids", nargs="+", metavar="ID")
    cmd(bsub, "remove-sold-out", cmd_basket_remove_sold_out, "remove sold-out lines left at quantity 0")
    sp = cmd(bsub, "clear", cmd_basket_clear, "empty the basket (needs --yes)")
    sp.add_argument("--yes", action="store_true", help="confirm")

    delivery = cmd(sub, "delivery", cmd_delivery, "delivery days and timeslots, or reserve a slot")
    delivery.add_argument("--days", type=int, default=7, help="number of days (default 7)")
    delivery.add_argument("--start", type=iso_date, help="first day, YYYY-MM-DD (default today)")
    delivery.add_argument("--available", action="store_true", help="only slots that can be booked")
    dsub = delivery.add_subparsers(metavar="ACTION")
    sp = cmd(dsub, "reserve", cmd_delivery_reserve, "reserve a delivery slot for the basket")
    sp.add_argument("slot_id", type=int)

    orders = cmd(sub, "orders", cmd_orders, "past orders, newest first; show one or reorder it")
    orders.add_argument("--limit", type=int, default=10, help="orders per page (default 10)")
    orders.add_argument("--page", type=int, default=1, help="1-based page")
    osub = orders.add_subparsers(metavar="ACTION")
    sp = cmd(osub, "show", cmd_orders_show, "one order with its product lines")
    sp.add_argument("order_id", type=int)
    sp = cmd(osub, "reorder", cmd_orders_reorder, "add every product of a past order to the basket")
    sp.add_argument("order_id", type=int)

    cmd(sub, "favourites", cmd_favourites, "the account's favourite products")

    sp = cmd(sub, "offers", cmd_offers, "offers for the delivery slot")
    sp.add_argument("--limit", type=int, default=20, help="max products (default 20, 0 for all)")
    sp.add_argument("--slot", type=int, metavar="SLOT_ID", help=SLOT_HELP)

    lists = cmd(sub, "lists", cmd_lists, "shopping lists (default: list them)")
    lsub = lists.add_subparsers(metavar="ACTION")
    sp = cmd(lsub, "show", cmd_lists_show, "one shopping list with its products")
    sp.add_argument("list_id", type=int)
    sp = cmd(lsub, "create", cmd_lists_create, "create a shopping list")
    sp.add_argument("name")
    sp = cmd(lsub, "set", cmd_lists_set, "set product quantities in a list (ID:QTY; 0 removes)")
    sp.add_argument("list_id", type=int)
    sp.add_argument("items", nargs="+", type=set_item, metavar="ID:QTY")
    sp = cmd(lsub, "delete", cmd_lists_delete, "delete a shopping list (needs --yes)")
    sp.add_argument("list_id", type=int)
    sp.add_argument("--yes", action="store_true", help="confirm")
    sp = cmd(lsub, "to-basket", cmd_lists_to_basket, "add a list's products to the basket")
    sp.add_argument("list_id", type=int)

    prefs = cmd(sub, "prefs", cmd_prefs, "household preferences, and rules for products to keep or avoid")
    psub = prefs.add_subparsers(metavar="ACTION")
    for kind, help in (
        ("keep", "never replace matching basket lines (search --cheaper-than skips them)"),
        ("avoid", "never suggest matching products as replacements (search --cheaper-than drops them)"),
    ):
        sp = cmd(psub, kind, cmd_prefs_add, help)
        sp.set_defaults(kind=kind)
        sp.add_argument("--id", help="product id")
        sp.add_argument("--brand", help="brand, ignoring case")
        sp.add_argument("--name", help="part of the product name, ignoring case")
        sp.add_argument("--note", help="why, shown with the rule")

    cmd(sub, "status", cmd_status, "whether a login session and credentials are available")
    cmd(sub, "login", cmd_login, "log in with the configured credentials and save the session")
    cmd(sub, "logout", cmd_logout, "forget the saved session")
    return p


# -- client -----------------------------------------------------------------------------------


def _env_file(arg: str | None) -> Path:
    if arg:
        return Path(arg).expanduser()
    if os.environ.get("NEMLIG_ENV_FILE"):
        return Path(os.environ["NEMLIG_ENV_FILE"]).expanduser()
    local = Path(".env")
    if local.is_file():
        return local
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "nemlig" / ".env"


def _prefs_file(a: argparse.Namespace) -> Path:
    """``preferences.toml`` next to the `.env` in use, unless ``NEMLIG_PREFS_FILE`` says otherwise."""
    if os.environ.get("NEMLIG_PREFS_FILE"):
        return Path(os.environ["NEMLIG_PREFS_FILE"]).expanduser()
    return _env_file(a.env_file).parent / "preferences.toml"


def make_client(a: argparse.Namespace) -> NemligClient:
    return NemligClient.from_env(_env_file(a.env_file), session_file=a.session_file, persist=not a.no_session)


# -- output -----------------------------------------------------------------------------------


def to_json(value: Any) -> Any:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=True)
    return _prune(value)


def _prune(value: Any) -> Any:
    if isinstance(value, dict):
        out = {k: _prune(v) for k, v in value.items() if k not in _NOISE}
        return {k: v for k, v in out.items() if v is not None and v != [] and v != {}}
    if isinstance(value, list):
        return [_prune(v) for v in value]
    if isinstance(value, BaseModel):
        return to_json(value)
    return value


def _kr(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f} kr"


def _product_row(p: Product) -> str:
    parts = [p.id, p.name]
    if p.description:
        parts.append(p.description)
    price = _kr(p.price)
    if p.unit_price is not None and p.unit_price_label:
        price += f" ({p.unit_price:.2f} {p.unit_price_label})"
    parts.append(price)
    if p.offer:
        offer = f"offer: {p.offer}"
        if p.offer_unit_price is not None and p.unit_price_label:
            offer += f" ({p.offer_unit_price:.2f} {p.unit_price_label})"
        parts.append(offer)
    if not p.available:
        parts.append("SOLD OUT")
    return "  ".join(parts)


def _text_details(p: ProductDetails) -> str:
    lines = [_product_row(p)]
    for label, value in (("brand", p.brand), ("category", p.category), ("origin", p.origin)):
        if value:
            lines.append(f"{label}: {value}")
    if p.labels:
        lines.append("labels: " + ", ".join(p.labels))
    for key, values in p.attributes.items():
        lines.append(f"{key}: {', '.join(values)}")
    for block in (p.text, p.declaration):
        if block:
            lines += ["", block]
    return "\n".join(lines)


def _text_basket(b: Basket) -> str:
    lines = [
        f"{line.quantity} x {line.name}"
        + (f" ({line.description})" if line.description else "")
        + f"  [{line.product_id}]  {_kr(line.total)}"
        + ("  SOLD OUT" if not line.available else "")
        for line in b.lines
    ] or ["(empty basket)"]
    lines.append(
        f"products {_kr(b.products_price)}, delivery {_kr(b.delivery_price)}, total {_kr(b.total_price)}"
    )
    if b.discount:
        lines.append(f"discount {_kr(b.discount)}")
    if not b.is_min_total_valid:
        lines.append(f"below the minimum order total of {_kr(b.minimum_order_total)}")
    if b.delivery_slot:
        slot = b.delivery_slot
        state = "reserved" if slot.reserved and not slot.reservation_lost else "not reserved"
        lines.append(f"delivery: {slot.label or slot.start} ({state})")
    lines += [f"warning: {v.message}" for v in b.validation_failures if v.message]
    return "\n".join(lines)


def _text_day(d: DeliveryDay) -> str:
    lines = [str(d.date)]
    for s in d.slots:
        state = getattr(s.availability, "name", str(s.availability)).lower().replace("_", " ")
        mark = "  (selected)" if s.selected else ""
        lines.append(f"  {s.id}  {s.start_hour:02d}-{s.end_hour:02d}  {_kr(s.price)}  {state}{mark}")
    return "\n".join(lines)


def _text_order(o: OrderSummary) -> str:
    when = o.delivery_start.strftime("%Y-%m-%d %H:%M") if o.delivery_start else "-"
    head = f"{o.id}  {when}  {_kr(o.total)}  status {o.status}"
    if not isinstance(o, Order):
        return head
    lines = [head] + [
        f"  {line.quantity} x {line.name}  [{line.product_id}]  {_kr(line.amount)}"
        + ("  SOLD OUT" if line.sold_out else "")
        for line in o.lines
    ]
    return "\n".join(lines)


def _text_prefs(v: PrefsView) -> str:
    p = v.preferences
    lines = [f"file: {v.file}" + ("" if v.exists else " (not created yet)")]
    lines += [f"{k}: {getattr(p, k)}" for k in ("household", "diet", "always", "budget") if getattr(p, k)]
    lines += [f"keep: {r.describe()}" for r in p.keep]
    lines += [f"avoid: {r.describe()}" for r in p.avoid]
    return "\n".join(lines)


def _text_list(s: ShoppingListSummary) -> str:
    head = f"{s.id}  {s.name}  {s.product_count} products  {_kr(s.total)}"
    if not isinstance(s, ShoppingList):
        return head
    items = [
        f"  {i.quantity} x {i.name}  [{i.product_id}]  {_kr(i.total)}" + ("" if i.available else "  SOLD OUT")
        for i in s.items
    ]
    return "\n".join([head, *items])


def to_text(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(to_text(v) for v in value) if value else "(none)"
    if isinstance(value, SearchResult):
        if value.skipped:
            return f"skipped {value.query!r}: {value.skipped}"
        head = f"{len(value.products)} of {value.total} results for {value.query!r}"
        return "\n".join([head, *(_product_row(p) for p in value.products)])
    if isinstance(value, Suggestions):
        cats = [f"category: {c.name}  {c.url}" for c in value.categories]
        return "\n".join([*value.suggestions, *cats]) or "(no suggestions)"
    if isinstance(value, ProductDetails):
        return _text_details(value)
    if isinstance(value, Product):
        return _product_row(value)
    if isinstance(value, Basket):
        return _text_basket(value)
    if isinstance(value, DeliveryDay):
        return _text_day(value)
    if isinstance(value, OrderSummary):
        return _text_order(value)
    if isinstance(value, ShoppingListSummary):
        return _text_list(value)
    if isinstance(value, SlotReservation):
        slot = value.slot.label if value.slot else "no slot"
        return f"{'reserved' if value.reserved else 'not reserved'}: {slot}" + (
            f" ({value.message})" if value.message else ""
        )
    if isinstance(value, PrefsView):
        return _text_prefs(value)
    if isinstance(value, dict):
        return "\n".join(f"{k}: {v}" for k, v in value.items())
    return json.dumps(to_json(value), ensure_ascii=False, indent=2)


# -- errors -----------------------------------------------------------------------------------


def _error(exc: Exception) -> tuple[int, dict[str, Any]]:
    applied = None
    if isinstance(exc, PartialError):
        applied, exc = exc.applied, exc.cause
    info: dict[str, Any] = {"error": type(exc).__name__, "message": str(exc)}
    if isinstance(exc, NotLoggedInError | AuthError):
        code = EXIT_LOGIN
        info["message"] += (
            ". Set NEMLIG_USER and NEMLIG_PASS (environment, --env-file, ./.env or ~/.config/nemlig/.env)"
        )
    elif isinstance(exc, ApiError):
        code = EXIT_ERROR
        info["status"] = exc.status
        if exc.error_code is not None:
            info["error_code"] = exc.error_code
    elif isinstance(exc, NemligError | httpx.HTTPError | ValidationError):
        code = EXIT_ERROR
    elif isinstance(exc, UsageError | ValueError | TypeError):
        code = EXIT_USAGE
    else:
        code = EXIT_ERROR
    if applied is not None:
        info["applied"] = applied
    return code, info


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # --help, --version, or a usage error already printed by argparse
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    text = getattr(args, "text", False)
    try:
        with make_client(args) as nc:
            result = args.func(nc, args)
    except Exception as exc:
        code, info = _error(exc)
        if text:
            message = info["message"]
            if "applied" in info:
                message += f" (applied before the error: {', '.join(info['applied']) or 'none'})"
            print(f"error: {message}", file=sys.stderr)
        else:
            print(json.dumps(info, ensure_ascii=False), file=sys.stderr)
        return code
    if text:
        print(to_text(result))
    else:
        print(json.dumps(to_json(result), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
