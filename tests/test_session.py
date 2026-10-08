import json
import stat
import sys

import httpx
import pytest
from conftest import WWW, token_body

from nemlig import NemligClient
from nemlig.session import SessionStore, user_key


def test_round_trip_and_permissions(tmp_path):
    path = tmp_path / "nested" / "session.json"
    jar = httpx.Cookies()
    jar.set(".ASPXAUTH", "secret", domain="www.nemlig.com", path="/")
    jar.set("XSRF-TOKEN", "x", domain=".nemlig.com", path="/")
    SessionStore(path).save(jar.jar)

    if sys.platform != "win32":  # Windows has no mode bits; the user profile's ACL guards it
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    restored = httpx.Cookies()
    assert SessionStore(path).load(restored.jar)
    assert restored.get(".ASPXAUTH", domain="www.nemlig.com") == "secret"
    assert restored.get("XSRF-TOKEN", domain=".nemlig.com") == "x"


def test_load_missing_or_corrupt(tmp_path):
    assert not SessionStore(tmp_path / "none.json").load(httpx.Cookies().jar)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert not SessionStore(bad).load(httpx.Cookies().jar)


def test_client_restores_saved_cookies(api, tmp_path):
    path = tmp_path / "session.json"
    jar = httpx.Cookies()
    jar.set(".ASPXAUTH", "saved", domain="www.nemlig.com", path="/")
    SessionStore(path).save(jar.jar)

    route = api.get(f"{WWW}/webapi/Token").respond(json=token_body(debitor="1"))
    with NemligClient(session_file=path) as client:
        assert client.is_logged_in()
    assert ".ASPXAUTH=saved" in route.calls.last.request.headers["Cookie"]


def test_logout_deletes_session_file(api, tmp_path):
    path = tmp_path / "session.json"
    jar = httpx.Cookies()
    jar.set(".ASPXAUTH", "saved", domain="www.nemlig.com", path="/")
    SessionStore(path).save(jar.jar)
    client = NemligClient(session_file=path)
    client.logout()
    client.close()
    assert not path.exists()


def saved_session(path, user=None):
    jar = httpx.Cookies()
    jar.set(".ASPXAUTH", "saved", domain="www.nemlig.com", path="/")
    SessionStore(path).save(jar.jar, user)


def test_credentials_use_only_their_own_session(api, tmp_path):
    path = tmp_path / "session.json"
    saved_session(path, user_key("a@example.com"))
    api.get(f"{WWW}/webapi/Token").respond(json=token_body(debitor="1"))

    with NemligClient(" A@example.com", "pw", session_file=path) as same:
        assert same._http.cookies.get(".ASPXAUTH") == "saved"
    with NemligClient("b@example.com", "pw", session_file=path) as other:
        assert other._http.cookies.get(".ASPXAUTH") is None


def test_credentials_ignore_a_session_of_unknown_user(tmp_path):
    path = tmp_path / "session.json"
    saved_session(path)
    with NemligClient("a@example.com", "pw", session_file=path) as client:
        assert client._http.cookies.get(".ASPXAUTH") is None


def test_saving_without_credentials_keeps_the_owner(tmp_path):
    path = tmp_path / "session.json"
    saved_session(path, user_key("a@example.com"))
    NemligClient(session_file=path).close()
    assert json.loads(path.read_text())["user"] == user_key("a@example.com")


@pytest.mark.parametrize("content", ["[]", '{"cookies": [1]}', '{"cookies": [{"name": "x"}]}'])
def test_load_malformed(tmp_path, content):
    path = tmp_path / "session.json"
    path.write_text(content)
    jar = httpx.Cookies()
    assert not SessionStore(path).load(jar.jar)
    assert not list(jar.jar)
