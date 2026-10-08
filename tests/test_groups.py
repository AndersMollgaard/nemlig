from pathlib import Path

import pytest

from nemlig import groups as g
from nemlig.groups import Groups, GroupsError, auto_key


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Rosiner øko.", "rosiner"),
        ("Rosiner", "rosiner"),
        ("Økologisk Letmælk 1,5%", "letmælk 1,5%"),
        ("Mørk chokolade 70% øko.", "mørk chokolade 70%"),
        ("Økomælk", "økomælk"),
        ("  Agurk   dansk ", "agurk dansk"),
    ],
)
def test_auto_key(name, key):
    assert auto_key(name) == key


def test_key_prefers_an_id_member_over_a_name_member():
    groups = Groups(groups={"rugbrød": ["solsikkerugbrød", "5032497"], "sandwich": ["5012678"]})
    assert groups.key("5035265", "Solsikkerugbrød") == "rugbrød"
    assert groups.key("5012678", "Solsikkerugbrød") == "sandwich"
    assert groups.key("5032497", "Rugbrød m. kerner") == "rugbrød"
    assert groups.key("1", "Banan") == "banan"


def test_merge_moves_members_and_folds_named_groups_in():
    groups = Groups(groups={"rugbrød": ["solsikkerugbrød"], "brød": ["5012678", "toastbrød"]})
    assert groups.merge("Rugbrød", ["Rugbrød m. solsikke øko.", "5012678"]) == [
        "solsikkerugbrød",
        "rugbrød m. solsikke",
        "5012678",
    ]
    assert groups.groups["brød"] == ["toastbrød"]
    groups.merge("rugbrød", ["brød"])
    assert groups.groups == {
        "rugbrød": ["solsikkerugbrød", "rugbrød m. solsikke", "5012678", "brød", "toastbrød"]
    }


def test_mark_reviewed_counts_only_new_ids():
    groups = Groups(reviewed=["1"])
    assert groups.mark_reviewed(["1", "2", "2", "3"]) == 2
    assert groups.reviewed == ["1", "2", "3"]


def test_file_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("NEMLIG_GROUPS_FILE", str(tmp_path / "g.json"))
    path = g.default_groups_file()
    assert g.load(path) == Groups()
    groups = Groups()
    groups.merge("æg", ["frilandsæg str. s/m/l", "skrabeæg str. m/l"])
    g.save(path, groups)
    assert g.load(path) == groups
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(GroupsError):
        g.load(path)


def test_default_file_is_in_the_repo_root(monkeypatch):
    monkeypatch.delenv("NEMLIG_GROUPS_FILE", raising=False)
    monkeypatch.delenv("NEMLIG_HOME")
    assert g.default_groups_file() == Path(__file__).resolve().parents[1] / "groups.json"
