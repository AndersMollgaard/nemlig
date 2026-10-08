from datetime import datetime

import httpx
import pytest
from conftest import WWW, fixture

from nemlig import ApiError, OrderCache
from nemlig.models import OrderSummary
from nemlig.order_cache import FORMAT, is_finished

NOW = datetime(2026, 10, 1, 12, 0)


def summary(order_id, end, status=3, editable=False):
    return {
        "Id": order_id,
        "Status": status,
        "IsEditable": editable,
        "DeliveryTime": {"Start": end.replace("T21", "T16"), "End": end},
    }


HISTORY = {
    "Orders": [
        summary(3, "2026-10-01T21:00:00"),  # today, not delivered yet
        summary(2, "2026-09-21T21:00:00"),
        summary(1, "2026-09-11T21:00:00"),
    ],
    "NumberOfPages": 1,
}


def routes(api):
    api.get(f"{WWW}/webapi/order/GetBasicOrderHistory").respond(json=HISTORY)
    lines = fixture("order_lines.json")
    return {
        i: api.get(f"{WWW}/webapi/v2/order/GetOrderHistory/{i}").respond(
            json={**lines, "Id": i, "DeliveryTime": HISTORY["Orders"][3 - i]["DeliveryTime"]}
        )
        for i in (1, 2, 3)
    }


def test_is_finished():
    def order(**kw):
        return OrderSummary.from_api(summary(1, "2026-09-30T21:00:00", **kw))

    assert is_finished(order(), NOW)
    assert not is_finished(OrderSummary.from_api(summary(1, "2026-10-01T21:00:00")), NOW)
    assert not is_finished(order(editable=True), NOW)
    assert not is_finished(order(status=1), NOW)


def test_sync_caches_finished_orders_once(api, customer, tmp_path):
    fetched = routes(api)
    cache = OrderCache(tmp_path)
    result = cache.sync(customer, now=NOW)
    assert (result.orders, result.cached, result.fetched, result.pending) == (3, 2, 2, 1)
    assert (str(result.first), str(result.last)) == ("2026-09-11", "2026-09-21")
    assert result.upcoming_ids == [3]
    assert "upcoming_ids" not in result.model_dump()
    assert not fetched[3].called

    again = cache.sync(customer, now=NOW)
    assert (again.cached, again.fetched) == (2, 0)
    assert fetched[1].call_count == fetched[2].call_count == 1

    account = customer.account_key()
    assert result.path == str(tmp_path / account)
    orders = cache.load(account)
    assert [o.id for o in orders] == [2, 1]
    assert orders[0].lines[0].product_id == "5027015"


def test_sync_keeps_what_it_fetched_before_a_failure(api, customer, tmp_path, monkeypatch):
    monkeypatch.setattr("nemlig.order_cache.SYNC_BATCH", 1)
    fetched = routes(api)
    fetched[1].mock(return_value=httpx.Response(500))
    cache = OrderCache(tmp_path)
    with pytest.raises(ApiError):
        cache.sync(customer, now=NOW)
    assert cache.ids(customer.account_key()) == {2}


def test_sync_refetches_an_older_format(api, customer, tmp_path):
    fetched = routes(api)
    cache = OrderCache(tmp_path)
    cache.sync(customer, now=NOW)
    account = customer.account_key()
    assert (tmp_path / account / "format").read_text(encoding="utf-8") == str(FORMAT)

    (tmp_path / account / "format").write_text("1", encoding="utf-8")
    assert not cache.is_current(account)
    again = cache.sync(customer, now=NOW)
    assert (again.fetched, again.cached) == (2, 2)
    assert fetched[1].call_count == 2
    assert cache.is_current(account)
    assert cache.load(account)[0].lines[0].category == "Drikke"
