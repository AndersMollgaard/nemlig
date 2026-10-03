"""The nemlig-recipes skill renders its page from JSON with a script next to SKILL.md."""

import importlib.util
import json
import re
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / ".claude/skills/nemlig-recipes"

_spec = importlib.util.spec_from_file_location("recipes_render", SKILL / "render.py")
render_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(render_module)


def _example() -> dict:
    return json.loads((SKILL / "example.json").read_text(encoding="utf-8"))


def test_renders_the_example():
    data = _example()
    page = render_module.render(data)
    assert "{{" not in page
    assert page.startswith("<title>Week 41 Dinners</title>")
    for night in data["nights"]:
        assert night["name"] in page
    assert 'href="#thu"' in page and 'id="thu"' in page
    assert 'data-key="recipes-week-41-dinners"' in page


def test_checkbox_ids_are_unique_and_stable():
    page = render_module.render(_example())
    ids = re.findall(r'type="checkbox" id="([^"]+)"', page)
    assert len(ids) == len(set(ids))
    assert "thu-i1" in ids and "sat-s6" in ids and "fri-h3" in ids


def test_escapes_text_and_dedupes_days():
    data = _example()
    data["nights"][1]["day"] = data["nights"][0]["day"]
    data["nights"][0]["steps"][0] = "Stir </script><b>well</b> & serve"
    page = render_module.render(data)
    assert "</script><b>" not in page
    assert "Stir &lt;/script&gt;&lt;b&gt;well&lt;/b&gt; &amp; serve" in page
    assert 'id="thu"' in page and 'id="thu-2"' in page


def test_cli_reports_a_missing_field(tmp_path, capsys):
    data = _example()
    del data["nights"][0]["steps"]
    src = tmp_path / "week.json"
    src.write_text(json.dumps(data), encoding="utf-8")
    assert render_module.main(["render.py", str(src), str(tmp_path / "week.html")]) == 2
    assert "steps" in capsys.readouterr().err
    assert not (tmp_path / "week.html").exists()
