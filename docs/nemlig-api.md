# Nemlig.com web API: investigation of existing clients

Snapshot of the living doc at
<https://claude.ai/code/artifact/23811d05-5483-4b42-822a-27a9523c75e3>, as of 2026-09-27.
This file is the version a coding session should rely on. Trimmed real responses are in
[`fixtures/`](fixtures/), and a working login script is in [`../research/`](../research/).

Nemlig.com has no public API. A client drives the same JSON endpoints the website's Angular app
uses. There are two hosts: `www.nemlig.com`, which uses cookies plus an XSRF header, and
`webapi.prod.knl.nemlig.it`, which uses a 5-minute bearer JWT. Anonymous search, product details
and delivery slots all worked from Denmark on 2026-09-27. Basket and order endpoints need a
logged-in cookie. A plain Python `requests` script logs in and uses every endpoint, and tests
confirmed three bulk-fill options: incremental add (`addToExisting`), reorder in one call
(`CopyOrder`) and shopping list to basket. The main risks are silent session expiry,
`AddToBasket` setting absolute quantities, Queue-it redirects for browser user agents, and very
large responses.

## Existing solutions surveyed

About ten community projects talk to nemlig.com. All are unofficial and reverse-engineered from
the website's network traffic. Most were created or updated in 2026. `eisbaw/nemlig_cli` is the
most copied base and has the best written API notes.

| Project | Language | Kind | Login approach | Coverage | Last push |
| --- | --- | --- | --- | --- | --- |
| [eisbaw/nemlig_cli](https://github.com/eisbaw/nemlig_cli) | Python | CLI + API notes | Plain HTTP (XSRF, token, login) | Search, details, basket, order history | 2026-08-09 |
| [mikkelkaas/nemligmcp](https://github.com/mikkelkaas/nemligmcp) | TypeScript | MCP server (npm) | Plain HTTP | Search, basket, timeslots, order history | 2026-06-29 |
| [kraenhansen/nemlig-mcp](https://github.com/kraenhansen/nemlig-mcp) | Python | MCP server | Reuses nemlig_cli | Search, details, basket (batch), order history | 2026-08-20 |
| [emilbm/nemlig-mcp](https://github.com/emilbm/nemlig-mcp) | TypeScript | MCP server (Docker) | Headless Chromium, then cookie refresh | Search, basket, favourites, offers | 2026-09-17 |
| [tobiasdosdal/Nemlig.com-CLI](https://github.com/tobiasdosdal/Nemlig.com-CLI) | JavaScript | CLI | Plain HTTP | Search, basket, timeslots, orders, invoices, reorder | 2026-09-21 |
| [simontjell/nemlig-cli](https://github.com/simontjell/nemlig-cli) | Python | CLI (fork of eisbaw) | Plain HTTP | As eisbaw + local grocery list | 2026-09-17 |
| [mhattingpete/nemlig-shopper](https://github.com/mhattingpete/nemlig-shopper) | Python | CLI (PyPI) | Plain HTTP | Recipe parsing, search, add to cart | 2026-07-10 |
| [LordMike/MBW.Nemlig2MQTT](https://github.com/LordMike/MBW.Nemlig2MQTT) | C# | Home Assistant bridge | Plain HTTP | Order history, delivery status (no basket) | 2026-07-26 |
| [schourode/nemlig](https://github.com/schourode/nemlig) | Python | Library + robot | Plain HTTP | Orders, basket | 2019-04-29 (stale) |

None of them places orders or touches payment. Checkout is left to the browser by design.

## Architecture

A client talks to two hosts with different credentials. The site is Sitecore on ASP.NET behind
Cloudflare, served from Copenhagen (`cf-ray …-CPH`). The newer customer-facing APIs sit on a
separate gateway host.

```
                     ┌─ www.nemlig.com · auth: .ASPXAUTH cookie (+ X-XSRF-TOKEN) ──────────┐
                     │  /webapi/Token        /webapi/*             /<path>?GetAsJson=1       │
   ┌────────────┐    │  Keycloak JWT, 5 min  login, basket,        page JSON: settings,      │
   │ our client │───▶│  anon or customer     orders, delivery      product details           │
   │ cookie jar │    │        │              (page routes + browser User-Agent → Queue-it)  │
   │ + JWT      │    └────────┼─────────────────────────────────────────────────────────────┘
   └────────────┘             │ JWT sent as Bearer
         │           ┌────────▼─ webapi.prod.knl.nemlig.it · auth: Bearer JWT, no cookies ──┐
         └──────────▶│  /searchgateway/api            /productbff/api/web/page              │
                     │  search, quick (autocomplete)  offers, favourites pages              │
                     │  prices in kroner              prices in øre                          │
                     └──────────────────────────────────────────────────────────────────────┘
```

The website's own Angular code attaches the bearer only to `*.knl.nemlig.it`, `api.nemlig.com` and
`*.k8s.nemlig`. Calls to `www.nemlig.com/webapi/*` rely on cookies plus Angular's standard XSRF
header. Existing clients send the bearer to both hosts, which is harmless.

### Request conventions

| Header | Sent to | Value | Needed? |
| --- | --- | --- | --- |
| `Version` | `/webapi/*`, `GetAsJson` | Web app version, `11.235.1` on 2026-09-27 (from `main.js`) | Sent by the site. Not needed in our tests |
| `Platform` / `Device-Size` | `/webapi/*`, `GetAsJson` | `web` / `desktop` | Sent by the site. Not needed in our tests |
| `X-Correlation-Id` | All | Fresh UUID per request | Tracing only |
| `X-XSRF-TOKEN` | Mutating `/webapi/*` calls | Value from `/webapi/AntiForgery` or the `XSRF-TOKEN` cookie | Sent by the site on POSTs. Not enforced in our tests (browser and script), but cheap to send |
| `Authorization: Bearer` | Gateway host | JWT from `/webapi/Token` | Yes. Without it: `401 Jwt is missing` |
| `User-Agent` | All | A plain non-browser string | A browser UA on page routes triggers Queue-it (below) |

JSON uses PascalCase on `/webapi` and the search gateway, and camelCase on `productbff`. Money is
decimal kroner everywhere except `productbff`, which uses integer øre.

## Authentication and sessions

The account lives in the `.ASPXAUTH` cookie, which lasts about a year. The bearer JWT is a
5-minute Keycloak token that anyone can mint. A logged-in client only has to keep the cookie jar
and mint a new JWT when the old one expires.

### Login flow over plain HTTP (used by eisbaw, mikkelkaas, tobiasdosdal, LordMike)

1. `GET /webapi/AntiForgery` returns `{"Header":"X-XSRF-TOKEN","Value":"…"}` and sets the
   `XSRF-TOKEN` and `XSRF-COOKIE-TOKEN` (HttpOnly) cookies.
2. `GET /webapi/Token` returns `{access_token, expires_in: 300, token_type: "Bearer"}`. Without the
   auth cookie this is an anonymous `service-account-sitecore` token.
3. `POST /webapi/login` with the XSRF header and JSON `{Username, Password,
   CheckForExistingProducts: true, DoMerge: true, AppInstalled: false, SaveExistingBasket: false}`.
   Success sets `.ASPXAUTH`, `IVCookieBasketKey` and `IVCookieBasketKeyId`, and returns
   `MergeSuccessful`, `DeliveryZoneId`, `TimeslotUtc` and GDPR ids.
4. `GET /webapi/Token` again, now carrying the cookie. The new JWT carries the customer's
   `debitorId` claim under `authorization.permissions[0].claims`.
5. Optional check: `GET /webapi/user/GetCurrentUser` should return a `DebitorId`. There is no
   `IsLoggedIn` field.

### Keeping a session alive

- Persist the cookie jar (chmod 600). tobiasdosdal stores it in `~/.config/nemlig-cli/session.json`
  and never stores the password.
- Refresh the JWT from its own `exp` claim 30–60 s before expiry, by calling `/webapi/Token` with
  the cookies. emilbm measured about 280 ms per refresh.
- If a refreshed JWT has no `debitorId`, the cookie has expired and you need a full login again.

### Resolved: login works without a browser (tested 2026-09-27)

A Python `requests` script with a plain `nemlig-probe/0.1` user agent logged in with the five
steps above ([`research/login_probe.py`](../research/login_probe.py)). No browser, captcha or
Cloudflare challenge was involved. emilbm's Playwright login is unnecessary. What the script saw:

| Step | Result |
| --- | --- |
| `POST /webapi/login` | 200, `MergeSuccessful: true`. Cookies set: `.ASPXAUTH`, `ASP.NET_SessionId`, `IVCookieBasketKey`, `IVCookieBasketKeyId`, `SC_ANALYTICS_GLOBAL_COOKIE` |
| `/webapi/Token` after login | JWT carries `debitorId`, expires in 300 s |
| Basket, current user, order history | 200 with the cookie alone (no bearer, no custom headers) |
| Search with the basket's `TimeslotUtc`, `DeliveryZoneId` and slot `Id` | 200, 5 hits, 93 KB |
| productbff `/favoritter` with the customer JWT | 200, 219 favourite products, 274 KB |
| `AddToBasket` without XSRF header or bearer | 200. XSRF is not enforced for non-browser clients either |
| `addToExisting: true` | 1 + 2 = 3 |
| New session built only from saved cookies | JWT gets `debitorId` again and the basket reads fine. No re-login needed |

The login response returned `DeliveryZoneId: 1`, but the basket reported zone `4` (the account's
real zone). Take the delivery context from `GetBasket`, not from the login response.

## Endpoint reference

Searching and filling a basket needs about ten endpoints. "Probed" means we called it anonymously
from Denmark on 2026-09-27. "Tested" means we called it logged in the same day, from the browser
and/or a Python script, and restored the basket afterwards. "Repos" means it appears in existing
clients' code. `www` is `https://www.nemlig.com`, `gw` is `https://webapi.prod.knl.nemlig.it`.
Example responses: see [`fixtures/`](fixtures/).

| Purpose | Call | Auth | Key inputs | Status |
| --- | --- | --- | --- | --- |
| Bootstrap context | `GET www/?GetAsJson=1` | None | Returns `Settings.TimeslotUtc`, `DeliveryZoneId`, `CombinedProductsAndSitecoreTimestamp`, `SitecorePublishedStamp`, `UserId` | Probed |
| Site routes and stamps | `GET www/webapi/v2/AppSettings/Website` | None | 49 keys, such as `BasketPageUrl` and the timestamps | Probed |
| Product search | `GET gw/searchgateway/api/search` | Bearer | `query`, `take`, `skip`, **`timeslotUtc` and `deliveryZoneId` required** (500 without them), optional `timestamp`, `recipeCount`, `includeFavorites`, `TimeSlotId`. Prices and deals follow `timeslotUtc` (see gotchas) | Tested |
| Autocomplete | `GET gw/searchgateway/api/quick` | Bearer | `query`, `correlationId` | Probed |
| Product details | `GET www/<product-slug>?GetAsJson=1` | None | Slug from search `Url`; data in `content[TemplateName=productdetailspot]` | Probed |
| Offers and favourites | `GET gw/productbff/api/web/page` | Bearer (customer JWT for favourites) | `path` (`/tilbud`, `/favoritter`), `timeslotId`. Offers follow `timeslotId`, not the reserved slot | Tested (`/tilbud` returned 2 MB) |
| Delivery slots | `GET www/webapi/v2/Delivery/GetDeliveryDays` | None (default zone) or cookie | `startDate` (`undefined` means today), `days`, `showForSubscriptions`. Slot `Availability`: 0 = available, 1 = past deadline, 2 = sold out, 3 = not active | Probed |
| Reserve slot | `POST www/webapi/Delivery/TryUpdateDeliveryTime?timeslotId=`, then `UpdateDeliveryTime?timeslotId=` if prices change | Cookie | The response has `IsReserved`, `PriceChangeDiff`, `ProductLineDiffs[]` and `MinutesReserved`. When the slot changes the basket's prices, `Try…` only reports the diffs; `UpdateDeliveryTime` confirms | Tested |
| Current user | `GET www/webapi/user/GetCurrentUser` | Cookie | Returns `DebitorId`, `Email`, addresses, `UpcomingOrder`. There is no `IsLoggedIn` field | Tested |
| Read basket | `GET www/webapi/basket/GetBasket` | Cookie only (no bearer, no `Version`) | `Lines[]`, `TotalPrice`, `IsMinTotalValid`, `DeliveryTimeSlot`, `TimeslotUtc`, `DeliveryZoneId`, `ValidationFailures`, plus personal data | Tested |
| Set line quantity | `POST www/webapi/basket/AddToBasket` | Cookie | `{ProductId, quantity, AffectPartialQuantity, disableQuantityValidation}`. Quantity is **absolute**, 0 removes. Returns the full basket | Tested |
| Add on top of the current quantity | Same endpoint, `{productId, quantity, addToExisting: true}` | Cookie | **Adds.** 1 + 2 = 3, then +1 = 4. A negative quantity subtracts (3 − 1 = 2) | Tested |
| Remove a quantity-0 line | Same endpoint, `{ProductId, quantity: 0, AffectPartialQuantity: true}` | Cookie | Needed for sold-out lines left at quantity 0 (see gotchas) | Tested |
| Clear basket | `POST www/webapi/basket/ClearBasket` | Cookie | Empties the lines. **The reserved slot stays reserved** | Tested |
| Order history | `GET www/webapi/order/GetBasicOrderHistory?skip&take` | Cookie | Numeric `Id` and `OrderNumber` per order. Delivered orders showed `Status: 3` | Tested |
| Order lines | `GET www/webapi/v2/order/GetOrderHistory/{Id}` | Cookie | `Lines[].ProductNumber` works as a basket product id | Tested |
| Latest order | `GET www/webapi/order/GetLatestOrderHistory` | Cookie | `includeCanceled` | Repos |
| Reorder in one call | `POST www/webapi/order/CopyOrder` | Cookie | `{OrderNumber: "<numeric Id>"}`. **The field takes the numeric `Id`**; the real order number gives `400 Order not found`. It merges the whole order into the basket additively (18/18 lines) and keeps the reserved slot | Tested |
| Shopping lists | `POST www/webapi/ShoppingList/CreateShoppingList?name=`, `UpdateProductInShoppingList?listId&productId&amount`, `GET getShoppingList?listId`, `GetShoppingLists?skip&take`, `POST RemoveShoppingList?listId` | Cookie | `amount` is absolute. All parameters go in the query string, with no body | Tested |
| List to basket in bulk | `POST www/webapi/basket/addShoppingListToBasket` | Cookie | `{ListId, ConfirmMissingProducts: false}`. **Adds** to basket quantities (1 + 2 = 3) and returns the full basket | Tested |

Out of scope on purpose: `Order/PlaceOrderLoggedIn` (charges a saved card and needs the password),
`Checkout/GetCreditCards`, `CancelOrder` and account management.

Error bodies on `/webapi` look like
`{"ErrorCode": 8, "ErrorMessage": "Order not found", "DeveloperMessage": "…", "ComplexError": null, "Data": {…}, "ValidationFailures": []}`
with HTTP 400.

## Gotchas and pitfalls

The most dangerous failures are silent. An expired session looks like an empty, anonymous basket,
not an error.

- **Expiry fails silently.** An expired or cookie-less token gets `200` with an empty basket and no
  favourites. Never wait for a 401. Check the JWT's `exp` and `debitorId` before each call (emilbm).
- **`AddToBasket` sets the quantity; it does not add.** Posting 1 twice leaves 1. Use
  `addToExisting: true` for real increments (tested).
- **Never retry a write blindly.** A retried basket write can double a line if it isn't absolute.
  tobiasdosdal retries only GETs, on 408/425/429/5xx with backoff.
- **Queue-it on page routes.** A browser-like `User-Agent` on `/?GetAsJson=1` got `302` to
  `nemlig.queue-it.net` (reproduced 2026-09-27). `/webapi/*` was unaffected. Use a plain
  non-browser UA.
- **Search needs delivery context.** Without both `timeslotUtc` and `deliveryZoneId` the gateway
  returns `500` with an empty body. Prices and stock depend on the slot and zone, so use the
  logged-in basket's values once available.
- **Responses are huge.** 3 search hits came back as 90 KB, because they include
  `TopUpOrderProducts`, recipes, ads and facets. `/tilbud` on productbff is 2 MB. Trim before
  anything reaches an LLM's context.
- **Personal data comes back in basket and order responses.** They include name, street address
  and phone number. kraenhansen redacts these before they reach the model.
- **Two id spaces for orders.** The numeric `Id` is used for order lines, PDFs and, despite the
  field name, `CopyOrder`. `OrderNumber` is used for `GetOrderHistoryByOrderNumber`.
- **The `Version` header drifts.** The repos hard-code `11.201.0` or `11.235.1`. The live value is
  in `main.js` (`version:"11.235.1"`) and the site build is `b1.0.9742.33427`.
- **Terms of use.** Every project is unofficial. Keep request volume human-scale and stop at the
  basket. Checkout stays in the browser.

Found in logged-in testing on 2026-09-27:

- **Sold-out lines stay at quantity 0.** After `CopyOrder`, an out-of-stock product stayed in
  `Lines` with `Quantity: 0` and `CheckoutHistoricalRecord.AvailabilityStatus: 1`. A plain
  `quantity: 0` did not remove it; `AffectPartialQuantity: true` did. Filter or clean up
  zero-quantity lines.
- **`CopyOrder` takes the numeric order `Id` in a field named `OrderNumber`.** Sending the real
  order number gives `400 {ErrorCode: 8, "Order not found"}`. Its response carried one
  `ValidationFailures` entry (`Group: 1`), which the site shows as a "changes to basket" dialog.
- **XSRF was not enforced**, neither for same-origin browser calls nor for the script.
  `AddToBasket` without `X-XSRF-TOKEN` returned 200. Send it anyway; it costs nothing.
- **The `.ASPXAUTH` cookie is HttpOnly.** It can't be copied out of the browser with JavaScript. A
  standalone client logs in itself (which works, see above).
- **Order status codes differ from eisbaw's notes.** Delivered orders showed `Status: 3`, not `4`.

## What our client needs to interface with

The minimum surface for "search and fill the basket" is two hosts, one cookie jar, a
self-refreshing JWT and about eight endpoints. Nothing here requires a browser: a plain HTTP
script login was tested end to end.

**Must handle**

- A persistent cookie jar for `www.nemlig.com`: `.ASPXAUTH`, the XSRF cookies and the basket keys.
- A JWT cache keyed on `exp`, refreshed from `/webapi/Token`, with the `debitorId` check that tells
  a customer token from an anonymous one.
- The XSRF header on mutating `/webapi` calls (not enforced today, but the site sends it).
- Delivery context (`TimeslotUtc`, `DeliveryZoneId`, slot `Id`) from `GetBasket` (logged in) or the
  bootstrap page (anonymous), passed to search and productbff.
- Endpoints: bootstrap, search, quick search, product details, get basket, set quantity (absolute
  and `addToExisting`), clear basket, order history and order lines. Delivery slots, reservation,
  `CopyOrder` and shopping lists are optional.
- Output trimming and personal-data redaction before results reach Claude.

**Must avoid**

- Browser user agents on page routes (Queue-it).
- Blind retries of writes, and anything under `Checkout/*` or `PlaceOrder*`.

**Verified with a real account**

- [x] Plain HTTP login works (a `requests` script logged in and every API worked, contradicting
  emilbm's browser-only claim)
- [x] `AddToBasket` with `addToExisting: true` increments, and a negative quantity decrements
- [x] `CopyOrder` (numeric `Id`) and `addShoppingListToBasket` both merge additively into the basket
- [x] `/webapi` calls don't need `Version`/`Platform` headers: reads need only the cookie, and
  writes worked without them

**Still untested**

- JWT refresh on real expiry in a long-running process (only a fresh session from saved cookies
  was tested)
- What a wrong password returns
- Whether a script login signs the browser session out
- Rate limits
- `ClearBasket`
- The meaning of `CopyOrder`'s `ValidationFailures` `Group: 1`

## Findings while building the client (2026-09-27)

Probed with the account while writing `src/nemlig/`. Read-only, or reverted afterwards.

- **Wrong password:** `POST /webapi/login` returns `400 {ErrorCode: 4, ErrorMessage: "E-mail
  og/eller password er ikke gyldig …"}`.
- **Product page by id:** `www/<id>?GetAsJson=1` returns an unrelated page, but any
  `<text>-<id>` path such as `/p-5050406` answers `301` to the canonical slug. The redirect drops
  the query string, so `GetAsJson=1` must be sent again. An unknown id redirects to
  `/?search=p#404`.
- **Order history paging:** `skip` is a **1-based page number** and `take` the page size, not an
  offset. `skip=0` and `skip=1` both return page 1.
- **Shopping list paging:** unlike order history, `GetShoppingLists`' `skip` counts lists, not
  pages, and the site sends `skip=0` for the first page. With one list, `take=1&skip=1` is empty
  but `take=2&skip=1` still returns it, so the server seems to round `skip` down to a page
  boundary. `NumberOfPages` is 0 on an empty page.
- **Offers and deals depend on the delivery slot** (tested 2026-09-29). With 30/09 16-17 and
  06/10 07-08 reserved in turn, about 1130 of about 1400 `/tilbud` products appeared for only one
  of the two slots, and 132 changed price or deal. Search deals changed too ("3 for 38 kr" became
  "3 for 50 kr"), while search `Price` stayed the same.
- **productbff reads the slot from `timeslotId` alone.** With 30/09 reserved, `timeslotId` of
  06/10 returned exactly 06/10's offers. Without `timeslotId`, `/tilbud` and `/favoritter` still
  return 200 but use the default slot, so leaving it out silently gives the wrong offers.
- **Search reads the slot from `timeslotUtc`.** `TimeSlotId` alone does not move it: with 30/09's
  `timeslotUtc` and 06/10's `TimeSlotId`, results matched neither slot, and 06/10's `timeslotUtc`
  without any `TimeSlotId` matched 06/10 exactly. `timeslotUtc` can be built from a
  `GetDeliveryDays` slot: `2026100605-60-1020` is the slot start as a UTC `yyyyMMddHH`, its length
  in minutes, and the minutes from the ordering `Deadline` to the start (slot hours and deadlines
  are Danish time). That matched every value the basket and bootstrap returned. Whether the lead
  time counts real minutes or wall-clock minutes across a DST change is unknown.
- **The basket always has a slot.** With no slot chosen, `DeliveryTimeSlot` is the earliest
  one, with `Reserved: false`, and `TimeslotUtc` matches it.
- **Offers:** `/tilbud` returned 1613 products in 15 sections, 1331 unique.
- **Offer fields** (probed 2026-09-30, 1350 unique in 24 sections): `tracking.item_category`
  is the top category as an ASCII slug (`Koed`, `Fisk-og-skaldyr`, `Frost`), and
  `item_category2` is the sub category (`Oksekoed`; `Frost` has `Koed` and
  `Frugt-og-groent`). 864 products have `priceOriginal` and `priceDiscount` (øre), a
  before-price. Most discounts are 15–42%. Multi-buy deals are only in
  `campaignLines[].text`: `"Mix 3 stk. 38,-"`, `"2 stk. 70,-"` or `"Mix 3 stk. 112,50 kr."`.
  These have no `priceOriginal`, and the badge says `Spar op til`. Other lines are labels
  (`Priskup`, `Skarp pris`). Top-level `Frugt-og-groent` on offer is mostly dried fruit and
  nuts. The model maps the category to `Koed/Oksekoed` and computes `discount` from the
  before-price or the deal.
- **`Campaign` on search products** is a deal, not a discounted `Price`: `{CampaignPrice: 50,
  MinQuantity: 3, Type: "ProductCampaignMixOffer"}` means 3 for 50 kr. `Price` stays the
  regular unit price. `DiscountItem: true` marks nemlig's budget "Discount" range, not an offer.
- **Basket lines are full products.** Each line in `GetBasket` has the search fields too
  (`UnitPriceCalc`, `UnitPriceLabel`, `Labels`, `Campaign`, `SubCategory`), but the basket and
  product pages spell the unit label `kr./Kg.` where search says `kr/kg`. The models normalise
  every label to the search spelling (`kr/kg`, `kr/l`, `kr/stk`).
- **Shopping lists:** `CreateShoppingList` returns the new list. `UpdateProductInShoppingList`
  returns `{List: {…}}`, and amount 0 removes the product. `RemoveShoppingList` returns an empty
  200. A missing list gives `400 {ErrorCode: 2}`.
- **`ClearBasket` and `TryUpdateDeliveryTime`** are body-less POSTs. The client reads the basket
  back after both. Tested 2026-09-29: `TryUpdateDeliveryTime` reserved the slot, and
  `ClearBasket` on an empty basket left the reservation in place (other clients say it drops it).
  There is no known call that releases a reservation.
- **`TryUpdateDeliveryTime` is a preview when prices change** (tested 2026-09-30). With a basket
  whose prices differ in the new slot, it answered `IsReserved: false`, `MinutesReserved: 0`, no
  message, and `ProductLineDiffs[]` of `{ProductName, Undeliverable, AmountDiff}`. The site shows
  these for the user to accept. `PriceChangeDiff` is unsigned (91.21 while the lines summed to
  -91.21), and `IsPriceDiffChangePositive` was `false` for a cheaper basket. The same
  `UpdateDeliveryTime?timeslotId=` POST then reserved it (`IsReserved: true`,
  `MinutesReserved: 20`, empty diffs), and the basket moved to the new prices.

## Sources

- [eisbaw/nemlig_cli: nemlig_api.md](https://github.com/eisbaw/nemlig_cli/blob/main/nemlig_api.md): the most complete written API notes, with more field-level detail than this file
- [mikkelkaas/nemligmcp](https://github.com/mikkelkaas/nemligmcp): session, search context, delivery, Queue-it UA note
- [emilbm/nemlig-mcp](https://github.com/emilbm/nemlig-mcp): browser login, `debitorId`, silent expiry, productbff
- [tobiasdosdal/Nemlig.com-CLI](https://github.com/tobiasdosdal/Nemlig.com-CLI): current `Version`, retry policy, sanitized network capture
- [kraenhansen/nemlig-mcp](https://github.com/kraenhansen/nemlig-mcp): endpoint allowlist, personal-data redaction, batched quantity writes
- [LordMike/MBW.Nemlig2MQTT](https://github.com/LordMike/MBW.Nemlig2MQTT): C# client (login, order history, delivery spot)
- [mhattingpete/nemlig-shopper](https://github.com/mhattingpete/nemlig-shopper), [simontjell/nemlig-cli](https://github.com/simontjell/nemlig-cli), [schourode/nemlig](https://github.com/schourode/nemlig)
- Our own anonymous probes, a read of `www.nemlig.com/scom/dist/main.js` (build `b1.0.9742.33427`), logged-in browser tests and a logged-in script, 2026-09-27
