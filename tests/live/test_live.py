"""Tests against the real nemlig.com with the account in .env. Opt in with NEMLIG_LIVE=1.

Reads are harmless. The only writes are reverted: one basket product is added and then set back
to its original quantity, and a temporary shopping list is created and deleted. Never run
clear_basket, reorder or reserve_slot here: they change the real basket or delivery slot.
"""

import os
from pathlib import Path

import pytest

from nemlig import NemligClient, NotLoggedInError

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("NEMLIG_LIVE") != "1", reason="set NEMLIG_LIVE=1 to run"),
]

ROOT = Path(__file__).resolve().parents[2]
TEST_PRODUCT = "5050406"  # Havregryn (finvalsede) øko.


@pytest.fixture(scope="module")
def nc(tmp_path_factory):
    session = tmp_path_factory.mktemp("live") / "session.json"
    with NemligClient.from_env(ROOT / ".env", session_file=session) as client:
        if not client.has_credentials:
            pytest.skip("NEMLIG_USER / NEMLIG_PASS missing")
        client.login()
        yield client


def test_logged_in(nc):
    assert nc.is_logged_in()
    assert nc.get_account().logged_in


def test_search_and_product(nc):
    result = nc.search("havregryn", limit=5)
    assert result.total > 0 and result.products
    details = nc.get_product(result.products[0].id)
    assert details.id == result.products[0].id
    assert nc.suggest("havre").suggestions


def test_reads(nc):
    basket = nc.get_basket()
    assert basket.delivery_context is not None
    assert nc.get_delivery_days(days=2)
    orders = nc.get_orders(limit=2)
    if orders:
        assert nc.get_order(orders[0].id).lines
    assert isinstance(nc.get_favourites(), list)
    assert nc.get_offers(limit=5)


def test_reversible_basket_write(nc):
    before = nc.get_basket().quantity_of(TEST_PRODUCT)
    try:
        assert nc.add_to_basket(TEST_PRODUCT, 2).quantity_of(TEST_PRODUCT) == before + 2
        assert nc.add_to_basket(TEST_PRODUCT, -1).quantity_of(TEST_PRODUCT) == before + 1
        assert nc.set_quantity(TEST_PRODUCT, before + 3).quantity_of(TEST_PRODUCT) == before + 3
    finally:
        nc.set_quantity(TEST_PRODUCT, before)
    assert nc.get_basket().quantity_of(TEST_PRODUCT) == before


def test_temporary_shopping_list(nc):
    created = nc.create_shopping_list("nemlig-python live test")
    try:
        updated = nc.set_shopping_list_item(created.id, TEST_PRODUCT, 2)
        assert [(i.product_id, i.quantity) for i in updated.items] == [(TEST_PRODUCT, 2)]
        assert any(s.id == created.id for s in nc.get_shopping_lists())
    finally:
        nc.delete_shopping_list(created.id)
    assert all(s.id != created.id for s in nc.get_shopping_lists())


def test_anonymous_client_refuses_account_calls(tmp_path):
    with NemligClient(session_file=tmp_path / "none.json") as anon:
        assert anon.search("mælk", limit=1).products
        with pytest.raises(NotLoggedInError):
            anon.get_basket()
