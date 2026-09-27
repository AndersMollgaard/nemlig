import httpx
import pytest
from conftest import WWW, fixture, make_jwt, token_body

from nemlig import AuthError, NemligClient, NotLoggedInError
from nemlig._http import Http
from nemlig.auth import Token, TokenManager


def test_token_claims():
    customer = Token.parse(make_jwt(debitor="42", exp=1000))
    assert customer.debitor_id == "42" and customer.is_customer
    assert customer.expires_at == 1000
    assert Token.parse(make_jwt()).debitor_id is None


def test_captured_claims_shape():
    """The real claim layouts from the fixtures, before and after login."""
    anon = Token(value="", claims=fixture("token_anonymous_claims.json"))
    customer = Token(value="", claims=fixture("token_customer_claims.json"))
    assert not anon.is_customer
    assert customer.is_customer


def test_token_manager_caches_until_near_expiry(api):
    now = [1_000.0]
    route = api.get(f"{WWW}/webapi/Token").mock(
        side_effect=lambda request: httpx.Response(200, json=token_body(exp=now[0] + 300))
    )
    http = Http()
    tokens = TokenManager(http, clock=lambda: now[0])
    first = tokens.get()
    now[0] += 250  # still more than 45 s left
    assert tokens.get() is first
    now[0] += 10  # inside the refresh margin
    assert tokens.get() is not first
    assert route.call_count == 2
    http.close()


def mock_login(api, *, ok=True):
    api.get(f"{WWW}/webapi/AntiForgery").respond(
        json={"Header": "X-XSRF-TOKEN", "Value": "x"}, headers={"Set-Cookie": "XSRF-TOKEN=x; path=/"}
    )
    if ok:
        return api.post(f"{WWW}/webapi/login").respond(
            json=fixture("login_response.json"), headers={"Set-Cookie": ".ASPXAUTH=abc; path=/; HttpOnly"}
        )
    return api.post(f"{WWW}/webapi/login").respond(
        400, json={"ErrorCode": 4, "ErrorMessage": "E-mail og/eller password er ikke gyldig"}
    )


def test_login_with_wrong_password(api):
    api.get(f"{WWW}/webapi/Token").respond(json=token_body())
    mock_login(api, ok=False)
    with NemligClient("me@example.com", "wrong", persist=False) as client:
        with pytest.raises(AuthError, match="ikke gyldig"):
            client.login()


def test_expired_session_logs_in_again(api):
    """An anonymous token (expired cookie) with credentials triggers exactly one login."""
    api.get(f"{WWW}/webapi/Token").mock(
        side_effect=[
            httpx.Response(200, json=token_body()),  # session expired: no debitorId
            httpx.Response(200, json=token_body()),  # anonymous token used for the login call
            httpx.Response(200, json=token_body(debitor="1")),  # after login
        ]
    )
    login = mock_login(api)
    api.get(f"{WWW}/webapi/basket/GetBasket").respond(json=fixture("basket.json"))
    with NemligClient("me@example.com", "pw", persist=False) as client:
        basket = client.get_basket()
    assert login.call_count == 1
    assert basket.total_price == 229.05
    body = login.calls.last.request.content
    assert b'"Username":"me@example.com"' in body.replace(b" ", b"")
    assert login.calls.last.request.headers["X-XSRF-TOKEN"] == "x"


def test_login_that_yields_anonymous_token_raises(api):
    api.get(f"{WWW}/webapi/Token").respond(json=token_body())
    mock_login(api)
    with NemligClient("me@example.com", "pw", persist=False) as client:
        with pytest.raises(NotLoggedInError):
            client.get_basket()


def test_no_credentials_and_no_session(anonymous):
    assert not anonymous.is_logged_in()
    with pytest.raises(NotLoggedInError):
        anonymous.get_basket()
