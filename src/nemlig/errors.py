"""Exceptions raised by the nemlig client."""

from __future__ import annotations


class NemligError(Exception):
    """Base class for every error this package raises."""


class ApiError(NemligError):
    """An HTTP error from nemlig.com, usually the `/webapi` error envelope.

    The envelope looks like ``{"ErrorCode": 8, "ErrorMessage": "...", "DeveloperMessage": "..."}``
    and comes with HTTP 400. ``error_code`` is ``None`` when the body was not an envelope.
    """

    def __init__(
        self,
        status: int,
        message: str,
        *,
        error_code: int | None = None,
        developer_message: str | None = None,
        url: str | None = None,
    ) -> None:
        self.status = status
        self.message = message
        self.error_code = error_code
        self.developer_message = developer_message
        self.url = url
        code = f" (ErrorCode {error_code})" if error_code is not None else ""
        super().__init__(f"HTTP {status}{code}: {message}")


class AuthError(NemligError):
    """Login was rejected, for example because of a wrong username or password."""


class NotLoggedInError(NemligError):
    """The call needs a logged-in account, and there is no valid session or credentials to log in."""


class QueueItError(NemligError):
    """nemlig.com redirected to its Queue-it waiting room instead of answering."""
