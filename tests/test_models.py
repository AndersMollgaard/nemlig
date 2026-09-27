import json
from datetime import date

import pytest
from conftest import fixture

from nemlig.models import (
    Account,
    Basket,
    DeliveryDay,
    Order,
    OrderSummary,
    Product,
    ProductDetails,
    SearchResult,
    ShoppingList,
    ShoppingListSummary,
    SlotAvailability,
    Suggestions,
)


def test_search_result():
    result = SearchResult.from_api(fixture("search.json"), "havregryn")
    assert result.query == "havregryn"
    assert result.total == 14
    p = result.products[0]
    assert (p.id, p.name, p.brand, p.price) == ("5050406", "Havregryn (finvalsede) øko.", "Go' Morgen", 9.95)
    assert p.unit_price_label == "kr/kg"
    assert p.slug == "havregryn-finvalsede-oeko-5050406"
    assert p.available and not p.on_offer  # DiscountItem is the budget range, not an offer
    assert "Øko (dansk)" in p.labels


@pytest.mark.parametrize(
    ("campaign", "text"),
    [
        ({"CampaignPrice": 50.0, "MinQuantity": 3}, "3 for 50 kr"),
        ({"CampaignPrice": 16.95, "MinQuantity": 1}, "16,95 kr"),
        (None, None),
    ],
)
def test_campaign_offer_text(campaign, text):
    p = Product.from_api({"Id": "1", "Name": "Mælk", "Price": 18.0, "Campaign": campaign})
    assert p.offer == text
    assert p.on_offer is (text is not None)


def test_unavailable_product():
    p = Product.from_api({"Id": 7, "Name": "x", "Availability": {"IsAvailableInStock": False}})
    assert p.id == "7"
    assert not p.available


def test_productbff_product_converts_ore():
    item = fixture("productbff_favourites.json")["pageContent"][0]["products"][0]
    p = Product.from_productbff(item)
    assert (p.id, p.name, p.price, p.original_price) == ("106499", "Cherrytomater øko.", 12.0, 15.0)
    assert (p.unit_price, p.unit_price_label) == (48.0, "kr/kg")
    assert p.offer == "Spar 3,-" and p.on_offer
    assert p.favourite and p.available
    assert p.labels == ["Øko (europæisk)"]


def test_product_details():
    d = ProductDetails.from_api(fixture("product_details.json")["productdetailspot"])
    assert d.id == "5050406"
    assert d.attributes["Allergener"] == ["Gluten", "Havre"]
    assert d.origin == "EU/Ikke-EU-jordbrug"
    assert d.text and d.text.startswith("Økologiske havregryn")
    assert d.declaration and "<" not in d.declaration and "Næringsindhold" in d.declaration


def test_basket():
    b = Basket.from_api(fixture("basket.json"))
    assert len(b.lines) == 2
    assert b.quantity_of("5034594") == 2
    assert b.quantity_of(5036764) == 1
    assert b.quantity_of("0") == 0
    assert b.total_price == 229.05
    assert not b.is_min_total_valid
    assert b.delivery_slot and b.delivery_slot.id == 2403209 and b.delivery_slot.reserved
    assert b.delivery_slot.label == "tirs. 29/09 kl. 11-13"
    ctx = b.delivery_context
    assert ctx and (ctx.timeslot_utc, ctx.zone_id, ctx.slot_id) == ("2026092909-120-1260", 4, 2403209)


def test_sold_out_basket_line():
    data = fixture("basket.json")
    line = dict(data["Lines"][0], Quantity=0, CheckoutHistoricalRecord={"AvailabilityStatus": 1})
    b = Basket.from_api(dict(data, Lines=[line]))
    assert b.lines[0].quantity == 0 and not b.lines[0].available


def test_delivery_days():
    days = [DeliveryDay.from_api(d) for d in fixture("delivery_days_anonymous.json")["DayRangeHours"]]
    assert days[0].date == date(2026, 9, 27)
    slot = days[0].slots[0]
    assert slot.availability is SlotAvailability.PAST_DEADLINE and not slot.is_available
    assert days[1].slots[0].is_available
    assert (slot.start_hour, slot.end_hour, slot.price) == (1, 6, 29.0)
    assert days[0].note and "<" not in days[0].note


def test_orders():
    summaries = [OrderSummary.from_api(o) for o in fixture("order_history.json")["Orders"]]
    assert summaries[0].id == 10000001 and summaries[0].status == 3 and summaries[0].total == 496.2
    order = Order.from_api(fixture("order_lines.json"))
    assert order.id == 10000001
    assert [line.product_id for line in order.lines] == ["5027015", "5012294"]
    assert order.lines[1].discount == 3.0
    assert order.delivery_price == 19.0


def test_shopping_lists():
    overview = fixture("shopping_lists.json")["ShoppingListOverViewViewModels"]
    summary = ShoppingListSummary.from_api(overview[0])
    assert (summary.id, summary.product_count, summary.total) == (100001, 4, 58.45)
    full = ShoppingList.from_api(
        {
            "Id": 5,
            "Name": "Weekend",
            "ProductsCount": 2,
            "TotalAmount": 19.9,
            "Lines": [
                {
                    "Id": "5050406",
                    "Name": "Havregryn",
                    "Quantity": 2,
                    "ItemPrice": 9.95,
                    "ProductsTotalAmount": 19.9,
                    "IsProductDeactivated": False,
                }
            ],
        }
    )
    assert full.items[0].product_id == "5050406" and full.items[0].quantity == 2


def test_suggestions():
    s = Suggestions.from_api(fixture("search_quick.json"), "havre")
    assert s.suggestions == ["havre", "havregryn"]
    assert s.categories[1].url == "/dagligvarer/kolonial/morgenmad/musli-granola"


def test_account_has_no_personal_data():
    a = Account.from_api(fixture("current_user.json"))
    assert a.logged_in
    assert set(a.model_dump()) == {"logged_in", "member_type", "has_upcoming_order"}


@pytest.mark.parametrize(
    ("name", "build"),
    [
        ("basket.json", Basket.from_api),
        ("order_lines.json", Order.from_api),
        ("current_user.json", Account.from_api),
    ],
)
def test_personal_fields_never_reach_models(name, build):
    """The fixtures mark every personal value "<redacted>"; none of them may come through."""
    dumped = json.dumps(build(fixture(name)).model_dump(mode="json"), ensure_ascii=False)
    assert "<redacted>" not in dumped
    for key in ("address", "email", "phone", "debitor", "order_number", "notes", "guid"):
        assert key not in dumped.lower()
