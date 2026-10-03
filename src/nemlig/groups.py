"""Which products meet the same need, so restock counts them as one ("rugbrød" in any brand).

A product's group is its name, lowercased and without the øko mark (`auto_key`), unless
``groups.json`` puts it in a named group. nemlig names are generic and the brand sits in the
description, so most brands and packs of one need already share a name. The file only records
what the names miss::

    {
      "groups": {"rugbrød": ["solsikkerugbrød", "rugbrød m. solsikkekerner", "5012678"]},
      "reviewed": ["5035265", "5012678"]
    }

A member is an auto key, which takes in every product with that name now and later, or a
product id, which wins over its name's group. ``reviewed`` lists the products already looked at,
so a review only shows new ones. The file maps products to needs and holds nothing about the
account.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, ConfigDict

_OKO = re.compile(r"\bøko(?:logisk|logiske)?\b\.?")


def auto_key(name: str) -> str:
    """``"Rosiner øko."`` and ``"Rosiner"`` both give ``"rosiner"``. Fat %, sizes and other words stay."""
    return " ".join(_OKO.sub(" ", name.casefold()).split())


def default_groups_file() -> Path:
    if os.environ.get("NEMLIG_GROUPS_FILE"):
        return Path(os.environ["NEMLIG_GROUPS_FILE"]).expanduser()
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "nemlig" / "groups.json"


class Groups(BaseModel):
    model_config = ConfigDict(extra="forbid")

    groups: dict[str, list[str]] = {}
    reviewed: list[str] = []

    def key(self, product_id: str, name: str) -> str:
        """The group of a product: its named group by id, then by name, else its auto key."""
        auto = auto_key(name)
        by_key = None
        for group, members in self.groups.items():
            if product_id in members:
                return group
            if by_key is None and auto in members:
                by_key = group
        return by_key or auto

    def merge(self, name: str, members: Iterable[str]) -> list[str]:
        """Put the members (auto keys or product ids) in group ``name``, moving them out of any
        other group. Returns the group's members."""
        name = auto_key(name)
        wanted = [m.strip() if m.strip().isdigit() else auto_key(m) for m in members]
        # A named group among the members brings its own members along.
        for member in list(wanted):
            if member != name and member in self.groups:
                wanted += self.groups.pop(member)
        wanted = [m for m in dict.fromkeys(wanted) if m and m != name]
        for group in list(self.groups):
            if group != name:
                self.groups[group] = [m for m in self.groups[group] if m not in wanted]
                if not self.groups[group]:
                    del self.groups[group]
        current = self.groups.get(name, [])
        self.groups[name] = current + [m for m in wanted if m not in current]
        return self.groups[name]

    def mark_reviewed(self, product_ids: Iterable[str]) -> int:
        """Add the ids to ``reviewed``. Returns how many were new."""
        seen = set(self.reviewed)
        new = [pid for pid in dict.fromkeys(product_ids) if pid not in seen]
        self.reviewed += new
        return len(new)


class GroupsError(ValueError):
    """The groups file is not valid JSON or has unknown fields."""


def load(path: str | os.PathLike[str]) -> Groups:
    """The groups in ``path``, or none if the file does not exist."""
    p = Path(path)
    if not p.is_file():
        return Groups()
    try:
        return Groups.model_validate_json(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise GroupsError(f"{p}: {exc}") from exc


def save(path: str | os.PathLike[str], groups: Groups) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp")
    tmp.write_text(groups.model_dump_json(indent=1) + "\n", encoding="utf-8")
    tmp.replace(p)
