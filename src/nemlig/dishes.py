"""Price a dinner plan: the dish tables `nemlig-dinners` shows at its second checkpoint.

The skill decides the dishes, products and quantities and writes them as a short spec. This
module does the sums: extras per dish, the price per portion and the total for the ★ set,
with multi-buy offers and packs that dishes share. Prices come from `product_cache`, the
products that `search` and `offers` printed, so pricing makes no request.

Spec, one item per line (``#`` starts a comment)::

    portions 3
    anchor 1 5066317:1 nights 1
    1a* Ovnstegt kylling med citron | 60 min | 5014541:2 2301103:1 | Danish, oven
    1b Kylling tikka masala med ris | 35 min | 5060435:1 | Indian, pot; ris at home
    anchor V nights 1 | Vegetarian
    Va* Linsesuppe med brød | 40 min | 5028796:1 | Middle Eastern, pot

A dish belongs to the anchor above it, and ``*`` marks it as part of the suggested set. A
product listed on several dishes is one shared pack, bought once at the largest quantity.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from .models import Product
from .models._base import Model

_ITEM = re.compile(r"(\d+)(?::(\d+))?$")


class SpecError(ValueError):
    """The spec can't be read; the message names the line."""


@dataclass
class Dish:
    code: str
    name: str
    time: str
    items: list[tuple[str, int]]
    note: str
    star: bool = False


@dataclass
class Anchor:
    key: str
    item: tuple[str, int] | None
    nights: int
    title: str | None
    dishes: list[Dish] = field(default_factory=list)


@dataclass
class Plan:
    portions: float
    anchors: list[Anchor]

    def dishes(self) -> list[tuple[Anchor, Dish]]:
        return [(a, d) for a in self.anchors for d in a.dishes]


def _item(spec: str, line: int) -> tuple[str, int]:
    m = _ITEM.match(spec)
    if not m:
        raise SpecError(f"line {line}: expected ID or ID:QTY, got {spec!r}")
    return m[1], int(m[2] or 1)


def parse(text: str) -> Plan:
    portions: float | None = None
    anchors: list[Anchor] = []
    codes: set[str] = set()
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#")[0].strip()
        if not line:
            continue
        head, *rest = line.split()
        if head == "portions":
            try:
                portions = float(rest[0].replace(",", "."))
            except (IndexError, ValueError):
                raise SpecError(f"line {n}: expected 'portions N'") from None
            if portions <= 0:
                raise SpecError(f"line {n}: portions must be more than 0")
        elif head == "anchor":
            words, _, title = line.partition("|")
            parts = words.split()[1:]
            if not parts:
                raise SpecError(f"line {n}: expected 'anchor KEY [ID:QTY] [nights N] [| title]'")
            key, item, nights = parts[0], None, 1
            rest = parts[1:]
            if rest and rest[0] != "nights":
                item = _item(rest.pop(0), n)
            if rest[:1] == ["nights"] and len(rest) == 2 and rest[1].isdigit() and int(rest[1]) > 0:
                nights = int(rest[1])
            elif rest:
                raise SpecError(f"line {n}: expected 'nights N' after the anchor, got {' '.join(rest)!r}")
            if item is None and not title.strip():
                raise SpecError(f"line {n}: an anchor without a product needs a title ('| Vegetarian')")
            anchors.append(Anchor(key=key, item=item, nights=nights, title=title.strip() or None))
        else:
            fields = [f.strip() for f in line.split("|")]
            if len(fields) != 4:
                raise SpecError(f"line {n}: expected 'CODE[*] name | time | ID:QTY ... | note'")
            code, _, name = fields[0].partition(" ")
            star = code.endswith("*")
            code = code.rstrip("*")
            if not anchors:
                raise SpecError(f"line {n}: dish {code} comes before any anchor")
            if code in codes:
                raise SpecError(f"line {n}: dish code {code} is used twice")
            codes.add(code)
            items = [_item(s, n) for s in fields[2].split() if s != "-"]
            dish = Dish(code=code, name=name.strip(), time=fields[1], items=items, note=fields[3], star=star)
            anchors[-1].dishes.append(dish)
    if portions is None:
        raise SpecError("the spec needs a 'portions N' line")
    if not any(a.dishes for a in anchors):
        raise SpecError("the spec has no dishes")
    return Plan(portions=portions, anchors=anchors)


def _ids(plan: Plan) -> set[str]:
    ids = {a.item[0] for a in plan.anchors if a.item}
    return ids | {pid for _, d in plan.dishes() for pid, _ in d.items}


def _check(plan: Plan, products: dict[str, Product]) -> None:
    missing = sorted(pid for pid in _ids(plan) if pid not in products or products[pid].price is None)
    if missing:
        raise SpecError(
            f"no price for {', '.join(missing)}: search for them first (prices from search and offers "
            "keep for 12 hours)"
        )


def _cost(products: dict[str, Product], pid: str, qty: int) -> float:
    cost = products[pid].cost(qty)
    assert cost is not None  # _check made sure there is a price
    return cost


def _anchor_cost(anchor: Anchor, products: dict[str, Product]) -> float:
    return _cost(products, *anchor.item) if anchor.item else 0.0


def _union(dishes: Iterable[Dish]) -> dict[str, int]:
    """Each product once, at the largest quantity any of the dishes needs."""
    out: dict[str, int] = {}
    for d in dishes:
        for pid, qty in d.items:
            out[pid] = max(out.get(pid, 0), qty)
    return out


def _pack(p: Product) -> str:
    size = (p.description or "").split(" / ")[0].strip()
    return "" if not size or size == "1 stk." else size


def _named(p: Product, qty: int) -> str:
    text = " ".join(t for t in (p.name, _pack(p)) if t)
    return f"{qty} x {text}" if qty > 1 else text


def _kr(value: float) -> str:
    return f"{value:.2f} kr"


def _cell(text: str) -> str:
    return text.replace("|", "/")


def _heading(anchor: Anchor, products: dict[str, Product]) -> str:
    pick = "pick 1" if anchor.nights == 1 else f"pick up to {anchor.nights}"
    if not anchor.item:
        return f"**{anchor.key}. {anchor.title}: {pick}**"
    pid, qty = anchor.item
    p = products[pid]
    price = _kr(_anchor_cost(anchor, products))
    if p.discount:
        price += f" (-{p.discount}%)"
    deal = p.deal()
    if deal and deal[0] > 1:
        price += f", offer {p.offer}"
    title = anchor.title or _named(p, qty)
    return f"**{anchor.key}. {_cell(title)}, {price}: {pick}**"


class DishCost(Model):
    code: str
    name: str
    cost: float
    """The dish's share of its anchor plus its extras."""
    items: list[str]
    """``ID:QTY`` of its extras."""


def dish_cost(plan: Plan, anchor: Anchor, dish: Dish, products: dict[str, Product]) -> DishCost:
    extras = sum(_cost(products, pid, qty) for pid, qty in dish.items)
    return DishCost(
        code=dish.code,
        name=dish.name,
        cost=round(_anchor_cost(anchor, products) / anchor.nights + extras, 2),
        items=[f"{pid}:{qty}" for pid, qty in dish.items],
    )


class Priced(Model):
    """The checkpoint tables, and the totals for the ★ set."""

    tables: str
    star_codes: list[str]
    star_total: float
    star_anchors: float
    star_extras: float
    shared: list[str] = []
    warnings: list[str] = []


def render(plan: Plan, products: dict[str, Product]) -> Priced:
    _check(plan, products)
    blocks = []
    for anchor in plan.anchors:
        if not anchor.dishes:
            continue
        share = _anchor_cost(anchor, products) / anchor.nights
        rows = [
            _heading(anchor, products),
            "| # | Dish | Time | Extras to buy | Extras | Per portion | Note |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for d in anchor.dishes:
            extras = sum(_cost(products, pid, qty) for pid, qty in d.items)
            names = ", ".join(_named(products[pid], qty) for pid, qty in d.items) or "-"
            cells = [
                f"{d.code} ★" if d.star else d.code,
                d.name,
                d.time,
                names,
                f"{extras:.0f} kr",
                f"{(share + extras) / plan.portions:.0f} kr",
                d.note,
            ]
            rows.append("| " + " | ".join(_cell(c) for c in cells) + " |")
        blocks.append("\n".join(rows))

    starred = [(a, d) for a, d in plan.dishes() if d.star]
    anchors = {id(a): a for a, _ in starred}
    union = _union(d for _, d in starred)
    star_anchors = sum(_anchor_cost(a, products) for a in anchors.values())
    star_extras = sum(_cost(products, pid, qty) for pid, qty in union.items())
    shared = []
    for pid in union:
        users = [d.code for _, d in starred if any(i == pid for i, _ in d.items)]
        if len(users) > 1:
            shared.append(f"{products[pid].name} ({', '.join(users)})")
    warnings = [
        f"{n} ★ dishes on anchor {a.key}, which covers {a.nights} night{'s' if a.nights > 1 else ''}"
        for a in anchors.values()
        if (n := sum(d.star for d in a.dishes)) > a.nights
    ]
    return Priced(
        tables="\n\n".join(blocks),
        star_codes=[d.code for _, d in starred],
        star_total=round(star_anchors + star_extras, 2),
        star_anchors=round(star_anchors, 2),
        star_extras=round(star_extras, 2),
        shared=shared,
        warnings=warnings,
    )


def picks(
    plan: Plan, codes: Sequence[str], products: dict[str, Product]
) -> tuple[list[tuple[str, int]], list[DishCost]]:
    """What to add for the picked dishes: their anchors and extras, each product once."""
    _check(plan, products)
    by_code = {d.code.lower(): (a, d) for a, d in plan.dishes()}
    unknown = [c for c in codes if c.lower() not in by_code]
    if unknown:
        raise SpecError(f"no dish {', '.join(unknown)} in the plan (dishes: {', '.join(by_code)})")
    chosen = [by_code[c.lower()] for c in codes]
    items: dict[str, int] = {}
    for a in {id(a): a for a, _ in chosen}.values():
        if a.item:
            items[a.item[0]] = max(items.get(a.item[0], 0), a.item[1])
    for pid, qty in _union(d for _, d in chosen).items():
        items[pid] = max(items.get(pid, 0), qty)
    return list(items.items()), [dish_cost(plan, a, d, products) for a, d in chosen]


def text(priced: Priced) -> str:
    lines = [priced.tables, ""]
    if priced.star_codes:
        lines.append(
            f"★ set ({', '.join(priced.star_codes)}): {_kr(priced.star_total)} "
            f"(anchors {_kr(priced.star_anchors)} + extras {_kr(priced.star_extras)})"
        )
    if priced.shared:
        lines.append("shared in the ★ set, bought once: " + "; ".join(priced.shared))
    lines += [f"warning: {w}" for w in priced.warnings]
    return "\n".join(lines).rstrip()
