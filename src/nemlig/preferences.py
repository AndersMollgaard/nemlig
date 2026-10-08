"""Household preferences: free text for the agent to judge, and rules the CLI enforces.

The file is TOML, ``preferences.toml`` in the repo root (`default_prefs_file`)::

    household = "2 adults, 1 child"
    diet = "No pork."
    always = "Øko milk and eggs."
    budget = "About 1200 kr a week."

    [[keep]]                  # never replace these basket lines
    brand = "Peter Larsen Kaffe"

    [[avoid]]                 # never suggest these as a replacement
    brand = "First Price"
    name = "toiletpapir"
    note = "too thin"

A rule matches a product when every field it sets matches: ``id`` exactly, ``brand`` ignoring
case, and ``name`` as a case-insensitive part of the product name.
"""

from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from ._paths import home_dir

RuleKind = Literal["keep", "avoid"]


def default_prefs_file() -> Path:
    if os.environ.get("NEMLIG_PREFS_FILE"):
        return Path(os.environ["NEMLIG_PREFS_FILE"]).expanduser()
    return home_dir() / "preferences.toml"


class Rule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str | None = None
    brand: str | None = None
    name: str | None = None
    note: str | None = None

    def matches(self, product_id: str, name: str, brand: str | None) -> bool:
        if self.id is None and self.brand is None and self.name is None:
            return False
        if self.id is not None and self.id != product_id:
            return False
        if self.brand is not None and self.brand.casefold() != (brand or "").casefold():
            return False
        return self.name is None or self.name.casefold() in name.casefold()

    def describe(self) -> str:
        parts = [f"{k} {v!r}" for k, v in (("id", self.id), ("brand", self.brand), ("name", self.name)) if v]
        return " ".join(parts) + (f" ({self.note})" if self.note else "")


class Preferences(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    household: str | None = None
    diet: str | None = None
    always: str | None = None
    budget: str | None = None
    keep: list[Rule] = []
    avoid: list[Rule] = []

    def kept_by(self, product_id: str, name: str, brand: str | None) -> Rule | None:
        return next((r for r in self.keep if r.matches(product_id, name, brand)), None)

    def avoided(self, product_id: str, name: str, brand: str | None) -> bool:
        return any(r.matches(product_id, name, brand) for r in self.avoid)


class PreferencesError(ValueError):
    """The preferences file is not valid TOML or has unknown fields."""


def load(path: str | os.PathLike[str]) -> Preferences:
    """The preferences in ``path``, or empty ones if the file does not exist."""
    p = Path(path)
    if not p.is_file():
        return Preferences()
    try:
        return Preferences.model_validate(tomllib.loads(p.read_text(encoding="utf-8")))
    except (tomllib.TOMLDecodeError, ValidationError) as exc:
        raise PreferencesError(f"{p}: {exc}") from exc


def add_rule(path: str | os.PathLike[str], kind: RuleKind, rule: Rule) -> Preferences:
    """Append a rule to the file, creating it if needed, and return the new preferences."""
    if rule.id is None and rule.brand is None and rule.name is None:
        raise PreferencesError("a rule needs at least one of id, brand or name")
    p = Path(path)
    current = p.read_text(encoding="utf-8") if p.is_file() else ""
    load(p)  # refuse to append to a broken file
    # A JSON string is a valid TOML basic string.
    values = rule.model_dump(exclude_none=True)
    fields = [f"{k} = {json.dumps(v, ensure_ascii=False)}" for k, v in values.items()]
    block = "\n".join([f"[[{kind}]]", *fields]) + "\n"
    sep = "" if not current else ("\n" if current.endswith("\n") else "\n\n")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(current + sep + block, encoding="utf-8")
    return load(p)
