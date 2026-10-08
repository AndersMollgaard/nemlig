import base64
import json
import time
from pathlib import Path

import pytest
import respx

from nemlig import NemligClient

FIXTURES = Path(__file__).resolve().parent.parent / "docs" / "fixtures"
WWW = "https://www.nemlig.com"
GW = "https://webapi.prod.knl.nemlig.it"


def fixture(name: str):
    """The ``response`` part of a captured fixture in docs/fixtures/."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["response"]


def make_jwt(*, debitor: str | None = None, exp: float | None = None) -> str:
    claims: dict = {"exp": int(exp if exp is not None else time.time() + 300)}
    if debitor:
        claims["authorization"] = {"permissions": [{"claims": {"debitorId": [debitor]}}]}

    def enc(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    return f"{enc({'alg': 'none'})}.{enc(claims)}.sig"


def token_body(**kwargs) -> dict:
    return {"access_token": make_jwt(**kwargs), "expires_in": 300, "token_type": "Bearer"}


@pytest.fixture(autouse=True)
def no_household_files(monkeypatch, tmp_path):
    """No test reads or writes the repo's own .env, preferences.toml or groups.json."""
    monkeypatch.setenv("NEMLIG_HOME", str(tmp_path))


@pytest.fixture
def api():
    """A respx router for both hosts; unmatched requests fail the test."""
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture
def customer(api):
    """A client whose cookies already belong to an account (the token has a debitorId)."""
    api.get(f"{WWW}/webapi/Token").respond(json=token_body(debitor="123"))
    with NemligClient(persist=False, sleep=lambda _: None) as client:
        yield client


@pytest.fixture
def anonymous(api):
    api.get(f"{WWW}/webapi/Token").respond(json=token_body())
    settings = fixture("bootstrap_getasjson.json")["Settings"]
    api.get(f"{WWW}/", params={"GetAsJson": "1"}).respond(json={"Settings": settings})
    with NemligClient(persist=False, sleep=lambda _: None) as client:
        yield client
