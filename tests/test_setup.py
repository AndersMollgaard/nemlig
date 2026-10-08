import json

import pytest

from nemlig import agent_skills, cli


@pytest.fixture
def source(tmp_path):
    src = tmp_path / "repo" / ".claude" / "skills"
    for name in ("nemlig-shopping", "nemlig-cheaper"):
        (src / name).mkdir(parents=True)
        (src / name / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
    (src / "notes").mkdir()  # no SKILL.md, not a skill
    return src


@pytest.fixture
def home(tmp_path, monkeypatch, source):
    home = tmp_path / "home"
    home.mkdir()
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(home))
    for name in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "NEMLIG_USER", "NEMLIG_PASS", "NEMLIG_ENV_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(agent_skills, "SKILLS_DIR", source)
    return home


def test_install_links_each_skill_and_is_safe_to_repeat(source, tmp_path):
    target = tmp_path / "skills"
    first = agent_skills.install("claude", source, target)
    assert first.linked == ["nemlig-cheaper", "nemlig-shopping"]
    assert (target / "nemlig-shopping" / "SKILL.md").is_file()
    again = agent_skills.install("claude", source, target)
    assert again.linked == [] and again.already == ["nemlig-cheaper", "nemlig-shopping"]


def test_install_leaves_other_folders_alone(source, tmp_path):
    target = tmp_path / "skills"
    (target / "nemlig-cheaper").mkdir(parents=True)
    out = agent_skills.install("claude", source, target)
    assert out.skipped == ["nemlig-cheaper"] and out.linked == ["nemlig-shopping"]
    assert not agent_skills._is_link(target / "nemlig-cheaper")


def test_remove_only_removes_links_into_the_repo(source, tmp_path):
    target = tmp_path / "skills"
    agent_skills.install("claude", source, target)
    (target / "other").mkdir()
    (source / "nemlig-cheaper" / "SKILL.md").unlink()
    (source / "nemlig-cheaper").rmdir()  # renamed since: a dangling link
    out = agent_skills.remove("claude", source, target)
    assert out.removed == ["nemlig-cheaper", "nemlig-shopping"]
    assert [p.name for p in target.iterdir()] == ["other"]


def test_detect_agents(home):
    assert agent_skills.detect_agents() == ["claude"]
    (home / ".codex").mkdir()
    assert agent_skills.detect_agents() == ["codex"]
    (home / ".claude").mkdir()
    assert agent_skills.detect_agents() == ["claude", "codex"]


def test_setup_links_for_both_agents_and_creates_preferences(home, capsys, tmp_path):
    (tmp_path / "repo" / "preferences.example.toml").write_text('diet = "x"\n', encoding="utf-8")
    code = cli.main(["--no-session", "setup", "--agent", "claude", "--agent", "codex"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["credentials"] is False and out["prefs"] == "created"
    assert (tmp_path / "preferences.toml").read_text(encoding="utf-8") == 'diet = "x"\n'
    assert [a["agent"] for a in out["agents"]] == ["claude", "codex"]
    assert (home / ".claude" / "skills" / "nemlig-shopping" / "SKILL.md").is_file()
    assert (home / ".agents" / "skills" / "nemlig-shopping" / "SKILL.md").is_file()

    code = cli.main(["--no-session", "--text", "setup", "--agent", "codex"])
    text = capsys.readouterr().out
    assert "credentials: missing; put NEMLIG_USER and NEMLIG_PASS in" in text
    assert "preferences: exists" in text
    assert "codex " in text and ": 2 already linked" in text

    code = cli.main(["--no-session", "--text", "setup", "--agent", "codex", "--remove"])
    assert code == 0
    assert "removed nemlig-cheaper, nemlig-shopping" in capsys.readouterr().out
    assert not (home / ".agents" / "skills" / "nemlig-shopping").exists()


def test_setup_without_the_repo_says_to_clone_it(home, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(agent_skills, "SKILLS_DIR", tmp_path / "nowhere")
    assert cli.main(["--no-session", "setup"]) == cli.EXIT_USAGE
    assert "Clone the repo" in capsys.readouterr().err
