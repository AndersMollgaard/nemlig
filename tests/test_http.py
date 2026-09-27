import httpx
import pytest
from conftest import WWW

from nemlig._http import Http
from nemlig.errors import ApiError, QueueItError


@pytest.fixture
def http(api):
    sleeps: list[float] = []
    h = Http(sleep=sleeps.append)
    h.sleeps = sleeps
    yield h
    h.close()


def test_get_retries_on_server_errors(api, http):
    route = api.get(f"{WWW}/webapi/x").mock(
        side_effect=[httpx.Response(503), httpx.Response(502), httpx.Response(200, json={"ok": 1})]
    )
    assert http.get(f"{WWW}/webapi/x") == {"ok": 1}
    assert route.call_count == 3
    assert http.sleeps == [0.5, 1.0]


def test_get_honours_retry_after(api, http):
    api.get(f"{WWW}/webapi/x").mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "2"}), httpx.Response(200, json=[])]
    )
    assert http.get(f"{WWW}/webapi/x") == []
    assert http.sleeps == [2.0]


def test_get_gives_up_after_retries(api, http):
    route = api.get(f"{WWW}/webapi/x").respond(503)
    with pytest.raises(ApiError) as exc:
        http.get(f"{WWW}/webapi/x")
    assert exc.value.status == 503
    assert route.call_count == 4


def test_post_is_never_retried(api, http):
    route = api.post(f"{WWW}/webapi/basket/AddToBasket").respond(503)
    with pytest.raises(ApiError):
        http.post(f"{WWW}/webapi/basket/AddToBasket", json={})
    assert route.call_count == 1


def test_error_envelope(api, http):
    api.post(f"{WWW}/webapi/order/CopyOrder").respond(
        400,
        json={"ErrorCode": 8, "ErrorMessage": "Order not found", "DeveloperMessage": "Order with id: 0"},
    )
    with pytest.raises(ApiError) as exc:
        http.post(f"{WWW}/webapi/order/CopyOrder", json={"OrderNumber": "0"})
    err = exc.value
    assert (err.status, err.error_code, err.message) == (400, 8, "Order not found")
    assert err.developer_message == "Order with id: 0"


def test_queue_it_redirect(api, http):
    api.get(f"{WWW}/").respond(302, headers={"Location": "https://nemlig.queue-it.net/?c=nemlig"})
    with pytest.raises(QueueItError):
        http.get(f"{WWW}/", params={"GetAsJson": 1}, follow_redirects=True)


def test_redirect_followed_with_params(api, http):
    api.get(f"{WWW}/p-5050406").respond(301, headers={"Location": "/havregryn-5050406"})
    target = api.get(f"{WWW}/havregryn-5050406", params={"GetAsJson": "1"}).respond(json={"content": []})
    assert http.get(f"{WWW}/p-5050406", params={"GetAsJson": 1}, follow_redirects=True) == {"content": []}
    assert target.called


def test_redirect_not_followed_by_default(api, http):
    api.get(f"{WWW}/webapi/x").respond(302, headers={"Location": "/login"})
    with pytest.raises(ApiError):
        http.get(f"{WWW}/webapi/x")


def test_not_found_redirect(api, http):
    api.get(f"{WWW}/p-1").respond(301, headers={"Location": "/?search=p#404"})
    with pytest.raises(ApiError) as exc:
        http.get(f"{WWW}/p-1", params={"GetAsJson": 1}, follow_redirects=True)
    assert exc.value.status == 404


def test_post_sends_xsrf_header_and_empty_body_is_none(api, http):
    http.cookies.set("XSRF-TOKEN", "tok123", domain="www.nemlig.com")
    route = api.post(f"{WWW}/webapi/basket/ClearBasket").respond(200, content=b"")
    assert http.post(f"{WWW}/webapi/basket/ClearBasket") is None
    request = route.calls.last.request
    assert request.headers["X-XSRF-TOKEN"] == "tok123"
    assert request.headers["User-Agent"].startswith("nemlig-python/")
    assert "X-Correlation-Id" in request.headers


def test_bool_and_none_params(api, http):
    route = api.get(f"{WWW}/webapi/x").respond(json={})
    http.get(f"{WWW}/webapi/x", params={"a": True, "b": False, "c": None, "d": 3})
    assert dict(route.calls.last.request.url.params) == {"a": "true", "b": "false", "d": "3"}
