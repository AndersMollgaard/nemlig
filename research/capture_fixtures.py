"""Capture trimmed, redacted real responses into docs/fixtures/ as shape references.

Research script, not the client. Read-only against the account: no basket writes. The one
POST besides login is a CopyOrder with a bogus id, to record the error shape.

Trimming: arrays keep their first 2 items, strings are cut to 300 chars.
Redaction: address blocks, names, contact details, ids tied to the person, and free text
the account holder typed are replaced with "<redacted>". A final scan checks that none
of the account's own personal strings made it into any fixture.

    uv run --with requests python research/capture_fixtures.py
"""
import json
import os
import re
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from login_probe import GW, ROOT, WWW, claims, credentials, get_token, login  # noqa: E402

OUT = os.path.join(ROOT, "docs", "fixtures")
PLAIN = {"Accept": "application/json", "User-Agent": "nemlig-probe/0.1"}
R = "<redacted>"

# Whole subtrees that describe the person or their household.
SUBTREE_KEYS = re.compile(
    r"^(InvoiceAddress|DeliveryAddress|DriverInformation|TrackingModel|GdprSettings|NemligAccount"
    r"|UpcomingOrder|Addresses|Address)$"
)
# Single values tied to the person.
SCALAR_KEYS = re.compile(
    r"^(KVHX|Email|MobileNumber|PhoneNumber|DebitorId|CustomerName|ContactPerson|DoorCode|Notes"
    r"|UnattendedNotes|PlacementMessage|MessageToDriver|EAN|CVR|UserId|BasketGuid|PreviousBasketGuid"
    r"|OrderNumber|PreviousOrderNumber|BackedByOrderNumber|CreditCardId|CreditCardFee"
    r"|sub|email|name|given_name|family_name|jti|sid|session_state|debitorId|memberId)$"
)


def trim(x, depth=0):
    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            if SUBTREE_KEYS.match(k) and not isinstance(v, bool):
                out[k] = R if v is not None else None
            elif SCALAR_KEYS.match(k) and v not in (None, "", 0) and not isinstance(v, bool):
                out[k] = R
            else:
                out[k] = trim(v, depth + 1)
        return out
    if isinstance(x, list):
        return [trim(v, depth + 1) for v in x[:2]]
    if isinstance(x, str) and len(x) > 300:
        return x[:300] + "…"
    return x


def save(name, data, note):
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"_note": note, "response": data}, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"  wrote {name}")


def personal_strings(user):
    """Strings from the account's own profile, to verify none leak into fixtures."""
    found = set()

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str) and len(x) >= 4:
            found.add(x)

    for key in ("InvoiceAddress", "DeliveryAddress", "DriverInformation"):
        walk(user.get(key))
    for key in ("Email", "DebitorId", "MessageToDriver"):
        if isinstance(user.get(key), str) and len(user[key]) >= 4:
            found.add(user[key])
    return found


def main():
    os.makedirs(OUT, exist_ok=True)
    user, pw = credentials()

    # Anonymous
    anon = requests.Session()
    boot = anon.get(f"{WWW}/?GetAsJson=1", headers=PLAIN).json()
    save("bootstrap_getasjson.json", {"topLevelKeys": sorted(boot), "Settings": trim(boot["Settings"])},
         "GET www/?GetAsJson=1 (anonymous). Only Settings kept; content/aside are page widgets.")
    save("appsettings_website.json", trim(anon.get(f"{WWW}/webapi/v2/AppSettings/Website", headers=PLAIN).json()),
         "GET www/webapi/v2/AppSettings/Website (anonymous).")
    atok = get_token(anon)
    save("token_anonymous_claims.json", trim(claims(atok)),
         "Decoded JWT payload from GET www/webapi/Token without login. Response body is "
         "{upgraded, access_token, expires_in: 300, refresh_expires_in, token_type: 'Bearer', not-before-policy}.")
    save("delivery_days_anonymous.json",
         trim(anon.get(f"{WWW}/webapi/v2/Delivery/GetDeliveryDays",
                       params={"startDate": "undefined", "days": 2, "showForSubscriptions": "false"},
                       headers=PLAIN).json()),
         "GET www/webapi/v2/Delivery/GetDeliveryDays?startDate=undefined&days=2 (anonymous, default zone). "
         "Availability: 0 available, 1 past deadline, 2 sold out, 3 not active.")

    # Logged in
    s = requests.Session()
    xsrf, _, login_body = login(s, user, pw, verbose=False)
    save("login_response.json", trim(login_body),
         "POST www/webapi/login. Note DeliveryZoneId here may differ from the basket's (1 vs 4 seen).")
    tok = get_token(s)
    save("token_customer_claims.json", trim(claims(tok)),
         "Decoded JWT payload after login. authorization.permissions[0].claims.debitorId marks a customer token.")
    auth = {**PLAIN, "Authorization": f"Bearer {tok}"}

    me = s.get(f"{WWW}/webapi/user/GetCurrentUser", headers=PLAIN).json()
    secrets = personal_strings(me) | {user}
    save("current_user.json", trim(me), "GET www/webapi/user/GetCurrentUser (cookie only).")

    basket = s.get(f"{WWW}/webapi/basket/GetBasket", headers=PLAIN).json()
    save("basket.json", trim(basket),
         "GET www/webapi/basket/GetBasket (cookie only). POST AddToBasket and addShoppingListToBasket "
         "return this same shape.")
    ctx = {"timeslotUtc": basket["TimeslotUtc"], "deliveryZoneId": basket["DeliveryZoneId"],
           "TimeSlotId": (basket.get("DeliveryTimeSlot") or {}).get("Id", 0)}

    search = s.get(f"{GW}/searchgateway/api/search", headers=auth,
                   params={"query": "havregryn", "take": 5, "skip": 0, **ctx}).json()
    save("search.json", trim(search),
         "GET gw/searchgateway/api/search?query=havregryn with the basket's timeslotUtc, deliveryZoneId, "
         "TimeSlotId. Full response was ~93 KB for 5 hits; TopUpOrderProducts/Recipes/Ads/Facets are the bulk.")
    save("search_quick.json",
         trim(s.get(f"{GW}/searchgateway/api/quick", headers=auth,
                    params={"query": "havre", "correlationId": boot["Settings"].get("SitecorePublishedStamp", "")}).json()),
         "GET gw/searchgateway/api/quick?query=havre")

    slug = search["Products"]["Products"][0]["Url"]
    page = s.get(f"{WWW}/{slug}", params={"GetAsJson": 1}, headers=PLAIN).json()
    detail = next(c for c in page["content"] if c.get("TemplateName") == "productdetailspot")
    save("product_details.json", {"MetaData": trim(page.get("MetaData")), "productdetailspot": trim(detail)},
         f"GET www/{slug}?GetAsJson=1. The product is content[TemplateName=productdetailspot].")

    favs = s.get(f"{GW}/productbff/api/web/page", headers=auth,
                 params={"path": "/favoritter", "timeslotId": ctx["TimeSlotId"]}).json()
    save("productbff_favourites.json", trim(favs),
         "GET gw/productbff/api/web/page?path=/favoritter&timeslotId=<slot Id> with customer JWT. "
         "camelCase, prices in øre. pageContent[] sections of contentType ProductList.")

    orders = s.get(f"{WWW}/webapi/order/GetBasicOrderHistory", params={"skip": 0, "take": 2}, headers=PLAIN).json()
    save("order_history.json", trim(orders),
         "GET www/webapi/order/GetBasicOrderHistory?skip=0&take=2. Use numeric Id for order lines and CopyOrder.")
    if orders.get("Orders"):
        oid = orders["Orders"][0]["Id"]
        save("order_lines.json", trim(s.get(f"{WWW}/webapi/v2/order/GetOrderHistory/{oid}", headers=PLAIN).json()),
             "GET www/webapi/v2/order/GetOrderHistory/{Id}. Lines[].ProductNumber is a basket product id.")

    lists = s.get(f"{WWW}/webapi/ShoppingList/GetShoppingLists", params={"skip": 0, "take": 6}, headers=PLAIN).json()
    for key, val in lists.items():  # list names are user-chosen text
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict) and "Name" in item:
                    item["Name"] = R
                    item["Url"] = R  # carries the list name as a query parameter
    save("shopping_lists.json", trim(lists), "GET www/webapi/ShoppingList/GetShoppingLists?skip=0&take=6. Name and Url (which embeds the name) redacted.")

    err = s.post(f"{WWW}/webapi/order/CopyOrder", json={"OrderNumber": "0"},
                 headers={**PLAIN, "Content-Type": "application/json", "X-XSRF-TOKEN": xsrf})
    save("error_copyorder_not_found.json", {"status": err.status_code, "body": trim(err.json())},
         "POST www/webapi/order/CopyOrder with a bogus id: the standard /webapi error envelope (HTTP 400).")

    # Leak check
    leaks = []
    for name in sorted(os.listdir(OUT)):
        if name.endswith(".json"):
            text = open(os.path.join(OUT, name), encoding="utf-8").read()
            leaks += [name for sec in secrets if sec in text]
    print(f"leak check: {len(secrets)} personal strings scanned, "
          f"{'no leaks' if not leaks else 'LEAKS IN ' + ', '.join(sorted(set(leaks)))}")
    if leaks:
        sys.exit(1)


if __name__ == "__main__":
    main()
