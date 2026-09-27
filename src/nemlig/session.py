"""Persist the www.nemlig.com cookie jar between runs. The password is never stored."""

from __future__ import annotations

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


class SessionStore:
    """Reads and writes the cookie jar as JSON, readable only by the owner (mode 600)."""

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path).expanduser() if path is not None else default_session_file()

    def load(self, jar: CookieJar) -> bool:
        """Add saved cookies to ``jar``. Returns False when there is no usable session file."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return False
        for c in data.get("cookies", []):
            jar.set_cookie(_make_cookie(c))
        return True

    def save(self, jar: CookieJar) -> None:
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
            json.dump({"version": 1, "cookies": cookies}, f, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)


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
