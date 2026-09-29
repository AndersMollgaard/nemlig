"""Shared model base and parsing helpers."""

from __future__ import annotations

import html
import re
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    """Public models are snake_case, immutable, and built from API dicts by ``from_api``.

    Only fields worth showing are mapped. Personal data in the responses (addresses, email,
    phone, notes, DebitorId, basket GUIDs, order numbers) is never read, so it cannot leak into a
    CLI or an LLM's context.
    """

    model_config = ConfigDict(frozen=True)


def money(value: Any) -> float | None:
    """Decimal kroner as the API sends them, rounded to øre."""
    if value is None or value == "":
        return None
    return round(float(value), 2)


def ore_to_kr(value: Any) -> float | None:
    """productbff sends integer øre."""
    if value is None:
        return None
    return round(int(value) / 100, 2)


_UNITS = {"ltr": "l", "liter": "l"}


def unit_label(value: Any) -> str | None:
    """Unit-price label in one spelling: search says ``kr/kg``, the basket ``kr./Kg.``."""
    if not value:
        return None
    label = str(value).lower().replace(".", "").replace(" ", "")
    currency, sep, unit = label.partition("/")
    return f"{currency}/{_UNITS.get(unit, unit)}" if sep else label


def parse_datetime(value: Any) -> datetime | None:
    if not value or str(value).startswith("0001-01-01"):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_date(value: Any) -> date | None:
    dt = parse_datetime(value)
    return dt.date() if dt else None


_BLOCK_END = re.compile(r"<\s*(br\s*/?|/p|/h\d|/tr|/li|/div|/table)\s*>", re.I)
_CELL_END = re.compile(r"<\s*/t[dh]\s*>", re.I)
_TAG = re.compile(r"<[^>]+>")


def html_to_text(value: str | None) -> str | None:
    """Flatten the small HTML fragments nemlig uses in product texts to readable plain text."""
    if not value:
        return None
    text = _BLOCK_END.sub("\n", value)
    text = _CELL_END.sub(" ", text)
    text = html.unescape(_TAG.sub("", text))
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n")]
    out = "\n".join(line for line in lines if line)
    return out or None
