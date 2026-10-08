"""Link the repo's agent skills where Claude Code and Codex find them, for `nemlig setup`.

The skills live in ``.claude/skills/`` in the repo, where Claude Code finds them inside a clone.
Codex reads ``.agents/skills/``, so by default that gets a link per skill, and both agents load
the skills only when started in the repo. ``user`` links them into the user's own skill folders
instead, which every session of the agent loads. A ``git pull`` updates the skills in place.
They are not in the wheel, so this needs the cloned repo.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic import BaseModel

SKILLS_DIR = Path(__file__).resolve().parents[2] / ".claude" / "skills"
AGENTS = ("claude", "codex")


def agent_home(agent: str) -> Path:
    """Where the agent keeps its settings, to tell whether it is installed."""
    if agent == "claude":
        return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def skills_target(agent: str, user: bool = False, source: Path | None = None) -> Path:
    """The agent's skill folder in the repo, or with ``user`` its user skill folder. Codex reads
    ``.agents/skills`` in both, not its own home."""
    if user:
        return agent_home("claude") / "skills" if agent == "claude" else Path.home() / ".agents" / "skills"
    repo = (source or SKILLS_DIR).parents[1]
    return repo / (".claude" if agent == "claude" else ".agents") / "skills"


def detect_agents() -> list[str]:
    """The agents whose home exists, or Claude when neither does."""
    return [a for a in AGENTS if agent_home(a).is_dir()] or ["claude"]


class Linked(BaseModel):
    agent: str
    dir: str
    linked: list[str] = []
    already: list[str] = []
    removed: list[str] = []
    skipped: list[str] = []  # something else is there, left alone


def skill_names(source: Path | None = None) -> list[str]:
    return sorted(p.parent.name for p in (source or SKILLS_DIR).glob("*/SKILL.md"))


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _ours(path: Path, source: Path) -> bool:
    return _is_link(path) and path.resolve().parent == source.resolve()


def _link(src: Path, dst: Path) -> None:
    try:
        os.symlink(src, dst, target_is_directory=True)
    except OSError:
        # Windows allows symlinks only in Developer Mode; a junction needs no privilege.
        if sys.platform != "win32":
            raise
        import _winapi

        _winapi.CreateJunction(str(src), str(dst))


def _unlink(path: Path) -> None:
    # A directory symlink or junction on Windows is removed like a directory.
    if sys.platform == "win32":
        os.rmdir(path)
    else:
        path.unlink()


def install(agent: str, source: Path | None = None, target: Path | None = None, user: bool = False) -> Linked:
    source = source or SKILLS_DIR
    target = target or skills_target(agent, user, source)
    out = Linked(agent=agent, dir=str(target))
    if target == source:  # Claude Code in the repo reads the skills where they are
        out.already = skill_names(source)
        return out
    target.mkdir(parents=True, exist_ok=True)
    for name in skill_names(source):
        dst = target / name
        if _is_link(dst) and dst.resolve() == (source / name).resolve():
            out.already.append(name)
        elif dst.exists() or _is_link(dst):
            out.skipped.append(name)
        else:
            _link(source / name, dst)
            out.linked.append(name)
    return out


def remove(agent: str, source: Path | None = None, target: Path | None = None, user: bool = False) -> Linked:
    """Remove the links into ``source``, also ones whose skill was renamed since."""
    source = source or SKILLS_DIR
    target = target or skills_target(agent, user, source)
    out = Linked(agent=agent, dir=str(target))
    if target != source and target.is_dir():
        for dst in sorted(target.iterdir()):
            if _ours(dst, source):
                _unlink(dst)
                out.removed.append(dst.name)
    return out
