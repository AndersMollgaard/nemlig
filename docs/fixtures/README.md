# Response fixtures

Real nemlig.com responses captured on 2026-09-27 by
[`research/capture_fixtures.py`](../../research/capture_fixtures.py). Use them as shape references
when modelling responses, and as test fixtures.

Each file is `{"_note": "<request and remarks>", "response": <trimmed body>}`.

- **Trimmed:** every array keeps only its first 2 items, and strings are cut to 300 characters.
  Counts such as `NumFound` still describe the full response.
- **Redacted:** address blocks, names, email, phone, `DebitorId`/`memberId`, `KVHX`, order numbers,
  basket GUIDs, notes to the driver and shopping-list names are replaced with `"<redacted>"`. The
  capture script ends with a check that none of the account's profile strings appear in any file.
- **Real data:** product lines in `basket.json`, `order_lines.json` and `productbff_favourites.json`
  are real items from the account.

| File | Request |
| --- | --- |
| `bootstrap_getasjson.json` | `GET www/?GetAsJson=1`: delivery context and timestamps (anonymous) |
| `appsettings_website.json` | `GET www/webapi/v2/AppSettings/Website` |
| `token_anonymous_claims.json` | Decoded JWT from `/webapi/Token` before login |
| `token_customer_claims.json` | Decoded JWT after login (`debitorId` claim present) |
| `login_response.json` | `POST www/webapi/login` |
| `current_user.json` | `GET www/webapi/user/GetCurrentUser` |
| `basket.json` | `GET www/webapi/basket/GetBasket`, also the response shape of `AddToBasket` and `addShoppingListToBasket` |
| `search.json` | `GET gw/searchgateway/api/search` |
| `search_quick.json` | `GET gw/searchgateway/api/quick` |
| `product_details.json` | `GET www/<slug>?GetAsJson=1`, `productdetailspot` content |
| `productbff_favourites.json` | `GET gw/productbff/api/web/page?path=/favoritter` |
| `delivery_days_anonymous.json` | `GET www/webapi/v2/Delivery/GetDeliveryDays` |
| `order_history.json` | `GET www/webapi/order/GetBasicOrderHistory` |
| `order_lines.json` | `GET www/webapi/v2/order/GetOrderHistory/{Id}` |
| `shopping_lists.json` | `GET www/webapi/ShoppingList/GetShoppingLists` |
| `error_copyorder_not_found.json` | The standard `/webapi` error envelope (HTTP 400) |

`www` = `https://www.nemlig.com`, `gw` = `https://webapi.prod.knl.nemlig.it`.
