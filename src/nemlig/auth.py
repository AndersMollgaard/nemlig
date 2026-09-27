"""Login and the short-lived bearer JWT used by the search gateway and productbff."""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ._http import WWW, Http
from .errors import ApiError, AuthError

# Refresh this many seconds before the JWT's `exp`, so a token never expires mid-request.
REFRESH_MARGIN = 45


def decode_claims(jwt: str) -> dict[str, Any]:
    """Decode a JWT payload without verifying it (we only read our own token's claims)."""
    try:
        payload = jwt.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError) as exc:
        raise ValueError("not a JWT") from exc


@dataclass(frozen=True)
class Token:
    value: str
    claims: dict[str, Any]

    @classmethod
    def parse(cls, value: str) -> Token:
        return cls(value, decode_claims(value))

    @property
    def expires_at(self) -> float:
        return float(self.claims.get("exp", 0))

    @property
    def debitor_id(self) -> str | None:
        """The customer id claim. Present only when the token was minted with a logged-in cookie."""
        try:
            return self.claims["authorization"]["permissions"][0]["claims"]["debitorId"][0]
        except (KeyError, IndexError, TypeError):
            return None

    @property
    def is_customer(self) -> bool:
        return bool(self.debitor_id)


class TokenManager:
    """Mints JWTs from ``/webapi/Token`` (which reads the cookie jar) and caches them until near expiry."""

    def __init__(self, http: Http, *, clock: Callable[[], float] = time.time) -> None:
        self._http = http
        self._clock = clock
        self._token: Token | None = None

    def get(self) -> Token:
        if self._token is None or self._clock() >= self._token.expires_at - REFRESH_MARGIN:
            body = self._http.get(f"{WWW}/webapi/Token", headers={"Referer": f"{WWW}/"})
            self._token = Token.parse(body["access_token"])
        return self._token

    def invalidate(self) -> None:
        self._token = None


def login(http: Http, username: str, password: str) -> dict[str, Any]:
    """Log in over plain HTTP. On success the cookie jar holds ``.ASPXAUTH`` and the basket keys.

    Steps as the website does them: AntiForgery (sets the XSRF cookies), an anonymous token, then
    ``POST /webapi/login``. The caller should mint a fresh token afterwards.
    """
    http.get(f"{WWW}/webapi/AntiForgery")
    anon = Token.parse(http.get(f"{WWW}/webapi/Token")["access_token"])
    try:
        return (
            http.post(
                f"{WWW}/webapi/login",
                headers={"Authorization": f"Bearer {anon.value}", "Referer": f"{WWW}/login"},
                json={
                    "Username": username,
                    "Password": password,
                    "CheckForExistingProducts": True,
                    "DoMerge": True,
                    "AppInstalled": False,
                    "SaveExistingBasket": False,
                },
            )
            or {}
        )
    except ApiError as exc:
        # A wrong username or password is HTTP 400 with ErrorCode 4.
        if exc.status == 400:
            raise AuthError(exc.message) from exc
        raise
