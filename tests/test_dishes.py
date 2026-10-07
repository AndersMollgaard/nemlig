import io
import json

import pytest
from conftest import GW, WWW, fixture, token_body

from nemlig import cli, dishes, product_cache
from nemlig.models import Product

PRODUCTS = {
    "100": Product(id="100", name="Hel kylling", description="1,35 kg / Danpo", price=65.95, discount=29),
    "200": Product(id="200", name="Culottesteg", description="1,6 kg", price=280.0, offer="2 for 500 kr"),
    "1": Product(id="1", name="Kartofler øko.", description="1 kg / Coop", price=15.0),
    "2": Product(id="2", name="Citron", description="1 stk.", price=5.0),
    "3": Product(id="3", name="Kokosmælk", description="400 ml", price=12.0, offer="3 for 30 kr"),
}

SPEC = """\
portions 3   # 2 adults, 2 children
anchor 1 100:1 nights 1
1a* Ovnstegt kylling med citron | 60 min | 1:2 2:1 | Danish, oven
1b Kylling tikka masala | 35 min | 3:3 | Indian, pot; ris at home
anchor 2 200:1 nights 2
2a* Culotte med rodfrugter | 90 min | 1:1 | Weekend, oven
2b* Steaksandwich | 15 min | 2:1 | Leftovers from 2a
anchor V nights 1 | Vegetarian
Va Linsesuppe | 40 min | - | Middle Eastern, pot
"""


def test_parse():
    plan = dishes.parse(SPEC)
    assert plan.portions == 3
    assert [(a.key, a.item, a.nights, a.title) for a in plan.anchors] == [
        ("1", ("100", 1), 1, None),
        ("2", ("200", 1), 2, None),
        ("V", None, 1, "Vegetarian"),
    ]
    assert [(d.code, d.star, d.items) for _, d in plan.dishes()][:2] == [
        ("1a", True, [("1", 2), ("2", 1)]),
        ("1b", False, [("3", 3)]),
    ]


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ("anchor 1 100\n1a x | 1 min | 1 | n", "portions"),
        ("portions 2\n1a x | 1 min | 1 | n", "before any anchor"),
        ("portions 2\nanchor 1 100\n1a x | 1 min | 1", "line 3"),
        ("portions 2\nanchor 1 100 3\n", "nights N"),
        ("portions 2\nanchor V\n", "needs a title"),
        ("portions 2\nanchor 1 100\n1a x | 1 | 1 | n\n1a y | 1 | 2 | n", "used twice"),
        ("portions 2\nanchor 1 100\n1a x | 1 | 1:two | n", "ID:QTY"),
    ],
)
def test_parse_errors(spec, message):
    with pytest.raises(dishes.SpecError, match=message):
        dishes.parse(spec)


def test_render_prices_the_tables_and_the_star_set():
    priced = dishes.render(dishes.parse(SPEC), PRODUCTS)
    blocks = priced.tables.split("\n\n")
    head, _, _, row_1a, row_1b = blocks[0].splitlines()
    assert head == "**1. Hel kylling 1,35 kg, 65.95 kr (-29%): pick 1**"
    # 1a: 2 x kartofler 30 + citron 5 = 35; (65.95 + 35) / 3 = 33.65
    assert row_1a == (
        "| 1a ★ | Ovnstegt kylling med citron | 60 min | 2 x Kartofler øko. 1 kg, Citron | 35 kr | 34 kr "
        "| Danish, oven |"
    )
    # 3 kokosmælk hit the 3 for 30 kr offer
    assert "| 3 x Kokosmælk 400 ml | 30 kr | 32 kr |" in row_1b
    assert (
        blocks[1].splitlines()[0] == "**2. Culottesteg 1,6 kg, 280.00 kr, offer 2 for 500 kr: pick up to 2**"
    )
    # 2b: 280 / 2 nights + 5 = 145; / 3 = 48.33
    assert blocks[1].splitlines()[-1].split(" | ")[5] == "48 kr"
    assert blocks[2].splitlines()[0] == "**V. Vegetarian: pick 1**"
    assert "| Va | Linsesuppe | 40 min | - | 0 kr | 0 kr |" in blocks[2]

    assert priced.star_codes == ["1a", "2a", "2b"]
    # Anchors 65.95 + 280; kartofler at the larger 2, citron shared by 1a and 2b bought once.
    assert (priced.star_anchors, priced.star_extras, priced.star_total) == (345.95, 35.0, 380.95)
    assert priced.shared == ["Kartofler øko. (1a, 2a)", "Citron (1a, 2b)"]
    assert priced.warnings == []
    out = dishes.text(priced)
    assert "★ set (1a, 2a, 2b): 380.95 kr (anchors 345.95 kr + extras 35.00 kr)" in out


def test_render_warns_when_an_anchor_has_too_many_stars():
    spec = SPEC.replace("1b Kylling", "1b* Kylling")
    assert dishes.render(dishes.parse(spec), PRODUCTS).warnings == [
        "2 ★ dishes on anchor 1, which covers 1 night"
    ]


def test_render_needs_every_price():
    with pytest.raises(dishes.SpecError, match="no price for 1, 2: search for them first"):
        dishes.render(dishes.parse(SPEC), {k: v for k, v in PRODUCTS.items() if k not in "12"})


def test_picks_add_anchors_and_extras_once():
    items, costs = dishes.picks(dishes.parse(SPEC), ["1B", "2a", "2b"], PRODUCTS)
    assert items == [("100", 1), ("200", 1), ("3", 3), ("1", 1), ("2", 1)]
    assert [(c.code, c.cost, c.items) for c in costs] == [
        ("1b", 95.95, ["3:3"]),
        ("2a", 155.0, ["1:1"]),
        ("2b", 145.0, ["2:1"]),
    ]
    with pytest.raises(dishes.SpecError, match="no dish 9z"):
        dishes.picks(dishes.parse(SPEC), ["9z"], PRODUCTS)


def test_product_cache_keeps_recent_prices(tmp_path):
    path = tmp_path / "products.json"
    product_cache.save([PRODUCTS["1"]], path, now=1000.0)
    product_cache.save([PRODUCTS["2"]], path, now=1000.0 + product_cache.MAX_AGE - 1)
    assert set(product_cache.load(path, now=1000.0 + product_cache.MAX_AGE - 1)) == {"1", "2"}
    assert set(product_cache.load(path, now=1000.0 + product_cache.MAX_AGE)) == {"2"}


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    for name in ("NEMLIG_USER", "NEMLIG_PASS", "NEMLIG_ENV_FILE", "NEMLIG_PREFS_FILE", "NEMLIG_CACHE_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)


def test_cli_prices_what_search_printed_then_adds_the_picks(api, cli_env, monkeypatch, capsys):
    api.get(f"{WWW}/webapi/Token").respond(json=token_body(debitor="123"))
    api.get(f"{WWW}/webapi/basket/GetBasket").respond(json=fixture("basket.json"))
    api.get(f"{GW}/searchgateway/api/search").respond(json=fixture("search.json"))
    assert cli.main(["--no-session", "--text", "search", "havregryn"]) == 0
    capsys.readouterr()

    spec = "portions 2\nanchor V nights 1 | Vegetarian\nVa* Grød | 10 min | 5050406:2 | Danish, pot\n"
    monkeypatch.setattr("sys.stdin", io.StringIO(spec))
    assert cli.main(["--no-session", "--text", "dishes"]) == 0
    out = capsys.readouterr().out
    assert "| Va ★ | Grød | 10 min | 2 x Havregryn (finvalsede) øko. 1 kg |" in out

    add = api.post(f"{WWW}/webapi/basket/AddToBasket").respond(json=fixture("basket.json"))
    assert cli.main(["--no-session", "--text", "dishes", "add", "Va", "5034594:1"]) == 0
    out = capsys.readouterr().out
    assert [json.loads(c.request.content)["productId"] for c in add.calls] == ["5050406", "5034594"]
    assert out.splitlines()[0].startswith("Va Grød, ") and out.splitlines()[0].endswith(": 5050406:2")
    assert out.splitlines()[1] == "added: 2 lines, 7.95 kr"
