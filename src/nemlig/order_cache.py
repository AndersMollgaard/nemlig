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

from pydantic import Field

from .models import Order, OrderSummary
from .models._base import Model

if TYPE_CHECKING:
    from .client import NemligClient

DELIVERED = 3
"""Status of every order in a 136-order history, including one due later the same day, so it
doesn't prove delivery on its own; see `is_finished`."""
SYNC_BATCH = 16
"""Orders fetched between writes, so a failed sync keeps what it already fetched."""
FORMAT = 2
"""Version of the cached `Order` files. A sync refetches every order when the account folder's
``format`` file is older, so new fields reach old orders. 2 added `OrderLine.category`."""


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
    upcoming_ids: list[int] = Field(default=[], exclude=True)
    """Unfinished orders whose delivery hasn't ended, e.g. to count an order on its way as
    bought. Left out of the output."""
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

    def is_current(self, account: str) -> bool:
        """Whether the cached files are in the current `FORMAT`."""
        try:
            return int((self.path(account) / "format").read_text(encoding="utf-8")) >= FORMAT
        except (OSError, ValueError):
            return False

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
        """Fetch the finished orders that aren't cached yet, in parallel, and store them.

        Every finished order is fetched again when the cache is in an older `FORMAT`.
        """
        account = nc.account_key()
        history = nc.get_all_orders()
        finished = [o for o in history if is_finished(o, now)]
        upcoming = [
            o.id
            for o in history
            if not is_finished(o, now)
            and (o.delivery_end is None or o.delivery_end >= (now or datetime.now(o.delivery_end.tzinfo)))
        ]
        have = self.ids(account) if self.is_current(account) else set()
        todo = [o.id for o in finished if o.id not in have]
        for start in range(0, len(todo), SYNC_BATCH):
            for order in nc.get_orders_many(todo[start : start + SYNC_BATCH]):
                self.save(account, order)
        if not self.is_current(account):
            folder = self.path(account)
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            (folder / "format").write_text(str(FORMAT), encoding="utf-8")
        cached = [o for o in finished if o.id in have or o.id in todo]
        dates = [o.delivery_start.date() for o in cached if o.delivery_start]
        return SyncResult(
            path=str(self.path(account)),
            orders=len(history),
            cached=len(self.ids(account)),
            fetched=len(todo),
            pending=len(history) - len(finished),
            upcoming_ids=upcoming,
            first=min(dates, default=None),
            last=max(dates, default=None),
        )
