import pytest

from nemlig.preferences import Preferences, PreferencesError, Rule, add_rule, load


@pytest.mark.parametrize(
    ("rule", "matches"),
    [
        (Rule(id="1"), True),
        (Rule(id="2"), False),
        (Rule(brand="first price"), True),
        (Rule(brand="First"), False),  # brands match whole
        (Rule(name="TOILET"), True),  # names match in part
        (Rule(brand="First Price", name="køkkenrulle"), False),  # every field must match
        (Rule(note="only a note"), False),
    ],
)
def test_rule_matches(rule, matches):
    assert rule.matches("1", "Toiletpapir", "First Price") is matches


def test_missing_file_is_empty(tmp_path):
    assert load(tmp_path / "nope.toml") == Preferences()


def test_add_rule_round_trips(tmp_path):
    path = tmp_path / "sub" / "preferences.toml"
    add_rule(path, "keep", Rule(brand="Peter Larsen Kaffe"))
    prefs = add_rule(path, "avoid", Rule(name='"øko" æg', note="line\nbreak"))
    assert prefs.keep == [Rule(brand="Peter Larsen Kaffe")]
    assert prefs.avoid == [Rule(name='"øko" æg', note="line\nbreak")]
    assert prefs.kept_by("9", "Java Colombia", "peter larsen kaffe") == Rule(brand="Peter Larsen Kaffe")


def test_add_rule_keeps_free_text(tmp_path):
    path = tmp_path / "preferences.toml"
    path.write_text('diet = "No pork."')  # no trailing newline
    prefs = add_rule(path, "avoid", Rule(id="1"))
    assert prefs.diet == "No pork." and prefs.avoid == [Rule(id="1")]


@pytest.mark.parametrize("text", ["diet = ", 'dieet = "typo"', "[[keep]]\nbrnad = 'x'"])
def test_bad_file(tmp_path, text):
    path = tmp_path / "preferences.toml"
    path.write_text(text)
    with pytest.raises(PreferencesError, match="preferences.toml"):
        load(path)
    with pytest.raises(PreferencesError):
        add_rule(path, "keep", Rule(id="1"))
    assert path.read_text() == text  # nothing appended to a broken file


def test_rule_needs_a_field(tmp_path):
    with pytest.raises(PreferencesError):
        add_rule(tmp_path / "p.toml", "keep", Rule(note="x"))
