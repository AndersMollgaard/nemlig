"""HTTP transport: one httpx.Client with nemlig's conventions, error mapping and a GET-only retry policy."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from ._version import __version__
from .errors import ApiError, QueueItError

WWW = "https://www.nemlig.com"
GW = "https://webapi.prod.knl.nemlig.it"

# A browser-like User-Agent on page routes gets redirected to Queue-it, so use a plain one.
USER_AGENT = f"nemlig-python/{__version__}"
RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
MAX_REDIRECTS = 3


class Http:
    """Wraps one `httpx.Client` that holds the www.nemlig.com cookie jar.

    Only GETs are retried. Basket writes are not idempotent (``addToExisting`` adds), so a POST
    that failed half-way must never be sent twice.
    """

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        retries: int = 3,
        backoff: float = 0.5,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*"},
            timeout=timeout,
            follow_redirects=False,
            transport=transport,
        )
        self.retries = retries
        self.backoff = backoff
        self._sleep = sleep

    @property
    def cookies(self) -> httpx.Cookies:
        return self.client.cookies

    def close(self) -> None:
        self.client.close()

    # -- public verbs -------------------------------------------------------------------------

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = False,
    ) -> Any:
        """GET and return the decoded JSON body (``None`` for an empty body)."""
        for attempt in range(self.retries + 1):
            last = attempt == self.retries
            try:
                resp = self._send("GET", url, params=params, headers=headers, follow=follow_redirects)
            except httpx.TransportError:
                if last:
                    raise
                delay = None
            else:
                if last or resp.status_code not in RETRY_STATUSES:
                    return self._decode(resp)
                delay = _retry_after(resp)
            self._sleep(delay if delay is not None else self.backoff * 2**attempt)
        raise AssertionError("unreachable")

    def post(
        self,
        url: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """POST once (never retried) and return the decoded JSON body (``None`` for an empty body)."""
        hdrs = dict(headers or {})
        xsrf = self._xsrf_token()
        if xsrf:
            hdrs.setdefault("X-XSRF-TOKEN", xsrf)
        resp = self._send("POST", url, params=params, headers=hdrs, json=json, follow=False)
        return self._decode(resp)

    # -- internals ----------------------------------------------------------------------------

    def _send(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None,
        headers: dict[str, str] | None,
        follow: bool,
        json: Any = None,
    ) -> httpx.Response:
        hdrs = {"X-Correlation-Id": str(uuid.uuid4()), **(headers or {})}
        kwargs: dict[str, Any] = {"params": _clean(params), "headers": hdrs}
        if json is not None:
            kwargs["json"] = json
        resp = self.client.request(method, url, **kwargs)
        hops = 0
        while resp.is_redirect:
            location = urljoin(str(resp.url), resp.headers.get("location", ""))
            if "queue-it" in urlsplit(location).netloc:
                raise QueueItError(f"{method} {url} was redirected to the Queue-it waiting room")
            if urlsplit(location).fragment == "404":
                # Unknown product pages redirect to "/?search=...#404".
                raise ApiError(404, "not found", url=str(resp.url))
            same_host = urlsplit(location).hostname == resp.url.host
            if not (follow and method == "GET" and same_host) or hops >= MAX_REDIRECTS:
                raise ApiError(resp.status_code, f"unexpected redirect to {location}", url=str(resp.url))
            hops += 1
            # Redirects drop the query string (e.g. GetAsJson=1), so send the original params again.
            resp = self.client.get(location, params=_clean(params), headers=hdrs)
        return resp

    def _decode(self, resp: httpx.Response) -> Any:
        if resp.is_success:
            if not resp.content.strip():
                return None
            try:
                return resp.json()
            except ValueError:
                raise ApiError(resp.status_code, "expected a JSON response", url=str(resp.url)) from None
        raise _to_api_error(resp)

    def _xsrf_token(self) -> str | None:
        for cookie in self.client.cookies.jar:
            if cookie.name == "XSRF-TOKEN":
                return cookie.value
        return None


def _clean(params: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop ``None`` values and render booleans the way ASP.NET expects them."""
    if params is None:
        return None
    out: dict[str, Any] = {}
    for k, v in params.items():
        if v is None:
            continue
        out[k] = ("true" if v else "false") if isinstance(v, bool) else v
    return out


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("retry-after", "")
    try:
        return min(float(value), 30.0)
    except ValueError:
        return None


def _to_api_error(resp: httpx.Response) -> ApiError:
    url = str(resp.url)
    try:
        body = resp.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and ("ErrorMessage" in body or "ErrorCode" in body):
        return ApiError(
            resp.status_code,
            body.get("ErrorMessage") or resp.reason_phrase,
            error_code=body.get("ErrorCode"),
            developer_message=body.get("DeveloperMessage") or None,
            url=url,
        )
    text = resp.text.strip()[:200] or resp.reason_phrase
    return ApiError(resp.status_code, text, url=url)
