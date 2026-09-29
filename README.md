# nemlig

A client for [nemlig.com](https://www.nemlig.com), the Danish online grocery store. It is a
Python library to search for products and fill the basket from a script or the command line.

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

    nc.add_to_basket(hits.products[0].id, 2)  # adds on top of the current quantity
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
| Search | `search(query, limit, offset, slot_id)`, `search_many(queries, limit, offset, slot_id)` (parallel), `suggest(query)`, `get_product(id_or_slug)` |
| Basket | `get_basket()`, `add_to_basket(id, qty)` (additive, negative subtracts), `set_quantity(id, qty)` (absolute), `remove_from_basket(id)`, `remove_sold_out()`, `clear_basket()` |
| Delivery | `get_delivery_days(days, start)`, `reserve_slot(slot_id)`, `get_slot_context(slot_id)` |
| Orders | `get_orders(limit, page)`, `get_order(order_id)`, `reorder(order_id)` |
| Favourites and offers | `get_favourites()`, `get_offers(limit, slot_id)` |
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
  keeps the session in memory only. It is written with mode 600, and records a hash of the
  username so a client with credentials never reuses another account's session.
- **Not thread-safe.** Use one client per thread.
- **Prices and offers depend on the delivery slot.** Search and offers use the basket's slot
  (with none chosen, nemlig picks the earliest), or the site's default when anonymous. Pass
  `slot_id` to price them for another slot without reserving it.
- `clear_basket()` empties the lines but keeps the reserved slot. Nothing releases a slot.

## CLI

`uv sync` installs a `nemlig` command (also `python -m nemlig`). It is written to be driven by
an agent: every command prints one JSON document on stdout, and `nemlig --help` explains the
workflow. Add `--text` for a compact human view.

```sh
nemlig search "havregryn" --limit 5       # pick a product "id" from the results
nemlig --text search mælk æg "rugbrød"    # several queries, run in parallel
nemlig basket add 5050406:2 5043017        # add 2 of one product and 1 of another
nemlig basket set 5050406:1                # absolute quantity; 0 removes
nemlig --text basket                       # lines, totals, minimum order, delivery slot
```

| Command | What |
| --- | --- |
| `search QUERY... [--limit] [--offset] [--slot] [--cheaper-than ID...]`, `suggest QUERY`, `product ID_OR_SLUG` | Find products. Several queries run in parallel and print a list. `--cheaper-than` takes one basket product id per query and keeps only what costs less per kg, l or piece (not per pack), offers included |
| `basket [show]`, `basket add ID[:QTY]...`, `basket set ID:QTY...`, `basket remove ID...`, `basket remove-sold-out`, `basket clear --yes` | The basket |
| `delivery [--days] [--start] [--available]`, `delivery reserve SLOT_ID` | Timeslots |
| `orders [--limit] [--page]`, `orders show ID`, `orders reorder ID` | Order history |
| `favourites`, `offers [--limit] [--slot]` | Favourites and offers |
| `lists`, `lists show ID`, `lists create NAME`, `lists set LIST_ID ID:QTY...`, `lists delete ID --yes`, `lists to-basket ID` | Shopping lists |
| `status`, `login`, `logout` | Session |

- **Output.** JSON with null and empty fields, image URLs and slugs left out. Basket changes
  print the resulting basket. Basket lines in JSON carry the unit price (`kr/kg`, `kr/l`),
  labels and offer, as search results do; `--text` leaves them out. A search product on offer
  also has `offer_unit_price`, the unit price when buying the offer's quantity.
- **Several items per call.** `basket add/set/remove` and `lists set` apply their items in order.
  If one fails, the error lists the items that were already `applied`, so an agent can recover
  without adding twice.
- **Errors** go to stderr as `{"error": "<class>", "message": ...}`. Exit codes: 0 ok, 1
  nemlig.com or network error, 2 bad usage, 3 not logged in or login rejected.
- **Credentials** come from `NEMLIG_USER` / `NEMLIG_PASS` in the environment, `--env-file`
  (or `NEMLIG_ENV_FILE`), `./.env`, or `~/.config/nemlig/.env`, in that order. The session is
  saved as with the library; `--no-session` turns that off.

## Agents

`AGENTS.md` (imported by `CLAUDE.md`) is the brief for coding agents. The skill
[`.claude/skills/nemlig-shopping`](.claude/skills/nemlig-shopping/SKILL.md) is the shopping
playbook: compact `--text` output, one multi-query `search` and one `basket add` per batch, how to choose
products, and how to recover from errors. Claude Code picks it up automatically inside this repo.
[`nemlig-cheaper`](.claude/skills/nemlig-cheaper/SKILL.md) builds on it: it compares unit
prices for what is in the basket and proposes cheaper swaps. Both read household preferences
from `~/.config/nemlig/preferences.md`.

To shop from any directory, install the command and the skills for your user:

```sh
uv tool install --editable .                       # puts `nemlig` on PATH
ln -s "$PWD/.claude/skills/nemlig-shopping" ~/.claude/skills/nemlig-shopping
ln -s "$PWD/.claude/skills/nemlig-cheaper" ~/.claude/skills/nemlig-cheaper
cp .env ~/.config/nemlig/.env                      # credentials, if not in the environment
```

## Tests

```sh
uv run pytest                          # offline, against the fixtures in docs/fixtures/
NEMLIG_LIVE=1 uv run pytest -m live    # against nemlig.com with the .env account
uv run ruff check . && uv run ruff format --check .
```

The live tests only read, plus two reverted writes: a basket quantity change that is set back
afterwards, and a temporary shopping list that is deleted again.

## Repo layout

| Path | What |
| --- | --- |
| `src/nemlig/client.py` | `NemligClient`, the public API |
| `src/nemlig/cli.py` | The `nemlig` command |
| `src/nemlig/models/` | Response models, built from the API's dicts |
| `src/nemlig/_http.py`, `auth.py`, `session.py` | Transport and retries, login and JWT, cookie persistence |
| `tests/` | Offline unit tests; `tests/live/` hits the real site |
| `docs/nemlig-api.md` | API investigation and endpoint reference. **Start here** for the API |
| `docs/fixtures/` | Trimmed, redacted real responses for each endpoint (shape references and test data) |
| `research/` | The original probe scripts (`login_probe.py`, `capture_fixtures.py`). Research tools, not the client |

## Credentials

`NEMLIG_USER` and `NEMLIG_PASS` go in `.env` in the repo root. It is listed in `.gitignore`;
never commit it.

## Acknowledgements

Nemlig has no public API. These community projects documented it first, and this client builds on
what they worked out:

- [eisbaw/nemlig_cli](https://github.com/eisbaw/nemlig_cli): the API notes (`nemlig_api.md`) that
  laid out the login flow, both hosts and the basket semantics.
- [emilbm/nemlig-mcp](https://github.com/emilbm/nemlig-mcp): the session model, including the
  customer id in the JWT and expired sessions that silently fall back to anonymous.
- [mikkelkaas/nemligmcp](https://github.com/mikkelkaas/nemligmcp): the search context, the delivery
  slot endpoints and the Queue-it user-agent pitfall.
- [tobiasdosdal/Nemlig.com-CLI](https://github.com/tobiasdosdal/Nemlig.com-CLI): the current client
  version header, retrying only reads, and cookie-based session persistence.
