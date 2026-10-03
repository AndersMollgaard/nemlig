"""Past orders, identified by the numeric ``Id``. The customer-facing order number is not exposed."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ._base import Model, money, parse_datetime


class OrderSummary(Model):
    id: int
    """Numeric order id, used by ``get_order`` and ``reorder``."""
    status: int
    """The site's status code; delivered orders showed 3."""
    total: float | None
    subtotal: float | None = None
    delivery_start: datetime | None = None
    delivery_end: datetime | None = None
    is_editable: bool = False

    @classmethod
    def _fields(cls, d: dict[str, Any]) -> dict[str, Any]:
        time = d.get("DeliveryTime") or {}
        return {
            "id": int(d["Id"]),
            "status": int(d.get("Status") or 0),
            "total": money(d.get("Total")),
            "subtotal": money(d.get("SubTotal")),
            "delivery_start": parse_datetime(time.get("Start")),
            "delivery_end": parse_datetime(time.get("End")),
            "is_editable": bool(d.get("IsEditable")),
        }

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> OrderSummary:
        return cls(**cls._fields(d))


class OrderLine(Model):
    product_id: str
    """Works as a basket product id."""
    name: str
    description: str | None = None
    quantity: int
    item_price: float | None
    amount: float | None
    discount: float | None = None
    sold_out: bool = False
    category: str | None = None
    """The site's main group, e.g. ``"Køl"``, ``"Kolonial"`` or ``"Kød & fisk"``."""

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> OrderLine:
        return cls(
            product_id=str(d["ProductNumber"]),
            name=d.get("ProductName") or "",
            description=d.get("Description") or None,
            quantity=int(d.get("Quantity") or 0),
            item_price=money(d.get("AverageItemPrice")),
            amount=money(d.get("Amount")),
            discount=money(d.get("DiscountAmount")) or None,
            sold_out=bool(d.get("SoldOut")),
            category=d.get("MainGroupName") or None,
        )


class Order(OrderSummary):
    lines: list[OrderLine]
    """Product lines only; deposit, recipe and meal-box lines are left out."""
    number_of_products: int = 0
    delivery_price: float | None = None
    deposit_price: float | None = None
    packaging_price: float | None = None
    discount: float | None = None

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Order:
        return cls(
            **cls._fields(d),
            lines=[
                OrderLine.from_api(line)
                for line in d.get("Lines") or []
                if line.get("IsProductLine", True) and line.get("ProductNumber")
            ],
            number_of_products=int(d.get("NumberOfProducts") or 0),
            delivery_price=money(d.get("ShippingPrice")),
            deposit_price=money(d.get("DepositPrice")),
            packaging_price=money(d.get("PackagingPrice")),
            discount=money(d.get("TotalProductDiscount")) or None,
        )
