"""Link the repo's agent skills into Claude Code's and Codex's user skill folders, for `nemlig setup`.

The skills live in ``.claude/skills/`` in the repo, where Claude Code finds them inside a clone.
Linking them into the user folders lets both agents use them from any directory, and a ``git
pull`` updates them in place. They are not in the wheel, so this needs the cloned repo.
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


def skills_target(agent: str) -> Path:
    """The agent's user skill folder. Codex reads ``~/.agents/skills``, not its own home."""
    if agent == "claude":
        return agent_home("claude") / "skills"
    return Path.home() / ".agents" / "skills"


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


def install(agent: str, source: Path | None = None, target: Path | None = None) -> Linked:
    source = source or SKILLS_DIR
    target = target or skills_target(agent)
    out = Linked(agent=agent, dir=str(target))
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


def remove(agent: str, source: Path | None = None, target: Path | None = None) -> Linked:
    """Remove the links into ``source``, also ones whose skill was renamed since."""
    source = source or SKILLS_DIR
    target = target or skills_target(agent)
    out = Linked(agent=agent, dir=str(target))
    if target.is_dir():
        for dst in sorted(target.iterdir()):
            if _ours(dst, source):
                _unlink(dst)
                out.removed.append(dst.name)
    return out
