import json

import httpx
import pytest
from conftest import GW, WWW, fixture, token_body

from nemlig import cli

ERROR = fixture("error_copyorder_not_found.json")


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch, tmp_path):
    for name in ("NEMLIG_USER", "NEMLIG_PASS", "NEMLIG_ENV_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)  # no ./.env
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))  # no ~/.config/nemlig/.env


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
    assert "delivery_context" not in basket


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


def test_status_anonymous(api, anonymous, capsys):
    code, out, _ = run(capsys, "status")
    assert code == 0
    assert json.loads(out) == {"logged_in": False, "has_credentials": False}


def test_credentials_from_env_file(api, capsys, tmp_path):
    api.get(f"{WWW}/webapi/Token").respond(json=token_body())
    env = tmp_path / "creds.env"
    env.write_text("NEMLIG_USER=a@example.com\nNEMLIG_PASS=secret\n")
    code, out, _ = run(capsys, "--env-file", str(env), "status")
    assert code == 0
    assert json.loads(out)["has_credentials"] is True
