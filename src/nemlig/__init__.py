"""Unofficial client for nemlig.com: search products and manage the basket. No checkout."""

from ._version import __version__
from .client import NemligClient
from .errors import ApiError, AuthError, NemligError, NotLoggedInError, QueueItError
from .models import *  # noqa: F403
from .models import __all__ as _models_all
from .order_cache import OrderCache

__all__ = [
    "__version__",
    "ApiError",
    "AuthError",
    "NemligClient",
    "NemligError",
    "NotLoggedInError",
    "OrderCache",
    "QueueItError",
    *_models_all,
]
