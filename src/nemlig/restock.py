"""Which of the household's usual products are due, predicted from its own order history.

Each group of products (see `groups`) gets two features at the delivery date:

- **how regular it is:** its purchase rate per order, decayed so recent orders count most
  (half-life `HALF_LIFE` orders), and
- **how due it is:** the days since it was last bought, divided by its usual gap (the median
  of the last `GAPS` gaps; unknown below 3 purchases).

The probability that it is bought in the coming order is the share of times this household
bought a group in the same rate and due-ness cell before. The table is learned from every past
order, and each cell is smoothed toward its rate bin and that toward the overall share, so a
sparse cell borrows from the pool. That is the hierarchical part, done as empirical Bayes. On
135 real orders, timing helped for the weekly items. It hardly helped for slow movers like
toilet paper, whose gaps vary widely, so their probabilities stay low and honest.

`backtest` replays the history: it predicts each of the last orders from the ones before it,
with no look-ahead, and compares the model with the Phase 3 stopgap.
"""

from __future__ import annotations

import bisect
from collections import Counter
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from statistics import median, median_low

from .groups import Groups
from .models import BasketLine, Order, OrderLine, Product
from .models._base import Model, fold
from .preferences import Preferences

HALF_LIFE = 8
"""Orders after which a purchase counts half as much in the purchase rate."""
GAPS = 6
"""Gaps (in days) behind a group's usual gap."""
STALE_DAYS = 365
"""Groups not bought for this long are left out."""
SMOOTHING = 5.0
"""Weight of the pooled share in a cell, in purchases."""
RATE_EDGES = (0.02, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)
RATIO_EDGES = (0.5, 0.8, 1.2, 2.0, 4.0)

DUE = 0.55
"""Added without asking. On the last 40 real orders: about 8 a time, 70% of them bought."""
MAYBE = 0.3
"""Offered for the user to pick, the likeliest `MAX_MAYBE` of them. About 4 in 10 were bought."""
MAX_MAYBE = 12
OFFER_FLOOR = 0.1
"""A group this likely joins the maybes when it is on offer at `OFFER_DISCOUNT` percent."""
OFFER_DISCOUNT = 20
MAX_OFFERS = 3
OFFER_MIN_BUYS = 3
"""Orders in the last year a group must have been in to be offered, so a steak bought once or
twice a year isn't suggested as a stock-up."""


# -- the model --------------------------------------------------------------------------------


@dataclass
class _Group:
    rate: float = 0.0
    dates: list[date] = field(default_factory=list)
    quantities: list[int] = field(default_factory=list)
    lines: dict[str, OrderLine] = field(default_factory=dict)
    """The latest line per product, oldest first."""
    categories: Counter[str] = field(default_factory=Counter)

    @property
    def category(self) -> str | None:
        return self.categories.most_common(1)[0][0] if self.categories else None

    def usual_gap(self) -> float | None:
        if len(self.dates) < 3:
            return None
        recent = self.dates[-GAPS - 1 :]
        return max(median((b - a).days for a, b in zip(recent, recent[1:], strict=False)), 1)

    def cell(self, when: date) -> tuple[int, int]:
        gap = self.usual_gap()
        ratio = -1 if gap is None else bisect.bisect_right(RATIO_EDGES, (when - self.dates[-1]).days / gap)
        return bisect.bisect_right(RATE_EDGES, self.rate), ratio


@dataclass
class _Share:
    bought: int = 0
    seen: int = 0

    def smoothed(self, prior: float) -> float:
        return (self.bought + SMOOTHING * prior) / (self.seen + SMOOTHING)


@dataclass
class _Table:
    overall: _Share = field(default_factory=_Share)
    rates: dict[int, _Share] = field(default_factory=dict)
    cells: dict[tuple[int, int], _Share] = field(default_factory=dict)

    def add(self, cell: tuple[int, int], bought: bool) -> None:
        for share in (
            self.overall,
            self.rates.setdefault(cell[0], _Share()),
            self.cells.setdefault(cell, _Share()),
        ):
            share.bought += bought
            share.seen += 1

    def p(self, cell: tuple[int, int]) -> float:
        overall = (self.overall.bought + 1) / (self.overall.seen + 2)
        by_rate = self.rates.get(cell[0], _Share()).smoothed(overall)
        return self.cells.get(cell, _Share()).smoothed(by_rate)


class _History:
    """Walks the orders oldest first, learning the table as it goes."""

    def __init__(self) -> None:
        self.groups: dict[str, _Group] = {}
        self.table = _Table()
        self.decay = 0.5 ** (1 / HALF_LIFE)

    def live(self, when: date) -> dict[str, _Group]:
        return {k: g for k, g in self.groups.items() if (when - g.dates[-1]).days <= STALE_DAYS}

    def add(self, when: date, basket: dict[str, list[OrderLine]]) -> None:
        for key, group in self.live(when).items():
            self.table.add(group.cell(when), key in basket)
        for group in self.groups.values():
            group.rate *= self.decay
        for key, lines in basket.items():
            group = self.groups.setdefault(key, _Group())
            group.rate += 1 - self.decay
            group.dates.append(when)
            group.quantities.append(sum(line.quantity for line in lines))
            for line in lines:
                group.lines.pop(line.product_id, None)
                group.lines[line.product_id] = line
                if line.category:
                    group.categories[line.category] += 1


def _baskets(orders: Iterable[Order], groups: Groups) -> list[tuple[date, dict[str, list[OrderLine]]]]:
    """Each order's lines by group, oldest order first. A product is grouped by its latest name,
    since nemlig renames some ("Letmælk" became "Letmælk 1,5%"). Sold-out lines were not
    delivered."""
    ordered = sorted((o for o in orders if o.delivery_start), key=lambda o: (o.delivery_start, o.id))
    names = {line.product_id: line.name for order in ordered for line in order.lines}
    out = []
    for order in ordered:
        basket: dict[str, list[OrderLine]] = {}
        for line in order.lines:
            if line.quantity > 0 and not line.sold_out:
                basket.setdefault(groups.key(line.product_id, names[line.product_id]), []).append(line)
        assert order.delivery_start is not None
        out.append((order.delivery_start.date(), basket))
    return out


@dataclass(frozen=True)
class Due:
    group: str
    p: float
    category: str | None
    last: date
    every: int | None
    """The usual gap in days."""
    buys: int
    """Orders in the last `STALE_DAYS` that had it."""
    quantity: int
    """Bought per order, the median of the last three times."""
    lines: list[OrderLine]
    """The latest line per product, newest first."""


def predict(orders: Iterable[Order], groups: Groups, when: date) -> list[Due]:
    """Every group bought in the last year, with the probability that it is bought for ``when``,
    most likely first. Orders delivered after ``when`` are left out."""
    history = _History()
    for day, basket in _baskets(orders, groups):
        if day <= when:
            history.add(day, basket)
    out = []
    for key, g in history.live(when).items():
        gap = g.usual_gap()
        out.append(
            Due(
                group=key,
                p=history.table.p(g.cell(when)),
                category=g.category,
                last=g.dates[-1],
                every=None if gap is None else round(gap),
                buys=sum((when - d).days <= STALE_DAYS for d in g.dates),
                quantity=max(median_low(g.quantities[-3:]), 1),
                lines=list(reversed(g.lines.values())),
            )
        )
    return sorted(out, key=lambda d: (-d.p, d.group))


# -- what to propose --------------------------------------------------------------------------


class RestockItem(Model):
    product_id: str
    name: str
    description: str | None = None
    quantity: int
    p: float
    """The probability that the group is bought in this order."""
    last: date
    every: int | None = None
    """The usual gap between purchases, in days."""
    offer: str | None = None
    """``-30%`` or ``2 for 70 kr, -20%`` when the product is on offer for the slot."""


class Restock(Model):
    date: date
    slot: str | None = None
    due: list[RestockItem]
    """Likely enough to add without asking."""
    maybe: list[RestockItem]
    """For the user to pick from."""
    in_basket: int = 0
    """Due or maybe groups left out because one of their products is in the basket."""
    to_review: int = 0
    """Products that `restock groups` should show."""


def _brand(line: OrderLine) -> str | None:
    """Order lines carry no brand. It is usually the last part of the description."""
    return (line.description or "").rpartition(" / ")[2].strip() or None


def _offer_text(p: Product) -> str | None:
    deal = p.offer if p.offer and " for " in p.offer else None
    parts = [t for t in (deal, f"-{p.discount}%" if p.discount else None) if t]
    return ", ".join(parts) or None


def _item(due: Due, line: OrderLine | Product, offer: Product | None) -> RestockItem:
    return RestockItem(
        product_id=line.product_id if isinstance(line, OrderLine) else line.id,
        name=line.name,
        description=line.description,
        quantity=due.quantity,
        p=round(due.p, 2),
        last=due.last,
        every=due.every,
        offer=_offer_text(offer) if offer else None,
    )


def propose(
    due: Sequence[Due],
    groups: Groups,
    *,
    when: date,
    slot: str | None = None,
    basket: Sequence[BasketLine] = (),
    prefs: Preferences | None = None,
    offers: Sequence[Product] = (),
    exclude: Collection[str] = (),
) -> Restock:
    """Split the predictions into due and maybe, leaving out groups in the basket, categories in
    ``exclude`` (``"kød & fisk"`` or ``"koed-&-fisk"``) and products an avoid rule matches.

    The suggested product is the group's latest one that no avoid rule matches. The maybes are
    the likeliest `MAX_MAYBE`. A group below them but at least `OFFER_FLOOR` likely, and bought
    in `OFFER_MIN_BUYS` orders in the last year, joins them when a product of it is on offer at
    `OFFER_DISCOUNT` percent or more, unless a keep rule holds its latest product; at most
    `MAX_OFFERS` do.
    """
    prefs = prefs or Preferences()
    excluded = {fold(c) for c in exclude}
    known = {line.product_id: d.group for d in due for line in d.lines}

    def group_of(product_id: str, name: str) -> str:
        return known.get(product_id) or groups.key(product_id, name)

    in_basket = {group_of(line.product_id, line.name) for line in basket if line.quantity > 0}
    on_offer: dict[str, Product] = {}
    for p in offers:
        if p.available and p.discount and not prefs.avoided(p.id, p.name, p.brand):
            key = group_of(p.id, p.name)
            if key not in on_offer or p.discount > (on_offer[key].discount or 0):
                on_offer[key] = p

    result: dict[str, list[RestockItem]] = {"due": [], "maybe": []}
    promoted = skipped = 0
    for d in due:
        if d.p < OFFER_FLOOR:
            break
        if d.category and fold(d.category) in excluded:
            continue
        line = next((x for x in d.lines if not prefs.avoided(x.product_id, x.name, _brand(x))), None)
        if line is None:
            continue
        if d.group in in_basket:
            skipped += d.p >= MAYBE
            continue
        offer = on_offer.get(d.group)
        tier = "due" if d.p >= DUE else "maybe" if d.p >= MAYBE and len(result["maybe"]) < MAX_MAYBE else None
        if tier:
            same = offer if offer and offer.id == line.product_id else None
            result[tier].append(_item(d, line, same))
        elif (
            offer
            and (offer.discount or 0) >= OFFER_DISCOUNT
            and d.buys >= OFFER_MIN_BUYS
            and promoted < MAX_OFFERS
            and (offer.id == line.product_id or not prefs.kept_by(line.product_id, line.name, _brand(line)))
        ):
            promoted += 1
            result["maybe"].append(_item(d, line if offer.id == line.product_id else offer, offer))
    return Restock(date=when, slot=slot, due=result["due"], maybe=result["maybe"], in_basket=skipped)


# -- grouping review --------------------------------------------------------------------------


class ReviewGroup(Model):
    key: str
    """The group: a named one, or the auto key of its name."""
    category: str | None = None
    bought: int
    """Orders it was bought in."""
    ids: list[str]
    """Its products that are not reviewed yet."""


class GroupReview(Model):
    named: dict[str, list[str]] = {}
    """The named groups and their members."""
    groups: list[ReviewGroup]


def review(orders: Iterable[Order], groups: Groups) -> GroupReview:
    """Products not reviewed yet that could become due: bought in the last `STALE_DAYS` before
    the latest order, in a group bought in at least two orders. Most bought first."""
    history = _History()
    last_seen: dict[str, date] = {}
    for day, basket in _baskets(orders, groups):
        history.add(day, basket)
        for lines in basket.values():
            for line in lines:
                last_seen[line.product_id] = day
    latest = max(last_seen.values(), default=date.min)
    reviewed = set(groups.reviewed)
    out = []
    for key, g in history.groups.items():
        ids = [
            pid
            for pid in reversed(g.lines)
            if pid not in reviewed and (latest - last_seen[pid]).days <= STALE_DAYS
        ]
        if ids and len(g.dates) >= 2:
            out.append(ReviewGroup(key=key, category=g.category, bought=len(g.dates), ids=ids))
    return GroupReview(named=groups.groups, groups=sorted(out, key=lambda r: (-r.bought, r.key)))


# -- backtest ---------------------------------------------------------------------------------


class Score(Model):
    method: str
    items: float
    """Suggested per order, on average."""
    precision: float
    recall: float


class Calibration(Model):
    predicted: str
    """A range of probabilities, e.g. ``0.6-0.7``."""
    bought: float
    """The share of those that were bought."""
    n: int


class Backtest(Model):
    orders: int
    """Orders predicted, each from the orders before it."""
    repeat: float
    """The share of their groups bought before, so the best recall possible."""
    scores: list[Score]
    calibration: list[Calibration]


def backtest(
    orders: Iterable[Order], groups: Groups, *, last: int = 30, exclude: Collection[str] = ()
) -> Backtest:
    """Predict each of the ``last`` orders from the ones before it and score the tiers against
    what was bought. "rate, same size" ranks by the purchase rate alone and takes as many as due
    and maybe together, to show what the due-ness adds. "stopgap" is Phase 3's rule: bought in
    2 of the last 3 orders."""
    excluded = {fold(c) for c in exclude}
    baskets = _baskets(orders, groups)
    history = _History()
    start = max(len(baskets) - last, 1)
    tally: dict[str, list[int]] = {}
    calibration: dict[int, list[float]] = {}
    repeat = actual_total = 0

    def score(method: str, chosen: set[str], actual: set[str]) -> None:
        t = tally.setdefault(method, [0, 0, 0])
        t[0] += len(chosen & actual)
        t[1] += len(chosen)
        t[2] += len(actual)

    def kept(category: str | None) -> bool:
        return not (category and fold(category) in excluded)

    for i, (day, basket) in enumerate(baskets):
        if i >= start:
            live = {k: g for k, g in history.live(day).items() if kept(g.category)}
            actual = {k for k, lines in basket.items() if kept(lines[0].category)}
            repeat += len(actual & live.keys())
            actual_total += len(actual)
            p = {k: history.table.p(g.cell(day)) for k, g in live.items()}
            due = {k for k, v in p.items() if v >= DUE}
            maybe = due | set(
                sorted((k for k, v in p.items() if MAYBE <= v < DUE), key=lambda k: -p[k])[:MAX_MAYBE]
            )
            score("due", due, actual)
            score("due + maybe", maybe, actual)
            by_rate = sorted(live, key=lambda k: -live[k].rate)[: len(maybe)]
            score("rate, same size", set(by_rate), actual)
            recent = [set(b) for _, b in baskets[max(i - 3, 0) : i]]
            score("stopgap", {k for k in live if sum(k in b for b in recent) >= 2}, actual)
            for k, v in p.items():
                c = calibration.setdefault(min(int(v * 10), 9), [0, 0])
                c[0] += k in actual
                c[1] += 1
        history.add(day, basket)

    n = max(len(baskets) - start, 0)
    return Backtest(
        orders=n,
        repeat=round(repeat / actual_total, 2) if actual_total else 0.0,
        scores=[
            Score(
                method=m,
                items=round(chosen / n, 1) if n else 0.0,
                precision=round(hit / chosen, 2) if chosen else 0.0,
                recall=round(hit / total, 2) if total else 0.0,
            )
            for m, (hit, chosen, total) in tally.items()
        ],
        calibration=[
            Calibration(
                predicted=f"{b / 10:.1f}-{(b + 1) / 10:.1f}", bought=round(c[0] / c[1], 2), n=int(c[1])
            )
            for b, c in sorted(calibration.items())
        ],
    )
