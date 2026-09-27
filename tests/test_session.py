import stat

import httpx
from conftest import WWW, token_body

from nemlig import NemligClient
from nemlig.session import SessionStore


def test_round_trip_and_permissions(tmp_path):
    path = tmp_path / "nested" / "session.json"
    jar = httpx.Cookies()
    jar.set(".ASPXAUTH", "secret", domain="www.nemlig.com", path="/")
    jar.set("XSRF-TOKEN", "x", domain=".nemlig.com", path="/")
    SessionStore(path).save(jar.jar)

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
