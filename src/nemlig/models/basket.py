"""The basket and its lines."""

from __future__ import annotations

from typing import Any

from ._base import Model, money
from .delivery import DeliveryContext, ReservedSlot


class ValidationFailure(Model):
    """A warning the site shows as a dialog, e.g. "changes to basket" after a reorder."""

    group: int | None = None
    message: str | None = None
    details: dict[str, Any] = {}

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> ValidationFailure:
        message = d.get("Message") or d.get("ErrorMessage") or d.get("Text") or d.get("Description")
        return cls(
            group=d.get("Group"),
            message=message or None,
            details={k: v for k, v in d.items() if isinstance(v, str | int | float | bool) or v is None},
        )


def validation_failures(items: list[dict[str, Any]] | None) -> list[ValidationFailure]:
    return [ValidationFailure.from_api(v) for v in items or [] if isinstance(v, dict)]


class BasketLine(Model):
    product_id: str
    name: str
    brand: str | None = None
    description: str | None = None
    quantity: int
    item_price: float | None
    """Price of one unit."""
    total: float | None
    """Line total."""
    discount: float | None = None
    available: bool = True
    """False for lines left at quantity 0 because the product sold out."""
    slug: str | None = None

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> BasketLine:
        record = d.get("CheckoutHistoricalRecord") or {}
        quantity = int(d.get("Quantity") or 0)
        return cls(
            product_id=str(d["Id"]),
            name=d.get("Name") or "",
            brand=d.get("Brand") or None,
            description=d.get("Description") or None,
            quantity=quantity,
            item_price=money(d.get("ItemPrice")),
            total=money(d.get("Price")),
            discount=money(d.get("DiscountSavings")) or None,
            available=quantity > 0 and not record.get("AvailabilityStatus"),
            slug=d.get("Url") or None,
        )


class Basket(Model):
    lines: list[BasketLine]
    number_of_products: int
    products_price: float | None
    delivery_price: float | None
    bags_price: float | None = None
    deposits_price: float | None = None
    discount: float | None = None
    total_price: float | None
    minimum_order_total: float | None = None
    is_min_total_valid: bool = True
    """False while the basket is below the minimum order total."""
    delivery_slot: ReservedSlot | None = None
    validation_failures: list[ValidationFailure] = []
    delivery_context: DeliveryContext | None = None

    def quantity_of(self, product_id: str | int) -> int:
        pid = str(product_id)
        return sum(line.quantity for line in self.lines if line.product_id == pid)

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Basket:
        slot = d.get("DeliveryTimeSlot") or None
        context = None
        if d.get("TimeslotUtc") and d.get("DeliveryZoneId") is not None:
            context = DeliveryContext(
                timeslot_utc=d["TimeslotUtc"],
                zone_id=int(d["DeliveryZoneId"]),
                slot_id=int(slot["Id"]) if slot and slot.get("Id") else None,
            )
        return cls(
            lines=[BasketLine.from_api(line) for line in d.get("Lines") or []],
            number_of_products=int(d.get("NumberOfProducts") or 0),
            products_price=money(d.get("TotalProductsPrice")),
            delivery_price=money(d.get("DeliveryPrice")),
            bags_price=money(d.get("TotalBagsPrice")),
            deposits_price=money(d.get("TotalDepositsPrice")),
            discount=money(d.get("TotalProductDiscountPrice")) or None,
            total_price=money(d.get("TotalPrice")),
            minimum_order_total=money(d.get("MinimumOrderTotal")),
            is_min_total_valid=bool(d.get("IsMinTotalValid", True)),
            delivery_slot=(
                ReservedSlot.from_api(slot, d.get("FormattedDeliveryTime"))
                if slot and slot.get("Id")
                else None
            ),
            validation_failures=validation_failures(d.get("ValidationFailures")),
            delivery_context=context,
        )
