#!/usr/bin/env python3
"""Render a recipe page from its JSON: ``uv run python render.py recipes.json page.html``.

example.json shows the shape. template.html holds the design; this only fills it in, escaping
every text, so the skill writes content and never HTML.
"""

import json
import re
import sys
from html import escape
from pathlib import Path

TEMPLATE = Path(__file__).with_name("template.html")
TAGS = {
    "fish": "Fish",
    "poultry": "Poultry",
    "beef": "Beef",
    "pork": "Pork",
    "lamb": "Lamb",
    "veg": "Vegetarian",
}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _ingredients(night_id: str, prefix: str, rows: list) -> str:
    """Rows are ``[amount, item]`` or ``[amount, item, pack]``."""
    out = []
    for n, row in enumerate(rows, 1):
        amount, item, pack = (list(row) + [""])[:3]
        note = f'<span class="pack">{escape(pack)}</span>' if pack else ""
        out.append(
            f'<li><label><input type="checkbox" id="{night_id}-{prefix}{n}">'
            f'<span class="amt">{escape(amount)}</span>'
            f'<span class="item">{escape(item)}{note}</span></label></li>'
        )
    return "\n".join(out)


def _night(night: dict, night_id: str) -> str:
    kind = night["kind"] if night.get("kind") in TAGS else "veg"
    tag = night.get("tag") or TAGS[kind]
    en = f'<p class="en">{escape(night["en"])}</p>' if night.get("en") else ""
    steps = "\n".join(
        f'<li><label><input type="checkbox" id="{night_id}-s{n}"><span class="badge"></span>'
        f'<span class="step-text">{escape(step)}</span></label></li>'
        for n, step in enumerate(night["steps"], 1)
    )
    notes = "\n".join(
        f'<p class="note"><b>{escape(label)}</b>{escape(text)}</p>' for label, text in night.get("notes", [])
    )
    home = ""
    if night.get("home"):
        home = (
            '<h3>At home</h3>\n<ul class="ingredients">\n'
            + _ingredients(night_id, "h", night["home"])
            + "\n</ul>"
        )
    return f"""
<article class="night {kind}" id="{night_id}">
<div class="night-head">
<span class="eyebrow"><span class="dot"></span>{escape(night["day"])} · {escape(tag)}</span>
<h2>{escape(night["name"])}</h2>
{en}
<ul class="meta">
<li><span>Time</span><span>{escape(night["time"])}</span></li>
<li><span>Serves</span><span>{escape(str(night["serves"]))}</span></li>
<li><span>Cost</span><span class="num">{escape(night["cost"])}</span></li>
</ul>
</div>
<div class="cols">
<section>
<h3>From the basket</h3>
<ul class="ingredients group">
{_ingredients(night_id, "i", night["basket"])}
</ul>
{home}
</section>
<section>
<h3>Method</h3>
<ol class="steps">
{steps}
</ol>
</section>
</div>
{f'<div class="notes">{notes}</div>' if notes else ""}
</article>"""


def render(data: dict) -> str:
    ids: list[str] = []
    for i, night in enumerate(data["nights"], 1):
        base = _slug(night["day"].split()[0]) or f"n{i}"
        ids.append(base if base not in ids else f"{base}-{i}")

    facts = "\n".join(f"<li><b>{escape(value)}</b> {escape(label)}</li>" for value, label in data["facts"])
    nav = "\n".join(
        f'<a href="#{night_id}" class="{night.get("kind", "veg")}"><span class="dot"></span>'
        f"{escape(night['day'].split()[0])} · {escape(night['short'])}</a>"
        for night_id, night in zip(ids, data["nights"], strict=True)
    )
    content = f"""<header>
<span class="eyebrow">{escape(data["eyebrow"])}</span>
<h1>{escape(data["title"])}</h1>
<p class="lede">{escape(data["lede"])}</p>
<ul class="facts">
{facts}
</ul>
</header>
<nav class="nights" aria-label="Nights">
{nav}
</nav>""" + "".join(_night(night, night_id) for night_id, night in zip(ids, data["nights"], strict=True))

    page = TEMPLATE.read_text(encoding="utf-8")
    return (
        page.replace("{{TITLE}}", escape(data["title"]))
        .replace("{{KEY}}", "recipes-" + _slug(data["title"]))
        .replace("{{CONTENT}}", content)
    )


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: render.py recipes.json page.html", file=sys.stderr)
        return 2
    data = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    try:
        page = render(data)
    except (KeyError, TypeError, ValueError) as exc:
        print(f"error: {argv[1]} is missing or misshapes {exc} (see example.json)", file=sys.stderr)
        return 2
    Path(argv[2]).write_text(page, encoding="utf-8")
    print(f"{argv[2]}: {len(data['nights'])} nights")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
