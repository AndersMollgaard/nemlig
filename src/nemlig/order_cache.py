"""A local copy of the order history, so later analysis doesn't refetch years of orders.

Finished orders don't change, so each is stored once as ``<root>/<account>/<order id>.json``,
where ``<account>`` is `NemligClient.account_key`. The files hold `Order` models, which carry no
personal data.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .models import Order, OrderSummary
from .models._base import Model

if TYPE_CHECKING:
    from .client import NemligClient

DELIVERED = 3
"""Status of every order in a 136-order history, including one due later the same day, so it
doesn't prove delivery on its own; see `is_finished`."""
SYNC_BATCH = 16
"""Orders fetched between writes, so a failed sync keeps what it already fetched."""


def default_cache_dir() -> Path:
    if os.environ.get("NEMLIG_CACHE_DIR"):
        return Path(os.environ["NEMLIG_CACHE_DIR"]).expanduser()
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "nemlig"


def is_finished(order: OrderSummary, now: datetime | None = None) -> bool:
    """Delivered and past its delivery window, so its lines won't change any more."""
    end = order.delivery_end
    if order.status != DELIVERED or order.is_editable or end is None:
        return False
    return end < (now or datetime.now(end.tzinfo))


class SyncResult(Model):
    path: str
    orders: int
    """Orders in the account's history."""
    cached: int
    """Orders in the cache after the sync."""
    fetched: int
    """Orders fetched and cached by this sync."""
    pending: int
    """Orders not finished yet, so not cached."""
    first: date | None = None
    last: date | None = None
    """Delivery dates of the oldest and newest cached order."""


class OrderCache:
    def __init__(self, root: str | os.PathLike[str] | None = None) -> None:
        self.root = Path(root).expanduser() if root is not None else default_cache_dir() / "orders"

    def path(self, account: str) -> Path:
        return self.root / account

    def ids(self, account: str) -> set[int]:
        return {int(p.stem) for p in self.path(account).glob("*.json") if p.stem.isdigit()}

    def load(self, account: str) -> list[Order]:
        """Every cached order of the account, newest first."""
        orders = [
            Order.model_validate_json(p.read_text(encoding="utf-8"))
            for p in self.path(account).glob("*.json")
            if p.stem.isdigit()
        ]
        return sorted(orders, key=lambda o: (o.delivery_start or datetime.min, o.id), reverse=True)

    def save(self, account: str, order: Order) -> None:
        folder = self.path(account)
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = folder / f".{order.id}.json.tmp"
        tmp.write_text(order.model_dump_json(), encoding="utf-8")
        tmp.replace(folder / f"{order.id}.json")

    def sync(self, nc: NemligClient, now: datetime | None = None) -> SyncResult:
        """Fetch the finished orders that aren't cached yet, in parallel, and store them."""
        account = nc.account_key()
        history = nc.get_all_orders()
        finished = [o for o in history if is_finished(o, now)]
        have = self.ids(account)
        todo = [o.id for o in finished if o.id not in have]
        for start in range(0, len(todo), SYNC_BATCH):
            for order in nc.get_orders_many(todo[start : start + SYNC_BATCH]):
                self.save(account, order)
        cached = [o for o in finished if o.id in have or o.id in todo]
        dates = [o.delivery_start.date() for o in cached if o.delivery_start]
        return SyncResult(
            path=str(self.path(account)),
            orders=len(history),
            cached=len(self.ids(account)),
            fetched=len(todo),
            pending=len(history) - len(finished),
            first=min(dates, default=None),
            last=max(dates, default=None),
        )
