from datetime import date, datetime, timedelta

import pytest

from nemlig import restock
from nemlig.groups import Groups
from nemlig.models import BasketLine, Order, OrderLine, Product
from nemlig.preferences import Preferences, Rule

START = date(2026, 1, 5)


def line(pid, name, qty=1, category="Kolonial", description=None, sold_out=False):
    return OrderLine(
        product_id=pid,
        name=name,
        description=description,
        quantity=qty,
        item_price=None,
        amount=None,
        category=category,
        sold_out=sold_out,
    )


def order(i, day, lines):
    return Order(
        id=i, status=3, total=None, delivery_start=datetime.combine(day, datetime.min.time()), lines=lines
    )


def weekly(weeks=30, extra=lambda week: []):
    """Milk every week, toilet paper every third, chicken every week, and a one-off."""
    orders = []
    for w in range(weeks):
        lines = [line("1", "Letmælk 1,5%", 2, "Køl"), line("3", "Kyllingebryst", 1, "Kød & fisk")]
        if w % 3 == 0:
            lines.append(line("2", "Toiletpapir", 1, "Husholdning", "8 rl. / Lambi"))
        if w == 5:
            lines.append(line("4", "Kaviar"))
        orders.append(order(w, START + timedelta(weeks=w), lines + extra(w)))
    return orders


NEXT = START + timedelta(weeks=30)


def by_group(due):
    return {d.group: d for d in due}


def test_predict_weekly_item_is_due_and_slow_item_less_so():
    due = by_group(restock.predict(weekly(), Groups(), NEXT))
    milk = due["letmælk 1,5%"]
    assert milk.p >= restock.DUE
    assert (milk.quantity, milk.every, milk.last, milk.category) == (2, 7, NEXT - timedelta(weeks=1), "Køl")
    assert due["toiletpapir"].p < milk.p
    assert due["kaviar"].p < restock.MAYBE
    assert [x.product_id for x in milk.lines] == ["1"]


def test_predict_just_bought_is_less_due():
    orders = weekly()
    soon = by_group(restock.predict(orders, Groups(), NEXT - timedelta(days=6)))
    later = by_group(restock.predict(orders, Groups(), NEXT))
    assert soon["letmælk 1,5%"].p < later["letmælk 1,5%"].p


def test_predict_ignores_orders_after_the_date_and_counts_upcoming_ones():
    orders = weekly()
    upcoming = order(99, NEXT - timedelta(days=2), [line("2", "Toiletpapir", 1, "Husholdning")])
    due = by_group(restock.predict([*orders, upcoming], Groups(), NEXT))
    assert due["toiletpapir"].last == NEXT - timedelta(days=2)
    due = by_group(restock.predict([*orders, upcoming], Groups(), NEXT - timedelta(days=3)))
    assert due["toiletpapir"].last < NEXT - timedelta(days=3)


def test_predict_groups_by_latest_name_and_skips_sold_out_lines():
    def extra(week):
        return [line("5", "Pærer" if week < 20 else "Pærer Conference", sold_out=week == 29)]

    due = by_group(restock.predict(weekly(extra=extra), Groups(), NEXT))
    assert "pærer" not in due
    assert due["pærer conference"].last == NEXT - timedelta(weeks=2)


def test_predict_uses_named_groups():
    def extra(week):
        return [line("6", "Frilandsæg") if week % 2 else line("7", "Skrabeæg")]

    groups = Groups()
    groups.merge("æg", ["frilandsæg", "skrabeæg"])
    due = by_group(restock.predict(weekly(extra=extra), groups, NEXT))
    assert "æg" in due and "frilandsæg" not in due
    assert [x.product_id for x in due["æg"].lines] == ["6", "7"]


def test_propose_excludes_categories_and_the_basket():
    due = restock.predict(weekly(), Groups(), NEXT)
    basket = [BasketLine(product_id="1", name="Letmælk 1,5%", quantity=1, item_price=None, total=None)]
    result = restock.propose(due, Groups(), when=NEXT, basket=basket, exclude=["kød & fisk"])
    ids = [i.product_id for i in result.due + result.maybe]
    assert "3" not in ids and "1" not in ids
    assert result.in_basket == 1
    plain = restock.propose(due, Groups(), when=NEXT, slot="man. 03/08 kl. 17-18")
    assert {"1", "3"} <= {i.product_id for i in plain.due}
    assert {i.product_id: i.quantity for i in plain.due}["1"] == 2 and plain.slot == "man. 03/08 kl. 17-18"


def test_propose_falls_back_to_an_older_product_past_an_avoid_rule(monkeypatch):
    monkeypatch.setattr(restock, "MAYBE", 0.0)
    monkeypatch.setattr(restock, "OFFER_FLOOR", 0.0)

    def extra(week):
        return [line("8", "Toiletpapir", 1, "Husholdning", "8 rl. / First Price")] if week == 29 else []

    due = restock.predict(weekly(extra=extra), Groups(), NEXT)
    prefs = Preferences(avoid=[Rule(brand="First Price", name="toiletpapir")])
    with_rule = restock.propose(due, Groups(), when=NEXT, prefs=prefs)
    without = restock.propose(due, Groups(), when=NEXT)
    pick = {i.name: i.product_id for i in with_rule.due + with_rule.maybe}
    assert pick["Toiletpapir"] == "2"
    assert {i.name: i.product_id for i in without.due + without.maybe}["Toiletpapir"] == "8"


def offer(pid, name, discount, brand=None):
    return Product(id=pid, name=name, brand=brand, discount=discount, offer="2 for 70 kr", on_offer=True)


def test_propose_promotes_an_unlikely_group_on_offer(monkeypatch):
    once = restock.predict(weekly(), Groups(), NEXT)
    assert by_group(once)["kaviar"].buys == 1
    monkeypatch.setattr(restock, "OFFER_FLOOR", 0.0)
    rare = restock.propose(once, Groups(), when=NEXT, offers=[offer("4", "Kaviar", 30)])
    assert "4" not in [i.product_id for i in rare.maybe]

    orders = weekly(extra=lambda week: [line("4", "Kaviar")] if week in (12, 19) else [])
    due = restock.predict(orders, Groups(), NEXT)
    kaviar = by_group(due)["kaviar"]
    assert kaviar.buys == restock.OFFER_MIN_BUYS and kaviar.p < restock.MAYBE
    monkeypatch.setattr(restock, "OFFER_FLOOR", kaviar.p - 0.001)

    result = restock.propose(due, Groups(), when=NEXT, offers=[offer("4", "Kaviar", 30)])
    assert result.maybe[-1].product_id == "4"
    assert result.maybe[-1].offer == "2 for 70 kr, -30%"

    weak = restock.propose(due, Groups(), when=NEXT, offers=[offer("4", "Kaviar", 10)])
    assert "4" not in [i.product_id for i in weak.maybe]

    other = restock.propose(due, Groups(), when=NEXT, offers=[offer("9", "Kaviar", 30)])
    assert other.maybe[-1].product_id == "9"
    kept = restock.propose(
        due,
        Groups(),
        when=NEXT,
        offers=[offer("9", "Kaviar", 30)],
        prefs=Preferences(keep=[Rule(id="4")]),
    )
    assert "9" not in [i.product_id for i in kept.maybe]


def test_propose_caps_the_maybes(monkeypatch):
    due = restock.predict(weekly(), Groups(), NEXT)
    monkeypatch.setattr(restock, "DUE", 1.0)
    monkeypatch.setattr(restock, "MAYBE", 0.0)
    monkeypatch.setattr(restock, "OFFER_FLOOR", 0.0)
    monkeypatch.setattr(restock, "MAX_MAYBE", 2)
    result = restock.propose(due, Groups(), when=NEXT)
    assert (len(result.due), len(result.maybe)) == (0, 2)


def test_review_lists_new_products_in_repeat_groups():
    def extra(week):
        return [line("10", "Solsikkerugbrød"), line("11", "Solsikkerugbrød")] if week in (28, 29) else []

    orders = weekly(extra=extra)
    review = restock.review(orders, Groups(reviewed=["2"]))
    keys = {r.key: r for r in review.groups}
    assert "kaviar" not in keys  # bought once
    assert "toiletpapir" not in keys  # reviewed
    assert keys["solsikkerugbrød"].ids == ["11", "10"] and keys["solsikkerugbrød"].bought == 2
    assert review.groups[0].key in ("letmælk 1,5%", "kyllingebryst")


def test_review_leaves_out_products_not_bought_for_a_year():
    old = [order(i, START + timedelta(weeks=i), [line("12", "Gammel")]) for i in range(3)]
    later = order(9, START + timedelta(days=400), [line("1", "Letmælk 1,5%")])
    later2 = order(10, START + timedelta(days=407), [line("1", "Letmælk 1,5%")])
    keys = {r.key for r in restock.review([*old, later, later2], Groups()).groups}
    assert keys == {"letmælk 1,5%"}


def test_backtest_beats_the_stopgap_on_a_regular_household():
    result = restock.backtest(weekly(40), Groups(), last=10, exclude=["kød & fisk"])
    scores = {s.method: s for s in result.scores}
    assert result.orders == 10
    assert set(scores) == {"due", "due + maybe", "rate, same size", "stopgap"}
    assert scores["due"].precision == pytest.approx(1.0)
    assert scores["due + maybe"].recall >= scores["stopgap"].recall
    assert result.repeat == 1.0
    assert result.calibration and all(0 <= c.bought <= 1 for c in result.calibration)
