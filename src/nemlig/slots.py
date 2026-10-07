"""Suggest a delivery slot from the household's past orders and the slot prices.

A past order votes for an offered slot by how much their windows overlap (hours in common over
hours in either, so 16-19 counts 0.6 for 16-21). Votes decay with an `HALF_LIFE`-order
half-life, and orders on the slot's weekday count `SAME_DAY` times as much, because the window
goes with the day: Sunday mornings, Friday afternoons. Over several days, a day's decayed share
of orders weighs in too. Each kroner of delivery fee costs `PRICE_WEIGHT`, which settles equal
windows at different prices.

In a backtest on the last 40 of 136 orders, the top window given the delivery day overlapped
the one chosen by half or more 72% of the time (51% over the last 106). The weekday alone is a
weak guess (28%), so a run without a day should offer more than one.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from .models import DeliveryDay, DeliverySlot, OrderSummary
from .models._base import Model

HALF_LIFE = 8
"""Orders after which a past slot counts half as much."""
SAME_DAY = 10
"""How much more an order on the slot's weekday counts for its window."""
PRICE_WEIGHT = 0.01
"""Score lost per kroner of delivery fee: 10 kr weighs as much as a 0.1 better fit."""
RECENT = 10
"""Orders the reason counts in."""


class SlotSuggestion(Model):
    id: int
    date: date
    start_hour: int
    end_hour: int
    price: float | None
    score: float
    reason: str
    """E.g. ``like 9 of the last 10 Fri orders, 6 of the last 10``."""


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> float:
    common = min(a[1], b[1]) - max(a[0], b[0])
    either = max(a[1], b[1]) - min(a[0], b[0])
    return max(common, 0) / either if either > 0 else 0.0


def suggest(
    orders: Sequence[OrderSummary], days: Sequence[DeliveryDay], limit: int = 3
) -> list[SlotSuggestion]:
    """The best available slots, best first. Over several days, at most one per day."""
    dated = sorted(
        (
            (o.delivery_start, (o.delivery_start.hour, o.delivery_end.hour))
            for o in orders
            if o.delivery_start is not None and o.delivery_end is not None
        ),
        reverse=True,
    )
    # (decayed weight, weekday, window), newest first
    past = [(0.5 ** (i / HALF_LIFE), start.weekday(), window) for i, (start, window) in enumerate(dated)]
    total = sum(w for w, _, _ in past)
    share = {day: (sum(w for w, wd, _ in past if wd == day) + 1 / 7) / (total + 1) for day in range(7)}

    slots = [s for d in days for s in d.slots if s.is_available]
    several_days = len({s.date for s in slots}) > 1
    top_share = max((share[s.date.weekday()] for s in slots), default=1.0)

    def fit(s: DeliverySlot) -> float:
        weekday, window = s.date.weekday(), (s.start_hour, s.end_hour)
        weights = [(w * (SAME_DAY if wd == weekday else 1), win) for w, wd, win in past]
        votes = sum(w * _overlap(win, window) for w, win in weights)
        return votes / sum(w for w, _ in weights) if weights else 0.0

    def reason(s: DeliverySlot) -> str:
        if not past:
            return "no past orders"
        weekday, window = s.date.weekday(), (s.start_hour, s.end_hour)
        like = [(_overlap(win, window) >= 0.5, wd) for _, wd, win in past]
        same = [hit for hit, wd in like if wd == weekday][:RECENT]
        recent = [hit for hit, _ in like][:RECENT]
        day = f"{s.date:%a}"
        parts = [f"{sum(same)} of the last {len(same)} {day} orders"] if same else [f"no {day} orders"]
        parts.append(f"{sum(recent)} of the last {len(recent)}")
        return "like " + ", ".join(parts)

    scored = []
    for s in slots:
        score = fit(s) * (share[s.date.weekday()] / top_share if several_days else 1.0)
        score -= PRICE_WEIGHT * (s.price or 0.0)
        scored.append((score, s))
    scored.sort(key=lambda x: (-x[0], x[1].date, x[1].start_hour))

    out: list[SlotSuggestion] = []
    seen: set[object] = set()
    for score, s in scored:
        key = s.date if several_days else (s.start_hour, s.end_hour)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            SlotSuggestion(
                id=s.id,
                date=s.date,
                start_hour=s.start_hour,
                end_hour=s.end_hour,
                price=s.price,
                score=round(score, 3),
                reason=reason(s),
            )
        )
        if len(out) == limit:
            break
    return out
