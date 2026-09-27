# nemlig

A client for [nemlig.com](https://www.nemlig.com), the Danish online grocery store. It is a
Python library to search for products and fill the basket from a script, and later from a CLI
or an MCP server.

Nemlig has no public API. This project talks to the same JSON endpoints the nemlig.com website
uses, so it is unofficial and may break when the site changes.

## Scope

- **In:** product search and details, reading and changing the basket, order history (for
  reordering), and delivery timeslots.
- **Out:** placing orders, payment, and anything under checkout. Checkout always happens in the
  browser.

## How nemlig.com is put together

- `www.nemlig.com`: login, basket, orders and delivery under `/webapi/*`, plus page data via
  `?GetAsJson=1`. It authenticates with the `.ASPXAUTH` session cookie. The site also sends an `X-XSRF-TOKEN`
  header on writes, but it wasn't enforced in our tests.
- `webapi.prod.knl.nemlig.it`: product search (`/searchgateway`) and offers and favourites
  (`/productbff`). It authenticates with a 5-minute bearer JWT from `www.nemlig.com/webapi/Token`.

The full investigation is in [`docs/nemlig-api.md`](docs/nemlig-api.md). It covers existing
community projects, the auth flow, an endpoint reference, pitfalls and what is still untested. It
is a snapshot of the living doc
[Nemlig.com web API: investigation of existing clients](https://claude.ai/code/artifact/23811d05-5483-4b42-822a-27a9523c75e3).

## Install

```sh
uv sync            # creates .venv with the package and dev tools
```

## Quickstart

```python
from nemlig import NemligClient

# Reads NEMLIG_USER / NEMLIG_PASS from the environment or .env. Logs in lazily, and saves the
# session cookies to ~/.config/nemlig/session.json so the next run skips the login.
with NemligClient.from_env() as nc:
    hits = nc.search("havregryn", limit=5)
    for p in hits.products:
        print(p.id, p.name, p.price, p.offer)

    nc.add_to_basket(hits.products[0].id, 2)   # adds on top of the current quantity
    basket = nc.set_quantity(hits.products[0].id, 1)  # absolute; 0 removes
    print(basket.total_price, basket.is_min_total_valid)
```

Search, suggestions, product pages, delivery days and offers also work without an account:
`NemligClient()` with no credentials and no saved session.

## Client API

All methods are synchronous and return pydantic models (snake_case, JSON-serializable via
`model_dump(mode="json")`). Personal data in nemlig's responses (names, addresses, email, phone,
driver notes, order numbers) is never mapped into the models.

| Area | Methods |
| --- | --- |
| Session | `login()`, `logout()`, `is_logged_in()`, `get_account()`, `get_delivery_context()` |
| Search | `search(query, limit, offset)`, `suggest(query)`, `get_product(id_or_slug)` |
| Basket | `get_basket()`, `add_to_basket(id, qty)` (additive, negative subtracts), `set_quantity(id, qty)` (absolute), `remove_from_basket(id)`, `remove_sold_out()`, `clear_basket()` |
| Delivery | `get_delivery_days(days, start)`, `reserve_slot(slot_id)` |
| Orders | `get_orders(limit, page)`, `get_order(order_id)`, `reorder(order_id)` |
| Favourites and offers | `get_favourites()`, `get_offers(limit)` |
| Shopping lists | `get_shopping_lists()`, `get_shopping_list(id)`, `create_shopping_list(name)`, `set_shopping_list_item(list_id, product_id, qty)`, `delete_shopping_list(id)`, `add_shopping_list_to_basket(id)` |

Behaviour worth knowing:

- **Expired sessions.** nemlig doesn't return 401 for an expired session; it silently answers
  as an anonymous user with an empty basket. Before every account call the client checks that
  its bearer token carries a customer id. If not, it logs in again (when it has credentials) or
  raises `NotLoggedInError`.
- **Writes are never retried.** Only GETs are retried (408/425/429/5xx, with backoff), because
  `add_to_basket` is not idempotent.
- **Errors.** `ApiError` (with nemlig's `error_code`), `AuthError` (wrong username or password),
  `NotLoggedInError`, `QueueItError`, all subclasses of `NemligError`.
- **Session file.** Override with `session_file=` or `NEMLIG_SESSION_FILE`; `persist=False`
  keeps the session in memory only. It is written with mode 600.
- `clear_basket()` and `reserve_slot()` follow other clients' usage and read the basket back
  afterwards, but have not been exercised against the real site.

## Tests

```sh
uv run pytest                          # offline, against the fixtures in docs/fixtures/
NEMLIG_LIVE=1 uv run pytest -m live    # against nemlig.com with the .env account
uv run ruff check . && uv run ruff format --check .
```

The live tests only read, plus two reverted writes: a basket quantity change that is set back
afterwards, and a temporary shopping list that is deleted again.

## Later

The client is meant to sit under a CLI and an MCP server. The flat method surface maps directly
onto commands or tools, and the models are already trimmed for an LLM's context. Both would
likely ship as optional extras (`nemlig[cli]`, `nemlig[mcp]`).

## Repo layout

| Path | What |
| --- | --- |
| `src/nemlig/client.py` | `NemligClient`, the public API |
| `src/nemlig/models/` | Response models, built from the API's dicts |
| `src/nemlig/_http.py`, `auth.py`, `session.py` | Transport and retries, login and JWT, cookie persistence |
| `tests/` | Offline unit tests; `tests/live/` hits the real site |
| `docs/nemlig-api.md` | API investigation and endpoint reference. **Start here** for the API |
| `docs/fixtures/` | Trimmed, redacted real responses for each endpoint (shape references and test data) |
| `research/` | The original probe scripts (`login_probe.py`, `capture_fixtures.py`). Research tools, not the client |

## Credentials

`NEMLIG_USER` and `NEMLIG_PASS` go in `.env` in the repo root. It is listed in `.gitignore`;
never commit it.
