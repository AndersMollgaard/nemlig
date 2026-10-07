"""Products, search results and autocomplete suggestions."""

from __future__ import annotations

import re
from typing import Any

from ._base import Model, html_to_text, money, ore_to_kr, unit_label


def _available(availability: dict[str, Any] | None) -> bool:
    a = availability or {}
    return bool(a.get("IsDeliveryAvailable", True) and a.get("IsAvailableInStock", True))


class Swap(Model):
    """What replacing a basket line with a product would save. Set by the CLI, not the API."""

    quantity: int
    """Packs that hold about the line's amount."""
    saving: float | None
    """The line's total minus the cost of ``quantity`` packs, offers included."""
    amount: float
    """``quantity`` packs as a share of the line's amount: 1 is the same amount."""
    offer_quantity: int | None = None
    """Set when only buying this many for the multi-buy offer makes it cheaper."""


class Product(Model):
    id: str
    name: str
    brand: str | None = None
    description: str | None = None
    """Pack size and brand, e.g. ``"1 kg / Go' Morgen"``."""
    price: float | None = None
    """Current price in kroner for one unit, discounts applied."""
    original_price: float | None = None
    """Price before an offer, when known (only offers and favourites report it)."""
    unit_price: float | None = None
    unit_price_label: str | None = None
    """E.g. ``"kr/kg"``."""
    category: str | None = None
    labels: list[str] = []
    on_offer: bool = False
    offer: str | None = None
    """Offer text: a multi-buy deal like ``"3 for 50 kr"``, or a badge like ``"Spar 3,-"``."""
    offer_unit_price: float | None = None
    """``unit_price`` when buying the offer's quantity at the offer price."""
    discount: int | None = None
    """Percent off, from the price before the offer or a multi-buy deal (offers and favourites only)."""
    available: bool = True
    favourite: bool = False
    avoided: bool | None = None
    """True when an ``avoid`` rule in the household's preferences matches. Set by the CLI, not
    the API."""
    swap: Swap | None = None
    """Set by ``search --cheaper-than``."""
    slug: str | None = None
    """Path of the product page on www.nemlig.com, usable with ``get_product``."""
    image: str | None = None

    def deal(self) -> tuple[int, float] | None:
        """The offer as (count, price), for ``3 for 50 kr`` or a single-price ``16,95 kr``."""
        m = _DEAL.match(self.offer or "")
        return (int(m[1] or 1), float(m[2].replace(",", "."))) if m else None

    def cost(self, quantity: int) -> float | None:
        """What ``quantity`` packs cost, with a multi-buy price for every full set of the deal."""
        if self.price is None:
            return None
        deal = self.deal()
        if deal is None:
            return round(quantity * self.price, 2)
        count, price = deal
        if count == 1:
            return round(quantity * min(price, self.price), 2)
        return round(quantity // count * price + quantity % count * self.price, 2)

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Product:
        """From the PascalCase product shape used by search, basket lines and product pages."""
        return cls(**_pascal_fields(d))

    @classmethod
    def from_productbff(cls, d: dict[str, Any]) -> Product:
        """From the camelCase productbff shape (favourites, offers), where money is in øre."""
        badge = d.get("campaignBadge") or {}
        per_unit = d.get("pricePerUnit") or {}
        unit_label = {"Weight": "kr/kg", "Volume": "kr/l", "Pieces": "kr/stk"}.get(per_unit.get("unitType"))
        tracking = d.get("tracking") or {}
        category = "/".join(c for c in (tracking.get("item_category"), tracking.get("item_category2")) if c)
        price, original_price = ore_to_kr(d.get("price")), ore_to_kr(d.get("priceOriginal"))
        unit_price = ore_to_kr(per_unit.get("value"))
        deal = _multi_buy(d.get("campaignLines"))
        offer_unit_price = None
        if deal:
            offer = _deal_text(*deal)
            if price and unit_price is not None:
                offer_unit_price = round(unit_price * deal[1] / deal[0] / price, 2)
        else:
            offer = " ".join(t for t in (badge.get("secondaryText"), badge.get("primaryText")) if t) or None
        cuts = []
        if price and original_price:
            cuts.append(1 - price / original_price)
        if offer_unit_price is not None and unit_price:
            cuts.append(1 - offer_unit_price / unit_price)
        discount = round(100 * max(cuts)) if cuts and max(cuts) > 0 else None
        return cls(
            id=str(d["id"]),
            name=d.get("title") or "",
            brand=tracking.get("item_brand") or None,
            description=d.get("description") or None,
            price=price,
            original_price=original_price,
            unit_price=unit_price,
            unit_price_label=unit_label,
            category=category or None,
            labels=[c["text"] for c in d.get("certificates") or [] if c.get("text")],
            on_offer=bool(d.get("priceDiscount")) or bool(offer),
            offer=offer,
            offer_unit_price=offer_unit_price,
            discount=discount,
            available=(d.get("availability") or {}).get("type", "Available") == "Available",
            favourite=bool(d.get("isFavorite")),
            slug=str(d["id"]),
            image=(d.get("image") or {}).get("source"),
        )


# The offer text `_deal_text` writes.
_DEAL = re.compile(r"(?:(\d+) for )?(\d+(?:,\d+)?) kr$")


def _deal_text(count: int, price: float) -> str:
    """``3 for 50 kr``, or ``16,95 kr`` for a single-price deal."""
    text = (f"{price:g}" if price == int(price) else f"{price:.2f}").replace(".", ",") + " kr"
    return f"{count} for {text}" if count > 1 else text


def campaign_text(campaign: dict[str, Any] | None) -> str | None:
    """Search and product pages describe multi-buy deals, e.g. ``3 for 50 kr``."""
    price = money((campaign or {}).get("CampaignPrice"))
    if not campaign or price is None:
        return None
    return _deal_text(int(campaign.get("MinQuantity") or 1), price)


# productbff campaign lines: "Mix 3 stk. 38,-", "2 stk. 70,-", "Mix 3 stk. 112,50 kr."
_MULTI_BUY = re.compile(r"(?:Mix )?(\d+) stk\. (\d+)(?:,(\d+))?")


def _multi_buy(lines: list[dict[str, Any]] | None) -> tuple[int, float] | None:
    """The first multi-buy deal as (count, price in kroner)."""
    for line in lines or []:
        m = _MULTI_BUY.match(line.get("text") or "")
        if m and int(m[1]) > 1:
            return int(m[1]), float(f"{m[2]}.{m[3] or 0}")
    return None


def _offer_unit_price(d: dict[str, Any]) -> float | None:
    campaign = d.get("Campaign") or {}
    price, unit_price = money(d.get("Price")), money(d.get("UnitPriceCalc"))
    offer_price = money(campaign.get("CampaignPrice"))
    if offer_price is None or not price or unit_price is None:
        return None
    count = int(campaign.get("MinQuantity") or 1)
    return round(unit_price * offer_price / count / price, 2)


def _pascal_fields(d: dict[str, Any]) -> dict[str, Any]:
    offer = campaign_text(d.get("Campaign"))
    return {
        "id": str(d["Id"]),
        "name": d.get("Name") or "",
        "brand": d.get("Brand") or None,
        "description": d.get("Description") or None,
        "price": money(d.get("Price")),
        "unit_price": money(d.get("UnitPriceCalc")),
        "unit_price_label": unit_label(d.get("UnitPriceLabel")),
        "category": d.get("SubCategory") or d.get("Category") or None,
        "labels": list(d.get("Labels") or []),
        # DiscountItem marks the budget "Discount" range, not an offer, so it is not used here.
        "on_offer": bool(offer),
        "offer": offer,
        "offer_unit_price": _offer_unit_price(d),
        "available": _available(d.get("Availability")),
        "favourite": bool(d.get("Favorite")),
        "slug": d.get("Url") or None,
        "image": d.get("PrimaryImage") or None,
    }


class CheaperThan(Model):
    """The basket line a ``search --cheaper-than`` query was compared with."""

    product_id: str
    name: str
    description: str | None = None
    quantity: int
    total: float | None
    unit_price: float | None = None
    unit_price_label: str | None = None


class SearchResult(Model):
    query: str
    total: int
    """Number of matching products in total, not just in this page."""
    products: list[Product]
    skipped: str | None = None
    """Why the search was not run, e.g. a keep rule in the preferences."""
    than: CheaperThan | None = None
    """The basket line the products were filtered against, with ``--cheaper-than``."""

    @classmethod
    def from_api(cls, d: dict[str, Any], query: str) -> SearchResult:
        block = d.get("Products") or {}
        return cls(
            query=d.get("SearchQuery") or query,
            total=int(block.get("NumFound") or d.get("ProductsNumFound") or 0),
            products=[Product.from_api(p) for p in block.get("Products") or []],
        )


class SuggestedCategory(Model):
    name: str
    url: str


class Suggestions(Model):
    query: str
    suggestions: list[str]
    categories: list[SuggestedCategory]

    @classmethod
    def from_api(cls, d: dict[str, Any], query: str) -> Suggestions:
        return cls(
            query=d.get("SearchQuery") or query,
            suggestions=list(d.get("Suggestions") or []),
            categories=[
                SuggestedCategory(name=c.get("Name") or "", url=c.get("Url") or "")
                for c in d.get("Categories") or []
            ],
        )


class ProductDetails(Product):
    text: str | None = None
    """Marketing description, as plain text."""
    declaration: str | None = None
    """Ingredients and nutrition table, as plain text."""
    attributes: dict[str, list[str]] = {}
    """E.g. ``{"Allergener": ["Gluten", "Havre"]}``."""
    origin: str | None = None

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> ProductDetails:
        """From the ``productdetailspot`` block of a product page."""
        return cls(
            **_pascal_fields(d),
            text=html_to_text(d.get("Text")),
            declaration=html_to_text(d.get("DeclarationLabel")),
            attributes={
                a["Key"]: [str(v) for v in a.get("Value") or []]
                for a in d.get("Attributes") or []
                if a.get("Key")
            },
            origin=d.get("OriginCodeDescription") or None,
        )
