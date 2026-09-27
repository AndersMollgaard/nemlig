"""Products, search results and autocomplete suggestions."""

from __future__ import annotations

from typing import Any

from ._base import Model, html_to_text, money, ore_to_kr


def _available(availability: dict[str, Any] | None) -> bool:
    a = availability or {}
    return bool(a.get("IsDeliveryAvailable", True) and a.get("IsAvailableInStock", True))


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
    available: bool = True
    favourite: bool = False
    slug: str | None = None
    """Path of the product page on www.nemlig.com, usable with ``get_product``."""
    image: str | None = None

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Product:
        """From the PascalCase product shape used by search, basket lines and product pages."""
        return cls(**_pascal_fields(d))

    @classmethod
    def from_productbff(cls, d: dict[str, Any]) -> Product:
        """From the camelCase productbff shape (favourites, offers), where money is in øre."""
        badge = d.get("campaignBadge") or {}
        offer = " ".join(t for t in (badge.get("secondaryText"), badge.get("primaryText")) if t) or None
        per_unit = d.get("pricePerUnit") or {}
        unit_label = {"Weight": "kr/kg", "Volume": "kr/l", "Pieces": "kr/stk"}.get(per_unit.get("unitType"))
        tracking = d.get("tracking") or {}
        return cls(
            id=str(d["id"]),
            name=d.get("title") or "",
            brand=tracking.get("item_brand") or None,
            description=d.get("description"),
            price=ore_to_kr(d.get("price")),
            original_price=ore_to_kr(d.get("priceOriginal")),
            unit_price=ore_to_kr(per_unit.get("value")),
            unit_price_label=unit_label,
            category=tracking.get("item_category2") or tracking.get("item_category") or None,
            labels=[c["text"] for c in d.get("certificates") or [] if c.get("text")],
            on_offer=bool(d.get("priceDiscount")) or bool(offer),
            offer=offer,
            available=(d.get("availability") or {}).get("type", "Available") == "Available",
            favourite=bool(d.get("isFavorite")),
            slug=str(d["id"]),
            image=(d.get("image") or {}).get("source"),
        )


def _campaign_text(campaign: dict[str, Any] | None) -> str | None:
    """Search and product pages describe multi-buy deals, e.g. ``3 for 50 kr``."""
    if not campaign or campaign.get("CampaignPrice") is None:
        return None
    price = f"{money(campaign['CampaignPrice']):g} kr".replace(".", ",")
    count = int(campaign.get("MinQuantity") or 1)
    return f"{count} for {price}" if count > 1 else price


def _pascal_fields(d: dict[str, Any]) -> dict[str, Any]:
    offer = _campaign_text(d.get("Campaign"))
    return {
        "id": str(d["Id"]),
        "name": d.get("Name") or "",
        "brand": d.get("Brand") or None,
        "description": d.get("Description") or None,
        "price": money(d.get("Price")),
        "unit_price": money(d.get("UnitPriceCalc")),
        "unit_price_label": d.get("UnitPriceLabel") or None,
        "category": d.get("SubCategory") or d.get("Category") or None,
        "labels": list(d.get("Labels") or []),
        # DiscountItem marks the budget "Discount" range, not an offer, so it is not used here.
        "on_offer": bool(offer),
        "offer": offer,
        "available": _available(d.get("Availability")),
        "favourite": bool(d.get("Favorite")),
        "slug": d.get("Url") or None,
        "image": d.get("PrimaryImage") or None,
    }


class SearchResult(Model):
    query: str
    total: int
    """Number of matching products in total, not just in this page."""
    products: list[Product]

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
