"""Where the household's own files live: ``.env``, ``preferences.toml`` and ``groups.json``."""

from __future__ import annotations

import os
from pathlib import Path


def home_dir() -> Path:
    """The repo root, found from this file rather than the working directory, so the CLI reads
    the same files wherever it runs. ``NEMLIG_HOME`` overrides it. An install without the repo
    behind it falls back to ``~/.config/nemlig``."""
    if os.environ.get("NEMLIG_HOME"):
        return Path(os.environ["NEMLIG_HOME"]).expanduser()
    root = Path(__file__).resolve().parents[2]
    if (root / "pyproject.toml").is_file():
        return root
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "nemlig"
