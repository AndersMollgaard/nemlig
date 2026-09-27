"""Delivery context, days and timeslots."""

from __future__ import annotations

from datetime import date, datetime
from enum import IntEnum
from typing import Any

from ._base import Model, html_to_text, money, parse_date, parse_datetime


class DeliveryContext(Model):
    """What search and productbff need to price products and check stock.

    ``timeslot_utc`` is an opaque string like ``"2026092909-120-1260"``. It comes from the logged-in
    basket, or from the site's bootstrap settings for anonymous use.
    """

    timeslot_utc: str
    zone_id: int
    slot_id: int | None = None


class SlotAvailability(IntEnum):
    AVAILABLE = 0
    PAST_DEADLINE = 1
    SOLD_OUT = 2
    NOT_ACTIVE = 3


class DeliverySlot(Model):
    id: int
    date: date
    start_hour: int
    end_hour: int
    price: float | None
    deadline: datetime | None
    """Last time to order for this slot."""
    availability: SlotAvailability | int
    selected: bool = False
    """True for the slot currently reserved for the basket."""
    type: int = 0
    """The site's slot type; 1 marks the long early-morning slots."""

    @property
    def is_available(self) -> bool:
        return self.availability == SlotAvailability.AVAILABLE

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> DeliverySlot:
        raw = d.get("Availability", 0)
        try:
            availability: SlotAvailability | int = SlotAvailability(raw)
        except ValueError:
            availability = int(raw)
        return cls(
            id=int(d["Id"]),
            date=parse_date(d.get("Date")) or date.min,
            start_hour=int(d.get("StartHour", 0)),
            end_hour=int(d.get("EndHour", 0)),
            price=money(d.get("DeliveryPrice")),
            deadline=parse_datetime(d.get("Deadline")),
            availability=availability,
            selected=bool(d.get("IsSelected")),
            type=int(d.get("Type") or 0),
        )


class DeliveryDay(Model):
    date: date
    slots: list[DeliverySlot]
    note: str | None = None
    """The site's ordering-deadline text for that day, as plain text."""

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> DeliveryDay:
        return cls(
            date=parse_date(d.get("Date")) or date.min,
            slots=[DeliverySlot.from_api(s) for s in d.get("DayHours") or []],
            note=html_to_text(d.get("DeliveryText")),
        )


class ReservedSlot(Model):
    """The basket's delivery slot."""

    id: int
    start: datetime | None
    end_hour: int
    reserved: bool
    reservation_lost: bool = False
    label: str | None = None
    """The site's short text, e.g. ``"tirs. 29/09 kl. 11-13"``."""

    @classmethod
    def from_api(cls, d: dict[str, Any], label: str | None = None) -> ReservedSlot:
        return cls(
            id=int(d["Id"]),
            start=parse_datetime(d.get("Date")),
            end_hour=int(d.get("EndTime") or 0),
            reserved=bool(d.get("Reserved")),
            reservation_lost=bool(d.get("ReservationLost")),
            label=label or None,
        )


class SlotReservation(Model):
    reserved: bool
    slot: ReservedSlot | None
    message: str | None = None
