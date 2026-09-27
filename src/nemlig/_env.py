"""Minimal `.env` reader, so the package needs no python-dotenv."""

from __future__ import annotations

import os
from pathlib import Path


def read_env_file(path: str | os.PathLike[str]) -> dict[str, str]:
    """Parse ``KEY=value`` lines. Blank lines and ``#`` comments are skipped, quotes stripped."""
    out: dict[str, str] = {}
    p = Path(path)
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        out[key] = value.strip().strip('"').strip("'")
    return out


def get_setting(name: str, env_file: str | os.PathLike[str] | None) -> str | None:
    """Real environment variables win over the `.env` file."""
    if os.environ.get(name):
        return os.environ[name]
    if env_file is not None:
        return read_env_file(env_file).get(name) or None
    return None
