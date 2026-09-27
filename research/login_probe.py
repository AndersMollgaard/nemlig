"""Probe: log in to nemlig.com from a script and exercise the APIs.

Research script, not the client. It verified on 2026-09-27 that plain HTTP login works
(see docs/nemlig-api.md). Reads NEMLIG_USER / NEMLIG_PASS from the repo's .env.
Prints only statuses, shapes and counts -- never credentials or personal data.
Basket writes use a test product and are reverted at the end.

    python3 research/login_probe.py
"""
import base64
import json
import os
import pickle
import sys
import time
import uuid

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = os.path.join(ROOT, ".env")
WWW = "https://www.nemlig.com"
GW = "https://webapi.prod.knl.nemlig.it"
TEST_PRODUCT = "5050406"  # Havregryn (finvalsede) oeko -- chosen because it was not in the basket
JAR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe_cookies.pkl")

BASE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "User-Agent": "nemlig-probe/0.1",
    "Platform": "web",
    "Device-Size": "desktop",
    "Version": "11.235.1",
}


def load_env(path):
    out = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def claims(jwt):
    p = jwt.split(".")[1]
    p += "=" * (-len(p) % 4)
    return json.loads(base64.urlsafe_b64decode(p))


def debitor(jwt):
    try:
        return claims(jwt)["authorization"]["permissions"][0]["claims"]["debitorId"][0]
    except (KeyError, IndexError, TypeError):
        return None


def hdr(**extra):
    return {**BASE_HEADERS, "X-Correlation-Id": str(uuid.uuid4()), **extra}


def show(label, **kv):
    print(f"{label:<38} " + "  ".join(f"{k}={v}" for k, v in kv.items()))


def get_token(s):
    r = s.get(f"{WWW}/webapi/Token", headers=hdr(Referer=f"{WWW}/"))
    r.raise_for_status()
    return r.json()["access_token"]


def qty(basket, pid):
    return next((l["Quantity"] for l in basket.get("Lines", []) if l["Id"] == pid), 0)


def credentials():
    env = load_env(ENV)
    user, pw = env.get("NEMLIG_USER"), env.get("NEMLIG_PASS")
    if not (user and pw):
        sys.exit("NEMLIG_USER / NEMLIG_PASS missing in .env")
    return user, pw


def login(s, user, pw, verbose=True):
    """Steps 1-3 of the login flow. Returns (xsrf, anonymous token, login response)."""
    r = s.get(f"{WWW}/webapi/AntiForgery", headers=hdr())
    xsrf = r.json()["Value"]
    tok = get_token(s)
    if verbose:
        show("1 AntiForgery", status=r.status_code, cookies=sorted(s.cookies.keys()))
        show("2 Token (anon)", debitorId=bool(debitor(tok)), user=claims(tok).get("preferred_username"))

    r = s.post(
        f"{WWW}/webapi/login",
        headers=hdr(**{"X-XSRF-TOKEN": xsrf, "Authorization": f"Bearer {tok}",
                       "Referer": f"{WWW}/login?returnUrl=%2F", "Content-Type": "application/json"}),
        json={"Username": user, "Password": pw, "CheckForExistingProducts": True,
              "DoMerge": True, "AppInstalled": False, "SaveExistingBasket": False},
    )
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if verbose:
        show("3 POST /webapi/login", status=r.status_code, keys=sorted(body)[:8] if r.ok else "",
             MergeSuccessful=body.get("MergeSuccessful"), ZoneId=body.get("DeliveryZoneId"))
    if not r.ok:
        print("   error body:", r.text[:300])
        sys.exit(1)
    return xsrf, tok, body


def main():
    user, pw = credentials()
    s = requests.Session()
    xsrf, _, _ = login(s, user, pw)
    show("  cookies after login", names=sorted(s.cookies.keys()))

    # 3. Customer token
    tok = get_token(s)
    c = claims(tok)
    show("4 Token (after login)", debitorId=bool(debitor(tok)), exp_in=c["exp"] - int(time.time()))

    # 4. Cookie-only reads (no bearer, no custom headers)
    plain = {"Accept": "application/json", "User-Agent": "nemlig-probe/0.1"}
    r = s.get(f"{WWW}/webapi/user/GetCurrentUser", headers=plain)
    show("5 GetCurrentUser (cookie only)", status=r.status_code, hasDebitorId=bool(r.ok and r.json().get("DebitorId")))
    r = s.get(f"{WWW}/webapi/basket/GetBasket", headers=plain)
    basket = r.json()
    slot = basket.get("DeliveryTimeSlot") or {}
    show("6 GetBasket (cookie only)", status=r.status_code, lines=len(basket["Lines"]), total=basket["TotalPrice"],
         slotId=slot.get("Id"), reserved=slot.get("Reserved"), tsUtc=basket.get("TimeslotUtc"), zone=basket.get("DeliveryZoneId"))
    snapshot = {l["Id"]: l["Quantity"] for l in basket["Lines"]}

    # 5. Search with the account's delivery context
    r = s.get(f"{GW}/searchgateway/api/search",
              headers={"Accept": "application/json", "Authorization": f"Bearer {tok}", "User-Agent": "nemlig-probe/0.1"},
              params={"query": "havregryn", "take": 5, "skip": 0, "timeslotUtc": basket["TimeslotUtc"],
                      "deliveryZoneId": basket["DeliveryZoneId"], "TimeSlotId": slot.get("Id", 0)})
    prods = r.json()["Products"]["Products"] if r.ok else []
    show("7 search (customer ctx)", status=r.status_code, bytes=len(r.content), hits=len(prods),
         first=[(p["Id"], p["Price"]) for p in prods[:2]])

    # 6. Favourites via productbff (needs debitorId)
    r = s.get(f"{GW}/productbff/api/web/page",
              headers={"Accept": "application/json", "Authorization": f"Bearer {tok}", "User-Agent": "nemlig-probe/0.1"},
              params={"path": "/favoritter", "timeslotId": slot.get("Id", "")})
    favs = []
    if r.ok:
        for sec in r.json().get("pageContent") or []:
            favs += sec.get("products") or []
    show("8 productbff /favoritter", status=r.status_code, bytes=len(r.content), products=len(favs))

    # 7. Orders
    r = s.get(f"{WWW}/webapi/order/GetBasicOrderHistory", headers=plain, params={"skip": 0, "take": 3})
    show("9 order history", status=r.status_code, orders=len(r.json().get("Orders", [])) if r.ok else None)

    # 8. Writes: without XSRF header, then with it
    post = lambda body, extra: s.post(f"{WWW}/webapi/basket/AddToBasket", json=body,
                                      headers={**plain, "Content-Type": "application/json", **extra})
    r = post({"ProductId": TEST_PRODUCT, "quantity": 1, "AffectPartialQuantity": False,
              "disableQuantityValidation": False}, {})
    show("10 AddToBasket no XSRF, no bearer", status=r.status_code,
         qty=qty(r.json(), TEST_PRODUCT) if r.ok else r.text[:120])
    xsrf_now = s.cookies.get("XSRF-TOKEN") or xsrf
    r = post({"productId": TEST_PRODUCT, "quantity": 2, "addToExisting": True}, {"X-XSRF-TOKEN": xsrf_now})
    show("11 AddToBasket addToExisting +2", status=r.status_code,
         qty=qty(r.json(), TEST_PRODUCT) if r.ok else r.text[:120])

    # 9. Persist cookies, rebuild a fresh session from them alone
    with open(JAR, "wb") as f:
        pickle.dump(s.cookies, f)
    os.chmod(JAR, 0o600)
    s2 = requests.Session()
    with open(JAR, "rb") as f:
        s2.cookies.update(pickle.load(f))
    tok2 = get_token(s2)
    r = s2.get(f"{WWW}/webapi/basket/GetBasket", headers=plain)
    show("12 fresh session from saved cookies", tokenDebitor=bool(debitor(tok2)), basket=r.status_code,
         testQty=qty(r.json(), TEST_PRODUCT) if r.ok else None)

    # 10. Revert the test product; verify basket equals the snapshot
    r = post({"ProductId": TEST_PRODUCT, "quantity": 0, "AffectPartialQuantity": True,
              "disableQuantityValidation": False}, {"X-XSRF-TOKEN": xsrf_now})
    final = {l["Id"]: l["Quantity"] for l in r.json()["Lines"]}
    show("13 revert", status=r.status_code, matchesSnapshot=final == snapshot)
    os.remove(JAR)


if __name__ == "__main__":
    main()
