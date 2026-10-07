from datetime import date, datetime, timedelta

from nemlig import slots
from nemlig.models import DeliveryDay, DeliverySlot, OrderSummary

FRI = date(2026, 10, 9)
SUN = date(2026, 10, 11)


def order(day: date, start: int, end: int, n: int = 0) -> OrderSummary:
    when = datetime.combine(day, datetime.min.time())
    return OrderSummary(
        id=n,
        status=3,
        total=500.0,
        delivery_start=when.replace(hour=start),
        delivery_end=when.replace(hour=end),
    )


def slot(day: date, start: int, end: int, price: float, n: int) -> DeliverySlot:
    return DeliverySlot(
        id=n, date=day, start_hour=start, end_hour=end, price=price, deadline=None, availability=0
    )


def history() -> list[OrderSummary]:
    """Ten weeks of Friday afternoons and Sunday mornings, alternating."""
    out = []
    for week in range(10):
        out.append(order(FRI - timedelta(weeks=week + 1), 16, 19, n=2 * week))
        out.append(order(SUN - timedelta(weeks=week + 1), 7, 10, n=2 * week + 1))
    return out


def test_the_window_follows_the_day():
    days = [
        DeliveryDay(date=day, slots=[slot(day, 7, 10, 33.0, 1 + k), slot(day, 16, 19, 26.0, 3 + k)])
        for k, day in ((0, FRI), (10, SUN))
    ]
    fri = slots.suggest(history(), days[:1])
    assert [(s.start_hour, s.end_hour) for s in fri] == [(16, 19), (7, 10)]
    assert fri[0].reason == "like 10 of the last 10 Fri orders, 5 of the last 10"
    sun = slots.suggest(history(), days[1:])
    assert (sun[0].start_hour, sun[0].end_hour) == (7, 10)


def test_a_recent_switch_and_the_fee_beat_an_old_habit():
    day = DeliveryDay(date=FRI, slots=[slot(FRI, 16, 19, 26.0, 1), slot(FRI, 16, 21, 19.0, 2)])
    assert slots.suggest(history(), [day])[0].id == 1
    # The last three Fridays went to the cheaper, wider window.
    wide = [order(FRI - timedelta(weeks=w), 16, 21, n=90 + w) for w in (1, 2, 3)]
    orders = [o for o in history() if o.delivery_start.date() not in {w.delivery_start.date() for w in wide}]
    assert slots.suggest(orders + wide, [day])[0].id == 2


def test_several_days_give_one_slot_per_day():
    days = [
        DeliveryDay(date=d, slots=[slot(d, 16, 19, 26.0, 10 + i), slot(d, 16, 21, 26.0, 20 + i)])
        for i, d in enumerate(FRI + timedelta(days=k) for k in range(3))
    ]
    got = slots.suggest(history(), days)
    assert len({s.date for s in got}) == 3
    assert got[0].date == FRI  # Friday is the household's day for the afternoon


def test_unavailable_slots_and_no_history():
    day = DeliveryDay(
        date=FRI,
        slots=[slot(FRI, 16, 19, 26.0, 1).model_copy(update={"availability": 2}), slot(FRI, 7, 10, 33.0, 2)],
    )
    got = slots.suggest([], [day])
    assert [s.id for s in got] == [2]
    assert got[0].reason == "no past orders"
