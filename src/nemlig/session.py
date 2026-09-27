"""Persist the www.nemlig.com cookie jar between runs. The password is never stored."""

from __future__ import annotations

import hashlib
import json
import os
from http.cookiejar import Cookie, CookieJar
from pathlib import Path


def default_session_file() -> Path:
    env = os.environ.get("NEMLIG_SESSION_FILE")
    if env:
        return Path(env).expanduser()
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "nemlig" / "session.json"


def user_key(username: str) -> str:
    """Identifies the account a session belongs to, without writing the e-mail address to disk."""
    return hashlib.sha256(username.strip().lower().encode()).hexdigest()


class SessionStore:
    """Reads and writes the cookie jar as JSON, readable only by the owner (mode 600).

    The file records which user it belongs to (``user_key``), so credentials for one account never
    pick up another account's saved cookies.
    """

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path).expanduser() if path is not None else default_session_file()
        self.user: str | None = None
        """The ``user_key`` of the last loaded session."""

    def load(self, jar: CookieJar, user: str | None = None) -> bool:
        """Add saved cookies to ``jar``. Returns False when there is no usable session file.

        With ``user``, a session saved for another user, or for no known user, is ignored.
        """
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if user is not None and data.get("user") != user:
                return False
            cookies = [_make_cookie(c) for c in data.get("cookies", [])]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return False
        for cookie in cookies:
            jar.set_cookie(cookie)
        self.user = data.get("user")
        return True

    def save(self, jar: CookieJar, user: str | None = None) -> None:
        cookies = [
            {
                "name": c.name,
                "value": c.value,
                "domain": c.domain,
                "path": c.path,
                "expires": c.expires,
                "secure": c.secure,
                "http_only": c.has_nonstandard_attr("HttpOnly"),
            }
            for c in jar
        ]
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "user": user, "cookies": cookies}, f, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)
        self.user = user

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)
        self.user = None


def _make_cookie(c: dict) -> Cookie:
    domain = c["domain"]
    return Cookie(
        version=0,
        name=c["name"],
        value=c["value"],
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=bool(domain),
        domain_initial_dot=domain.startswith("."),
        path=c.get("path") or "/",
        path_specified=True,
        secure=bool(c.get("secure")),
        expires=c.get("expires"),
        discard=c.get("expires") is None,
        comment=None,
        comment_url=None,
        rest={"HttpOnly": ""} if c.get("http_only") else {},
    )
