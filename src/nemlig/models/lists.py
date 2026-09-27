"""Shopping lists and the non-personal parts of the account."""

from __future__ import annotations

from typing import Any

from ._base import Model, money


class ShoppingListSummary(Model):
    id: int
    name: str
    product_count: int
    total: float | None

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> ShoppingListSummary:
        return cls(
            id=int(d["Id"]),
            name=d.get("Name") or "",
            product_count=int(d.get("ProductsCount") or 0),
            total=money(d.get("TotalAmount")),
        )


class ShoppingListItem(Model):
    product_id: str
    name: str
    description: str | None = None
    quantity: int
    item_price: float | None
    total: float | None
    available: bool = True

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> ShoppingListItem:
        availability = d.get("Availability") or {}
        return cls(
            product_id=str(d["Id"]),
            name=d.get("Name") or "",
            description=d.get("Description") or None,
            quantity=int(d.get("Quantity") or 0),
            item_price=money(d.get("ItemPrice")),
            total=money(d.get("ProductsTotalAmount")),
            available=not d.get("IsProductDeactivated")
            and bool(availability.get("IsDeliveryAvailable", True))
            and bool(availability.get("IsAvailableInStock", True)),
        )


class ShoppingList(ShoppingListSummary):
    items: list[ShoppingListItem]

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> ShoppingList:
        return cls(
            **ShoppingListSummary.from_api(d).model_dump(),
            items=[ShoppingListItem.from_api(line) for line in d.get("Lines") or []],
        )


class Account(Model):
    """Deliberately excludes name, email, addresses and phone numbers."""

    logged_in: bool
    member_type: int | None = None
    has_upcoming_order: bool = False

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Account:
        return cls(
            logged_in=bool(d.get("DebitorId")),
            member_type=d.get("MemberType"),
            has_upcoming_order=bool(d.get("UpcomingOrder")),
        )
