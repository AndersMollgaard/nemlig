"""The skills, the README and docs/cli.md quote `nemlig` commands for agents to copy. Every one
must still parse, so a renamed command or flag breaks this test instead of a live run."""

import contextlib
import io
import re
import shlex
from pathlib import Path

import pytest

from nemlig.cli import build_parser

ROOT = Path(__file__).resolve().parent.parent
DOCS = sorted(ROOT.glob(".claude/skills/*/SKILL.md")) + [ROOT / "README.md", ROOT / "docs" / "cli.md"]

_INLINE = re.compile(r"`((?:uv run )?nemlig [^`]+)`")
# Placeholders the docs use: SLOT_ID, ID:QTY, OLD_ID, LIST_ID, Q1 ...
_DATE = re.compile(r"\b(?:YYYY-MM-DD|DAY)\b")
_CAPS = re.compile(r"\b[A-Z][A-Z0-9_]+\b")


def _commands(path: Path):
    """``(line number, command)`` for each command in a code block or an inline code span."""
    fenced = False
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            candidates = [line.split("  #")[0].split(" # ")[0]]
        else:
            candidates = _INLINE.findall(line)
        # A chain such as `prefs; basket` or `reserve ID && restock` is one command per part.
        candidates = [part for c in candidates for part in re.split(r";|&&", c)]
        for c in candidates:
            c = c.split("|")[0].split("<<")[0].replace("...", "").strip().removeprefix("uv run ")
            # Syntax summaries (ID[:QTY], <query>) are not commands.
            if c.startswith("nemlig ") and not any(s in c for s in ("[", "<")):
                yield n, c


def _argv(command: str) -> list[str]:
    command = _CAPS.sub("1", _DATE.sub("2026-10-02", command))
    return shlex.split(command)[1:]


CASES = [(path, n, c) for path in DOCS for n, c in _commands(path)]


def test_the_docs_quote_commands():
    assert len(CASES) > 40


@pytest.mark.parametrize(
    ("path", "line", "command"), CASES, ids=[f"{p.parent.name}:{n}" for p, n, _ in CASES]
)
def test_quoted_command_parses(path, line, command):
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            build_parser().parse_args(_argv(command))
    except SystemExit as exc:
        assert not exc.code, f"{path.relative_to(ROOT)}:{line}: {command}\n{out.getvalue()}"
