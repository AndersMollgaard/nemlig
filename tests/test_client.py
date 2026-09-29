import json

import httpx
import pytest
from conftest import GW, WWW, fixture

from nemlig import ApiError


def body(route) -> dict:
    return json.loads(route.calls.last.request.content)


def params(route) -> dict:
    return dict(route.calls.last.request.url.params)


@pytest.fixture
def basket_route(api):
    return api.get(f"{WWW}/webapi/basket/GetBasket").respond(json=fixture("basket.json"))


@pytest.fixture
def add_route(api):
    return api.post(f"{WWW}/webapi/basket/AddToBasket").respond(json=fixture("basket.json"))


def test_search_uses_the_basket_delivery_context(api, customer, basket_route):
    search = api.get(f"{GW}/searchgateway/api/search").respond(json=fixture("search.json"))
    result = customer.search("havregryn", limit=5)
    assert result.products[0].id == "5050406"
    p = params(search)
    assert p["query"] == "havregryn" and p["take"] == "5" and p["skip"] == "0"
    assert (p["timeslotUtc"], p["deliveryZoneId"], p["TimeSlotId"]) == ("2026092909-120-1260", "4", "2403209")
    assert search.calls.last.request.headers["Authorization"].startswith("Bearer ")
    customer.search("mælk")
    assert basket_route.call_count == 1  # context is cached


def test_search_many_keeps_query_order_and_resolves_context_once(api, customer, basket_route):
    def respond(request):
        data = {**fixture("search.json"), "SearchQuery": request.url.params["query"]}
        return httpx.Response(200, json=data)

    search = api.get(f"{GW}/searchgateway/api/search").mock(side_effect=respond)
    queries = ["a", "bb", "ccc", "æg", "mælk"]
    results = customer.search_many(queries, limit=5)
    assert [r.query for r in results] == queries
    assert search.call_count == len(queries)
    assert basket_route.call_count == 1
    assert {c.request.url.params["TimeSlotId"] for c in search.calls} == {"2403209"}


def test_search_many_raises_when_one_query_fails(api, customer, basket_route):
    def respond(request):
        if request.url.params["query"] == "bad":
            return httpx.Response(400, json={"ErrorCode": 1, "ErrorMessage": "nope"})
        return httpx.Response(200, json=fixture("search.json"))

    api.get(f"{GW}/searchgateway/api/search").mock(side_effect=respond)
    with pytest.raises(ApiError):
        customer.search_many(["ok", "bad", "ok2"])


def test_anonymous_search_uses_bootstrap_context(api, anonymous):
    search = api.get(f"{GW}/searchgateway/api/search").respond(json=fixture("search.json"))
    anonymous.search("havregryn")
    p = params(search)
    assert (p["timeslotUtc"], p["deliveryZoneId"]) == ("2026092714-60-240", "1")
    assert "TimeSlotId" not in p


@pytest.fixture
def days_route(api):
    return api.get(f"{WWW}/webapi/v2/Delivery/GetDeliveryDays").respond(
        json=fixture("delivery_days_anonymous.json")
    )


def test_search_for_another_slot(api, customer, basket_route, days_route):
    search = api.get(f"{GW}/searchgateway/api/search").respond(json=fixture("search.json"))
    customer.search_many(["a", "b"], slot_id=2400911)  # 28/09 05-07, deadline 27/09 16:00
    assert days_route.call_count == 1
    p = params(search)
    assert (p["timeslotUtc"], p["deliveryZoneId"], p["TimeSlotId"]) == ("2026092803-120-780", "4", "2400911")


def test_offers_for_another_slot(api, customer, basket_route, days_route):
    route = api.get(f"{GW}/productbff/api/web/page").respond(json=fixture("productbff_favourites.json"))
    assert customer.get_offers(limit=3, slot_id=2400911)
    assert params(route) == {"path": "/tilbud", "timeslotId": "2400911"}
    customer.get_offers(limit=3)
    assert params(route) == {"path": "/tilbud", "timeslotId": "2403209"}


def test_unknown_slot_is_rejected(api, customer, basket_route, days_route):
    with pytest.raises(ValueError, match="no delivery slot 1 "):
        customer.search("mælk", slot_id=1)


def test_get_product_by_id_uses_redirecting_path(api, anonymous):
    api.get(f"{WWW}/p-5050406").respond(301, headers={"Location": "/havregryn-finvalsede-oeko-5050406"})
    page = {"content": [{"TemplateName": "ribbon"}, fixture("product_details.json")["productdetailspot"]]}
    api.get(f"{WWW}/havregryn-finvalsede-oeko-5050406").respond(json=page)
    assert anonymous.get_product(5050406).name == "Havregryn (finvalsede) øko."
    assert anonymous.get_product("havregryn-finvalsede-oeko-5050406").id == "5050406"


def test_get_product_not_a_product_page(api, anonymous):
    api.get(f"{WWW}/something").respond(json={"content": [{"TemplateName": "ribbon"}]})
    with pytest.raises(ApiError) as exc:
        anonymous.get_product("something")
    assert exc.value.status == 404


def test_set_quantity_is_absolute(customer, add_route):
    basket = customer.set_quantity("5034594", 3)
    assert basket.quantity_of("5034594") == 2  # whatever the server says
    assert body(add_route) == {
        "ProductId": "5034594",
        "quantity": 3,
        "AffectPartialQuantity": False,
        "disableQuantityValidation": False,
    }


def test_remove_uses_affect_partial_quantity(customer, add_route):
    customer.remove_from_basket(5034594)
    assert body(add_route)["quantity"] == 0
    assert body(add_route)["AffectPartialQuantity"] is True


def test_add_to_basket_is_additive(customer, add_route):
    customer.add_to_basket("5034594", 2)
    assert body(add_route) == {"productId": "5034594", "quantity": 2, "addToExisting": True}


@pytest.mark.parametrize(("qty", "error"), [(-1, ValueError), (1.5, TypeError), (True, TypeError)])
def test_set_quantity_validates(customer, qty, error):
    with pytest.raises(error):
        customer.set_quantity("1", qty)


def test_remove_sold_out(api, customer, add_route):
    data = fixture("basket.json")
    sold_out = dict(data["Lines"][0], Quantity=0)
    api.get(f"{WWW}/webapi/basket/GetBasket").respond(json=dict(data, Lines=[sold_out, data["Lines"][1]]))
    customer.remove_sold_out()
    assert add_route.call_count == 1
    assert body(add_route)["ProductId"] == sold_out["Id"]


def test_clear_basket_reads_back(api, customer, basket_route):
    clear = api.post(f"{WWW}/webapi/basket/ClearBasket").respond(200, content=b"")
    assert customer.clear_basket().total_price == 229.05
    assert clear.called and basket_route.called


def test_reorder_sends_numeric_id_as_order_number(api, customer, basket_route):
    copy = api.post(f"{WWW}/webapi/order/CopyOrder").respond(
        json={"ValidationFailures": [{"Group": 1, "Message": "Changes to basket"}]}
    )
    basket = customer.reorder(10000001)
    assert body(copy) == {"OrderNumber": "10000001"}
    assert basket.validation_failures[0].group == 1
    assert basket.validation_failures[0].message == "Changes to basket"


def test_orders(api, customer):
    history = api.get(f"{WWW}/webapi/order/GetBasicOrderHistory").respond(json=fixture("order_history.json"))
    api.get(f"{WWW}/webapi/v2/order/GetOrderHistory/10000001").respond(json=fixture("order_lines.json"))
    orders = customer.get_orders(limit=2, page=3)
    assert params(history) == {"skip": "3", "take": "2"}
    assert customer.get_order(orders[0].id).lines[0].product_id == "5027015"


def test_delivery_days_and_reservation(api, customer, basket_route):
    days = api.get(f"{WWW}/webapi/v2/Delivery/GetDeliveryDays").respond(
        json=fixture("delivery_days_anonymous.json")
    )
    assert len(customer.get_delivery_days(days=2)) == 2
    assert params(days) == {"startDate": "undefined", "days": "2", "showForSubscriptions": "false"}

    reserve = api.post(f"{WWW}/webapi/Delivery/TryUpdateDeliveryTime").respond(json={"IsReserved": True})
    result = customer.reserve_slot(2403209)
    assert params(reserve) == {"timeslotId": "2403209"}
    assert result.reserved and result.slot and result.slot.id == 2403209


def test_favourites_dedupe(api, customer, basket_route):
    page = fixture("productbff_favourites.json")
    route = api.get(f"{GW}/productbff/api/web/page").respond(json=page)
    favourites = customer.get_favourites()
    all_ids = [p["id"] for s in page["pageContent"] for p in s["products"]]
    assert [p.id for p in favourites] == list(dict.fromkeys(all_ids))
    assert params(route) == {"path": "/favoritter", "timeslotId": "2403209"}


def test_shopping_lists(api, customer, basket_route):
    lst = {"Id": 9, "Name": "Uge", "ProductsCount": 0, "TotalAmount": 0.0, "Lines": []}
    api.get(f"{WWW}/webapi/ShoppingList/GetShoppingLists").respond(json=fixture("shopping_lists.json"))
    create = api.post(f"{WWW}/webapi/ShoppingList/CreateShoppingList").respond(json=lst)
    update = api.post(f"{WWW}/webapi/ShoppingList/UpdateProductInShoppingList").respond(json={"List": lst})
    remove = api.post(f"{WWW}/webapi/ShoppingList/RemoveShoppingList").respond(200, content=b"")
    to_basket = api.post(f"{WWW}/webapi/basket/addShoppingListToBasket").respond(json=fixture("basket.json"))

    assert customer.get_shopping_lists()[0].id == 100001
    assert customer.create_shopping_list("Uge").id == 9
    assert params(create) == {"name": "Uge"}
    customer.set_shopping_list_item(9, "5050406", 2)
    assert params(update) == {"listId": "9", "productId": "5050406", "amount": "2"}
    customer.delete_shopping_list(9)
    assert params(remove) == {"listId": "9"}
    customer.add_shopping_list_to_basket(9)
    assert body(to_basket) == {"ListId": 9, "ConfirmMissingProducts": False}


def test_shopping_lists_page_by_offset(api, customer):
    def page(start, count):
        return {
            "ShoppingListOverViewViewModels": [{"Id": i, "Name": "x"} for i in range(start, start + count)]
        }

    route = api.get(f"{WWW}/webapi/ShoppingList/GetShoppingLists").mock(
        side_effect=[httpx.Response(200, json=page(0, 50)), httpx.Response(200, json=page(50, 3))]
    )
    assert [s.id for s in customer.get_shopping_lists()] == list(range(53))
    assert [dict(c.request.url.params)["skip"] for c in route.calls] == ["0", "50"]


def test_shopping_lists_stop_when_a_page_repeats(api, customer):
    full = {"ShoppingListOverViewViewModels": [{"Id": i, "Name": "x"} for i in range(50)]}
    route = api.get(f"{WWW}/webapi/ShoppingList/GetShoppingLists").respond(json=full)
    assert len(customer.get_shopping_lists()) == 50
    assert route.call_count == 2


def test_reserve_slot_tolerates_a_bare_boolean(api, customer, basket_route):
    api.post(f"{WWW}/webapi/Delivery/TryUpdateDeliveryTime").respond(json=True)
    assert customer.reserve_slot(2403209).reserved


@pytest.mark.parametrize("bad", ["../webapi/user/GetCurrentUser", "a/b", "x?GetAsJson=0", "", "p-1#404"])
def test_get_product_rejects_other_paths(customer, bad):
    with pytest.raises(ValueError):
        customer.get_product(bad)


def test_empty_basket_body_is_an_api_error(api, customer):
    api.get(f"{WWW}/webapi/basket/GetBasket").respond(200, content=b"")
    with pytest.raises(ApiError):
        customer.get_basket()
