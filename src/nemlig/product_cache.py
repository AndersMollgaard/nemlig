"""The products `search` and `offers` printed lately, so `dishes` can price a plan offline.

Stored as ``<cache dir>/products.json``: product id -> when it was seen and the `Product`. Prices
depend on the delivery slot and change daily, so entries older than `MAX_AGE` are dropped.
Products carry no personal data.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable
from pathlib import Path

from .models import Product
from .order_cache import default_cache_dir

MAX_AGE = 12 * 3600
"""Seconds a seen price stays usable."""


def default_file() -> Path:
    return default_cache_dir() / "products.json"


def _read(path: Path) -> dict[str, dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(products: Iterable[Product], path: Path | None = None, now: float | None = None) -> None:
    """Remember these products. A cache that can't be written is skipped: it only helps `dishes`."""
    path = path or default_file()
    now = time.time() if now is None else now
    entries = {k: v for k, v in _read(path).items() if now - v.get("seen", 0) < MAX_AGE}
    for p in products:
        product = p.model_dump(mode="json", exclude_none=True, exclude={"image", "slug", "swap", "avoided"})
        entries[p.id] = {"seen": now, "product": product}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def load(path: Path | None = None, now: float | None = None) -> dict[str, Product]:
    """The products seen within `MAX_AGE`, by id."""
    now = time.time() if now is None else now
    return {
        pid: Product.model_validate(v["product"])
        for pid, v in _read(path or default_file()).items()
        if now - v.get("seen", 0) < MAX_AGE and isinstance(v.get("product"), dict)
    }
