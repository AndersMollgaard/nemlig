import io
import json
import sys

import httpx
import pytest
from conftest import GW, WWW, fixture, token_body

from nemlig import cli

ERROR = fixture("error_copyorder_not_found.json")


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch, tmp_path):
    for name in (
        "NEMLIG_USER",
        "NEMLIG_PASS",
        "NEMLIG_ENV_FILE",
        "NEMLIG_PREFS_FILE",
        "NEMLIG_CACHE_DIR",
        "NEMLIG_GROUPS_FILE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))  # no ~/.cache/nemlig


def run(capsys, *argv):
    code = cli.main(["--no-session", *argv])
    out, err = capsys.readouterr()
    return code, out, err


@pytest.fixture
def customer(api):
    api.get(f"{WWW}/webapi/Token").respond(json=token_body(debitor="123"))


@pytest.fixture
def anonymous(api):
    api.get(f"{WWW}/webapi/Token").respond(json=token_body())
    settings = fixture("bootstrap_getasjson.json")["Settings"]
    api.get(f"{WWW}/", params={"GetAsJson": "1"}).respond(json={"Settings": settings})


@pytest.fixture
def add_route(api):
    return api.post(f"{WWW}/webapi/basket/AddToBasket").respond(json=fixture("basket.json"))


def test_search_prints_trimmed_json(api, anonymous, capsys):
    search = api.get(f"{GW}/searchgateway/api/search").respond(json=fixture("search.json"))
    code, out, _ = run(capsys, "search", "havregryn", "--limit", "3")
    assert code == 0
    assert search.calls.last.request.url.params["take"] == "3"
    result = json.loads(out)
    assert result["query"] and result["total"] >= len(result["products"])
    product = result["products"][0]
    assert product["id"] == "5050406" and "price" in product and "available" in product
    assert "image" not in product and "slug" not in product
    assert all(v is not None and v != [] for v in product.values())


def test_search_text(api, anonymous, capsys):
    api.get(f"{GW}/searchgateway/api/search").respond(json=fixture("search.json"))
    code, out, _ = run(capsys, "search", "havregryn", "--text")
    assert code == 0
    lines = out.splitlines()
    assert "results for 'havregryn'" in lines[0]
    assert lines[1].startswith("5050406  ") and " kr" in lines[1]


def test_search_several_queries(api, anonymous, capsys):
    def respond(request):
        data = {**fixture("search.json"), "SearchQuery": request.url.params["query"]}
        return httpx.Response(200, json=data)

    search = api.get(f"{GW}/searchgateway/api/search").mock(side_effect=respond)
    code, out, _ = run(capsys, "search", "mælk", "hakket oksekød", "--limit", "2")
    assert code == 0
    assert search.call_count == 2
    assert [r["query"] for r in json.loads(out)] == ["mælk", "hakket oksekød"]

    code, out, _ = run(capsys, "--text", "search", "mælk", "æg")
    heads = [line for line in out.splitlines() if "results for" in line]
    assert [h.split("results for ")[1] for h in heads] == ["'mælk'", "'æg'"]


def _search_with(*products):
    """The search fixture with extra products next to its two havregryn (9.95 and 10.64 kr/kg)."""
    data = fixture("search.json")
    base = data["Products"]["Products"][0]
    extra = [{**base, "Campaign": None, **p} for p in products]
    return {**data, "Products": {**data["Products"], "Products": data["Products"]["Products"] + extra}}


def test_search_cheaper_than_a_basket_line(api, customer, capsys):
    # The basket's havregryn [5034594] is 2 x 1 kg at 7.95 kr/kg (sent as "kr./Kg."), 15.90 kr.
    api.get(f"{WWW}/webapi/basket/GetBasket").respond(json=fixture("basket.json"))
    search = api.get(f"{GW}/searchgateway/api/search").respond(
        json=_search_with(
            {"Id": "1", "Price": 6.0, "UnitPriceCalc": 6.0},  # 2 x 1 kg saves 3.90
            {
                "Id": "2",
                "Price": 10.0,
                "UnitPriceCalc": 10.0,
                "Campaign": {"CampaignPrice": 11.0, "MinQuantity": 2},
            },
            {"Id": "3", "Price": 5.0, "UnitPriceCalc": 5.0, "Availability": {"IsAvailableInStock": False}},
            {"Id": "4", "Price": 1.0, "UnitPriceCalc": 1.0, "UnitPriceLabel": "kr/stk"},
            {"Id": "5", "Price": 7.6, "UnitPriceCalc": 7.6},  # saves 0.70: not worth a swap
            {"Id": "6", "Price": 25.0, "UnitPriceCalc": 5.0},  # 5 kg: cheaper per kg, dearer in total
            {
                "Id": "7",
                "Price": 10.0,
                "UnitPriceCalc": 10.0,
                "Campaign": {"CampaignPrice": 18.0, "MinQuantity": 3},
            },
            {"Id": "8", "Price": 3.0, "UnitPriceCalc": 6.0},  # 500 g: 4 packs save 3.90
        )
    )
    code, out, _ = run(capsys, "search", "havregryn", "--cheaper-than", "5034594")
    assert code == 0 and search.call_count == 1
    result = json.loads(out)
    products = {p["id"]: p for p in result["products"]}
    assert list(products) == ["2", "1", "8", "7"]  # biggest saving first, stock-up offers last
    assert products["2"]["offer_unit_price"] == 5.5
    assert products["2"]["swap"] == {"quantity": 2, "saving": 4.9, "amount": 1.0}
    assert products["8"]["swap"]["quantity"] == 4
    assert products["7"]["swap"]["offer_quantity"] == 3
    assert result["than"]["unit_price"] == 7.95

    code, out, _ = run(capsys, "--text", "search", "havregryn", "--cheaper-than", "5034594")
    head, *rows = out.splitlines()
    assert head.endswith("cheaper than 2 x Havregryn (finvalsede) (1 kg / Go' Morgen) 15.90 kr (7.95 kr/kg)")
    assert rows[0].endswith("offer: 2 for 11 kr (5.50 kr/kg)  2x saves 4.90 kr")
    assert rows[-1].endswith("buy 3 for the offer")


def _write_prefs(tmp_path, text):
    (tmp_path / "preferences.toml").write_text(text, encoding="utf-8")  # NEMLIG_HOME, the repo root


def test_search_cheaper_than_applies_keep_and_avoid_rules(api, customer, capsys, tmp_path):
    _write_prefs(
        tmp_path, '[[keep]]\nname = "popcorn"\nnote = "the kids choose"\n\n[[avoid]]\nbrand = "cheapo"\n'
    )
    api.get(f"{WWW}/webapi/basket/GetBasket").respond(json=fixture("basket.json"))
    search = api.get(f"{GW}/searchgateway/api/search").respond(
        json=_search_with(
            {"Id": "1", "Price": 6.0, "UnitPriceCalc": 6.0, "Brand": "Cheapo"},
            {"Id": "2", "Price": 6.5, "UnitPriceCalc": 6.5},
        )
    )
    argv = ["search", "popcorn", "havregryn", "--cheaper-than", "5036764", "5034594"]
    code, out, _ = run(capsys, "--text", *argv)
    assert code == 0
    assert [c.request.url.params["query"] for c in search.calls] == ["havregryn"]  # popcorn is kept
    head, *rows = out.splitlines()
    assert head == "skipped 'popcorn': keep rule name 'popcorn' (the kids choose)"
    assert [r.split()[0] for r in rows[1:]] == ["2"]  # Cheapo is avoided


def test_prefs_add_and_show(capsys, tmp_path):
    code, out, _ = run(capsys, "--text", "prefs")
    assert code == 0 and "(not created yet)" in out
    run(capsys, "prefs", "avoid", "--brand", "First Price", "--name", "toiletpapir", "--note", "for tynd")
    code, out, _ = run(capsys, "--text", "prefs", "keep", "--id", "5027015")
    assert code == 0
    assert out.splitlines()[1:] == [
        "keep: id '5027015'",
        "avoid: brand 'First Price' name 'toiletpapir' (for tynd)",
    ]
    assert (tmp_path / "preferences.toml").is_file()
    code, _, err = run(capsys, "prefs", "keep")
    assert code == 2 and "at least one of id, brand or name" in err


def test_credentials_and_prefs_come_from_the_repo_root_not_the_working_directory(
    api, capsys, tmp_path, monkeypatch
):
    api.get(f"{WWW}/webapi/Token").respond(json=token_body())
    (tmp_path / ".env").write_text("NEMLIG_USER=a@example.com\nNEMLIG_PASS=secret\n", encoding="utf-8")
    _write_prefs(tmp_path, 'diet = "No pork."\n')
    elsewhere = tmp_path / "other-project"
    elsewhere.mkdir()
    (elsewhere / ".env").write_text("NEMLIG_USER=b@example.com\nNEMLIG_PASS=other\n", encoding="utf-8")
    monkeypatch.chdir(elsewhere)
    assert cli._env_file(None) == tmp_path / ".env"
    code, out, _ = run(capsys, "status")
    assert code == 0 and json.loads(out)["has_credentials"] is True
    code, out, _ = run(capsys, "--text", "prefs")
    assert out.splitlines() == [f"file: {tmp_path / 'preferences.toml'}", "diet: No pork."]


def test_output_is_utf8_even_when_the_pipe_is_not(capsys, tmp_path, monkeypatch):
    # Piped on Windows, stdout is in the ANSI code page (cp1252), which has no ★.
    _write_prefs(tmp_path, 'diet = "Ingen svinekød ★"\n')
    with capsys.disabled():
        out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        monkeypatch.setattr(sys, "stdout", out)
        assert cli.main(["--no-session", "--text", "prefs"]) == 0
        out.flush()
        assert out.buffer.getvalue().decode("utf-8").endswith("diet: Ingen svinekød ★\n")


def test_search_and_offers_mark_avoided_products(api, anonymous, capsys, tmp_path):
    _write_prefs(tmp_path, '[[avoid]]\nname = "havregryn"\n')
    api.get(f"{GW}/searchgateway/api/search").respond(json=fixture("search.json"))
    _, out, _ = run(capsys, "search", "havregryn", "--limit", "3")
    products = json.loads(out)["products"]
    assert products and all(p["avoided"] for p in products if "havregryn" in p["name"].lower())
    assert all("avoided" not in p for p in products if "havregryn" not in p["name"].lower())
    _, out, _ = run(capsys, "--text", "search", "havregryn")
    assert any(row.endswith("  AVOID") for row in out.splitlines()[1:])
    api.get(f"{GW}/productbff/api/web/page").respond(json=fixture("productbff_offers.json"))
    _write_prefs(tmp_path, '[[avoid]]\nid = "5027568"\n')
    _, out, _ = run(capsys, "--text", "offers", "--category", "koed")
    rows = out.splitlines()
    assert rows[0].startswith("5027568") and rows[0].endswith("  AVOID")
    assert not any(row.endswith("AVOID") for row in rows[1:])


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["a", "b", "--cheaper-than", "5034594"], "one basket product id per query"),
        (["a", "--cheaper-than", "999"], "not in the basket: 999"),
    ],
)
def test_search_cheaper_than_usage(api, customer, capsys, argv, message):
    api.get(f"{WWW}/webapi/basket/GetBasket").respond(json=fixture("basket.json"))
    search = api.get(f"{GW}/searchgateway/api/search").respond(json=fixture("search.json"))
    code, _, err = run(capsys, "search", *argv)
    assert code == 2 and message in err
    assert search.call_count == 0


def test_basket_add_several_items(api, customer, add_route, capsys):
    code, out, _ = run(capsys, "basket", "add", "111:2", "222")
    assert code == 0
    bodies = [json.loads(c.request.content) for c in add_route.calls]
    assert [(b["productId"], b["quantity"], b["addToExisting"]) for b in bodies] == [
        ("111", 2, True),
        ("222", 1, True),
    ]
    basket = json.loads(out)
    assert basket["total_price"] == 229.05
    assert [line["product_id"] for line in basket["lines"]] == ["5036764", "5034594"]
    assert basket["lines"][0]["unit_price_label"] == "kr/kg"
    assert "delivery_context" not in basket


def test_basket_add_text_says_what_was_added(api, customer, add_route, capsys):
    # The fixture basket has 2 x havregryn for 15.90 kr, so adding 1 accounts for 7.95 kr.
    code, out, _ = run(capsys, "--text", "basket", "add", "5034594", "999")
    assert code == 0
    assert out.splitlines()[0] == "added: 2 lines, 7.95 kr"


def test_basket_set_zero_removes(api, customer, add_route, capsys):
    code, _, _ = run(capsys, "basket", "set", "5036764:0")
    assert code == 0
    body = json.loads(add_route.calls.last.request.content)
    assert (body["ProductId"], body["quantity"], body["AffectPartialQuantity"]) == ("5036764", 0, True)


def test_basket_text(api, customer, capsys):
    api.get(f"{WWW}/webapi/basket/GetBasket").respond(json=fixture("basket.json"))
    code, out, _ = run(capsys, "--text", "basket")
    assert code == 0
    assert "[5036764]" in out and "total 229.05 kr" in out


@pytest.mark.parametrize("item", ["111", "111:x", ":2"])
def test_bad_item_is_a_usage_error_before_any_request(api, capsys, item):
    code, _, err = run(capsys, "basket", "set", item)
    assert code == 2
    assert "ID:QTY" in err or "quantity" in err
    assert not api.calls


def test_clear_needs_yes(api, customer, capsys):
    clear = api.post(f"{WWW}/webapi/basket/ClearBasket").respond(json={})
    code, _, err = run(capsys, "basket", "clear")
    assert code == 2
    assert json.loads(err)["error"] == "UsageError"
    assert not clear.called


def test_not_logged_in(api, anonymous, capsys):
    code, out, err = run(capsys, "basket")
    assert code == 3 and out == ""
    info = json.loads(err)
    assert info["error"] == "NotLoggedInError" and "NEMLIG_USER" in info["message"]


def test_api_error_mid_batch_reports_applied(api, customer, capsys):
    api.post(f"{WWW}/webapi/basket/AddToBasket").mock(
        side_effect=[
            httpx.Response(200, json=fixture("basket.json")),
            httpx.Response(ERROR["status"], json=ERROR["body"]),
        ]
    )
    code, out, err = run(capsys, "basket", "add", "111:2", "222", "333")
    assert code == 1 and out == ""
    info = json.loads(err)
    assert info["error"] == "ApiError" and info["error_code"] == 8
    assert info["applied"] == ["111:2"]


def test_delivery_available_filter(api, customer, capsys):
    api.get(f"{WWW}/webapi/v2/Delivery/GetDeliveryDays").respond(json=fixture("delivery_days_anonymous.json"))
    _, out, _ = run(capsys, "delivery")
    _, available, _ = run(capsys, "delivery", "--available")
    all_slots = [s for d in json.loads(out) for s in d["slots"]]
    open_slots = [s for d in json.loads(available) for s in d["slots"]]
    assert open_slots and len(open_slots) < len(all_slots)
    assert all(s["availability"] == 0 for s in open_slots)


def test_delivery_reserve_text_shows_the_price_change(api, customer, capsys):
    api.get(f"{WWW}/webapi/basket/GetBasket").respond(json=fixture("basket.json"))
    api.post(f"{WWW}/webapi/Delivery/TryUpdateDeliveryTime").respond(
        json={
            "IsReserved": False,
            "ProductLineDiffs": [
                {"ProductName": "Laks", "Undeliverable": False, "AmountDiff": -30.8},
                {"ProductName": "Peber", "Undeliverable": True, "AmountDiff": 0},
            ],
        }
    )
    api.post(f"{WWW}/webapi/Delivery/UpdateDeliveryTime").respond(json={"IsReserved": True})
    code, out, _ = run(capsys, "--text", "delivery", "reserve", "2403209")
    assert code == 0
    assert out.startswith("reserved: ")
    assert "(basket -30.80 kr; undeliverable: Peber)" in out


def test_delivery_reserve_fails_with_exit_1(api, customer, capsys):
    api.get(f"{WWW}/webapi/basket/GetBasket").respond(json=fixture("basket.json"))
    api.post(f"{WWW}/webapi/Delivery/TryUpdateDeliveryTime").respond(
        json={"IsReserved": False, "Message": "Tidspunktet er udsolgt"}
    )
    code, out, err = run(capsys, "--text", "delivery", "reserve", "2400911")
    assert code == 1 and out == ""
    assert err.strip() == (
        "error: slot 2400911 not reserved: Tidspunktet er udsolgt; "
        "the basket's slot is tirs. 29/09 kl. 11-13 (reserved)"
    )
    # Reserved, but not the slot that was asked for.
    api.post(f"{WWW}/webapi/Delivery/TryUpdateDeliveryTime").respond(json={"IsReserved": True})
    code, _, err = run(capsys, "delivery", "reserve", "2400911")
    assert code == 1 and json.loads(err)["error"] == "NotReservedError"


def test_search_and_offers_take_a_slot(api, anonymous, capsys):
    api.get(f"{WWW}/webapi/v2/Delivery/GetDeliveryDays").respond(json=fixture("delivery_days_anonymous.json"))
    search = api.get(f"{GW}/searchgateway/api/search").respond(json=fixture("search.json"))
    offers = api.get(f"{GW}/productbff/api/web/page").respond(json=fixture("productbff_favourites.json"))
    assert run(capsys, "search", "mælk", "--slot", "2400911")[0] == 0
    assert search.calls.last.request.url.params["timeslotUtc"] == "2026092803-120-780"
    assert run(capsys, "offers", "--slot", "2400911")[0] == 0
    assert offers.calls.last.request.url.params["timeslotId"] == "2400911"
    code, _, err = run(capsys, "offers", "--slot", "1")
    assert code == 2 and "no delivery slot 1" in err


def test_slot_of_the_basket_needs_no_lookup(api, customer, capsys):
    # No GetDeliveryDays route: the basket's own slot is priced from the basket's context.
    api.get(f"{WWW}/webapi/basket/GetBasket").respond(json=fixture("basket.json"))
    search = api.get(f"{GW}/searchgateway/api/search").respond(json=fixture("search.json"))
    assert run(capsys, "search", "mælk", "--slot", "2403209")[0] == 0
    params = search.calls.last.request.url.params
    assert params["timeslotUtc"] == "2026092909-120-1260" and params["TimeSlotId"] == "2403209"


@pytest.fixture
def offers_route(api, anonymous):
    return api.get(f"{GW}/productbff/api/web/page").respond(json=fixture("productbff_offers.json"))


def ids(out):
    return [p["id"] for p in json.loads(out)]


def test_offers_filters(offers_route, capsys):
    # "kød" folds to Koed and matches Frost/Koed too; the duplicate is listed once.
    _, out, _ = run(capsys, "offers", "--category", "kød")
    assert ids(out) == ["5027568", "5071248", "5056387", "5604676"]
    _, out, _ = run(capsys, "offers", "--category", "Kylling", "frugt og grønt")
    assert ids(out) == ["5056387", "5000033"]
    _, out, _ = run(capsys, "offers", "--min-discount", "15")
    assert ids(out) == ["5056387", "5604676", "5000033"]
    _, out, _ = run(capsys, "offers", "--category", "koed", "--min-discount", "10", "--limit", "2")
    assert ids(out) == ["5027568", "5056387"]


def test_offers_text_shows_discount(offers_route, capsys):
    _, out, _ = run(capsys, "offers", "--category", "koed", "--text")
    rows = out.splitlines()
    assert rows[0].startswith("5027568") and "99.00 kr (99.00 kr/kg) -14%" in rows[0]
    assert "Spar" not in rows[0]  # the badge only restates the discount
    assert "offer: God pris" in rows[1]
    assert "-15%  offer: 3 for 112,50 kr (133.92 kr/kg)" in rows[2]


def test_offers_categories(offers_route, capsys):
    _, out, _ = run(capsys, "offers", "--categories", "--text")
    assert out.splitlines()[0] == "Koed 3: Oksekoed 2, Kylling 1"
    _, out, _ = run(capsys, "offers", "--categories", "--min-discount", "20")
    assert json.loads(out) == [
        {"name": "Frost", "count": 1, "sub": {"Koed": 1}},
        {"name": "Frugt-og-groent", "count": 1, "sub": {"Frugt": 1}},
    ]


def test_orders_sync(api, customer, capsys, tmp_path):
    api.get(f"{WWW}/webapi/order/GetBasicOrderHistory").respond(json=fixture("order_history.json"))
    lines = fixture("order_lines.json")
    for i in (10000001, 10000002):
        api.get(f"{WWW}/webapi/v2/order/GetOrderHistory/{i}").respond(json={**lines, "Id": i})
    code, out, _ = run(capsys, "orders", "sync", "--text")
    assert code == 0
    head, path = out.splitlines()
    assert head == "2 of 2 orders cached (2 new, 0 not finished), 2026-09-11 to 2026-09-21"
    assert path.startswith(str(tmp_path / "cache" / "nemlig" / "orders"))


def test_orders_show_defaults_to_the_latest(api, customer, capsys):
    api.get(f"{WWW}/webapi/order/GetBasicOrderHistory").respond(json=fixture("order_history.json"))
    latest = api.get(f"{WWW}/webapi/v2/order/GetOrderHistory/10000001").respond(
        json=fixture("order_lines.json")
    )
    code, out, _ = run(capsys, "--text", "orders", "show")
    assert code == 0 and latest.call_count == 1
    assert out.startswith("10000001  2026-09-21 10:00")


@pytest.fixture
def history(api, customer):
    """Two past orders, each with the order-lines fixture's Java Colombia and Blomkål."""
    orders = fixture("order_history.json")
    api.get(f"{WWW}/webapi/order/GetBasicOrderHistory").respond(json=orders)
    lines = fixture("order_lines.json")
    for o in orders["Orders"]:
        api.get(f"{WWW}/webapi/v2/order/GetOrderHistory/{o['Id']}").respond(
            json={**lines, "Id": o["Id"], "DeliveryTime": o["DeliveryTime"]}
        )


def test_restock(api, history, capsys):
    api.get(f"{WWW}/webapi/basket/GetBasket").respond(json=fixture("basket.json"))
    offers = api.get(f"{GW}/productbff/api/web/page").respond(json=fixture("productbff_offers.json"))
    code, out, _ = run(capsys, "restock", "--text", "--exclude", "Grønt")
    assert code == 0
    assert out.splitlines() == [
        "due for tirs. 29/09 kl. 11-13 (add):",
        "  5027015  Java Colombia (450 g / hele bønner / Peter Larsen Kaffe)  x2  75%  last 21/09",
        "to review: 2 new products (nemlig restock groups)",
    ]
    assert offers.called
    code, out, _ = run(capsys, "restock", "--no-offers")
    data = json.loads(out)
    assert [i["product_id"] for i in data["due"]] == ["5012294", "5027015"]
    assert data["date"] == "2026-09-29" and data["to_review"] == 2
    assert offers.call_count == 1
    # The basket's own slot needs no delivery-days lookup (there is no route for one).
    code, out, _ = run(capsys, "restock", "--text", "--exclude", "Grønt", "--slot", "2403209")
    assert code == 0 and out.startswith("due for tirs. 29/09 kl. 11-13 (add):")
    assert offers.calls.last.request.url.params["timeslotId"] == "2403209"


def test_restock_text_rows():
    item = {"name": "Toiletpapir", "description": "8 rl. / Lambi", "quantity": 2, "last": "2026-09-21"}
    result = cli.restock.Restock(
        date="2026-10-02",
        due=[
            cli.restock.RestockItem(
                product_id="5019859", name="Letmælk 1,5%", quantity=3, p=0.8, last="2026-09-25", every=7
            )
        ],
        maybe=[
            cli.restock.RestockItem(product_id="5012806", p=0.41, every=16, **item),
            cli.restock.RestockItem(product_id="5602297", p=0.18, offer="2 for 70 kr, -20%", **item),
        ],
        in_basket=3,
    )
    assert cli.to_text(result).splitlines() == [
        "due for 2026-10-02 (add):",
        "  5019859  Letmælk 1,5%  x3  80%  every ~7 d, last 25/09",
        "maybe (pick by letter):",
        "  a  5012806  Toiletpapir (8 rl. / Lambi)  x2  41%  every ~16 d, last 21/09",
        "  b  5602297  Toiletpapir (8 rl. / Lambi)  x2  18%  last 21/09  offer: 2 for 70 kr, -20%",
        "already in the basket: 3 due or maybe",
    ]


def test_restock_groups_review_and_merge(api, history, capsys, tmp_path):
    run(capsys, "orders", "sync")
    _, out, _ = run(capsys, "restock", "groups", "--text")
    assert out.splitlines() == [
        "to review: 2 groups, 2 products",
        "  blomkål  x2  Grønt  5012294",
        "  java colombia  x2  Drikke  5027015",
    ]
    _, out, _ = run(capsys, "restock", "groups", "merge", "Kaffe", "Java Colombia", "--text")
    assert out.splitlines() == ["group: kaffe", "members: java colombia"]
    _, out, _ = run(capsys, "restock", "groups", "reviewed", "--text")
    assert out.strip() == "reviewed: 2"
    _, out, _ = run(capsys, "restock", "groups", "--text")
    assert out.splitlines() == ["named groups: kaffe", "to review: 0 groups, 0 products"]
    saved = json.loads((tmp_path / "groups.json").read_text(encoding="utf-8"))
    assert saved == {"groups": {"kaffe": ["java colombia"]}, "reviewed": ["5012294", "5027015"]}


def test_restock_backtest(api, history, capsys):
    run(capsys, "orders", "sync")
    code, out, _ = run(capsys, "restock", "backtest", "--last", "1", "--text")
    assert code == 0
    lines = out.splitlines()
    assert lines[0].startswith("1 orders, each predicted from the ones before it. 100% of their groups")
    assert lines[1].split() == ["method", "items", "precision", "recall"]
    assert [line.split()[0] for line in lines[2:6]] == ["due", "due", "rate,", "stopgap"]


def test_status_anonymous(api, anonymous, capsys):
    code, out, _ = run(capsys, "status")
    assert code == 0
    assert json.loads(out) == {"logged_in": False, "has_credentials": False}


def test_credentials_from_env_file(api, capsys, tmp_path):
    api.get(f"{WWW}/webapi/Token").respond(json=token_body())
    env = tmp_path / "creds.env"
    env.write_text("NEMLIG_USER=a@example.com\nNEMLIG_PASS=secret\n", encoding="utf-8")
    code, out, _ = run(capsys, "--env-file", str(env), "status")
    assert code == 0
    assert json.loads(out)["has_credentials"] is True
