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
uv sync                                       # creates .venv with the package and dev tools
cp .env.example .env                          # your nemlig.com login
cp preferences.example.toml preferences.toml  # optional; the household's preferences
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
| Orders | `get_orders(limit, page)`, `get_all_orders()`, `get_order(order_id)`, `get_orders_many(ids)` (parallel), `reorder(order_id)`; `OrderCache().sync(client)` and `.load(client.account_key())` keep finished orders in `~/.cache/nemlig/orders` |
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
| `search QUERY... [--limit] [--offset] [--slot] [--cheaper-than ID...]`, `suggest QUERY`, `product ID_OR_SLUG` | Find products. Several queries run in parallel and print a list. `--cheaper-than` takes one basket product id per query and keeps only what costs less per kg, l or piece, offers included, and saves at least 2 kr and 5% on the line for about the same amount. Each row says how many packs and what they save (or `buy N for the offer` for a stock-up), the biggest saving first, and the `keep` and `avoid` rules in the preferences apply. `search` and `offers` remember the products they print for 12 hours (`~/.cache/nemlig/products.json`), for `dishes`. `--slot` prices for another slot; the basket's own slot costs no extra request |
| `basket [show]`, `basket add ID[:QTY]...`, `basket set ID:QTY...`, `basket remove ID...`, `basket remove-sold-out`, `basket clear --yes` | The basket. `add` also prints how many lines it added and their total |
| `delivery [--days] [--start] [--available]`, `delivery reserve SLOT_ID`, `delivery suggest [--start] [--days] [--limit]` | Timeslots. `suggest` ranks the bookable slots by the household's past delivery windows (weighted towards the same weekday and recent orders, orders on their way included) and the fee, one per day over several days, with how many recent orders were alike. `reserve` accepts the new slot's prices and prints how the basket total changed and what it can't deliver; it exits 1 when the slot isn't reserved |
| `orders [--limit] [--page]`, `orders show [ID]`, `orders reorder ID`, `orders sync` | Order history. `show` without an id shows the latest order. `sync` caches every finished order's lines in `~/.cache/nemlig/orders/<account>/` (or `NEMLIG_CACHE_DIR`), fetching only the ones not cached yet |
| `restock [--slot] [--exclude CAT...] [--no-offers]`, `restock groups`, `restock groups merge NAME KEY_OR_ID...`, `restock groups reviewed`, `restock backtest [--last N]` | The usual products due for the delivery slot, predicted from the cached order history (it syncs first; an order on its way counts as bought). Rows are split into `due`, likely enough to add, and lettered `maybe` rows to pick from, with the chance and the usual gap. Products in the basket and `avoid` matches are left out, and a less likely product on offer for the slot joins the maybes if it was bought in at least 3 orders in the last year. `groups` lists new products to review, `merge` counts several names or ids as one need (stored in `groups.json` in the repo root, or `NEMLIG_GROUPS_FILE`), and `backtest` scores the predictions on the last cached orders |
| `favourites`, `offers [--limit] [--slot] [--category C...] [--min-discount PCT] [--categories]` | Favourites and offers. `--category` keeps a top or sub category (`koed`, `kylling`; `kød` works too), `--min-discount` keeps offers at least that many percent off, and `--categories` counts the offers per category instead |
| `dishes` (spec on stdin), `dishes add CODE... [ID:QTY...]` | Price a dinner plan: the dish tables with the extras, the price per portion and the ★ set's total, from the prices `search` and `offers` printed (no request). `add` puts the picked dishes' anchors and extras in the basket, each product once. The spec format is in `src/nemlig/dishes.py` and `nemlig-dinners` |
| `lists`, `lists show ID`, `lists create NAME`, `lists set LIST_ID ID:QTY...`, `lists delete ID --yes`, `lists to-basket ID` | Shopping lists |
| `prefs`, `prefs keep [--id] [--brand] [--name] [--note]`, `prefs avoid ...` | Household preferences, and rules for products never to replace (`keep`) or never to suggest (`avoid`) |
| `status`, `login`, `logout` | Session |

- **Output.** JSON with null and empty fields, image URLs and slugs left out. Basket changes
  print the resulting basket. Basket lines in JSON carry the unit price (`kr/kg`, `kr/l`),
  labels and offer, as search results do; `--text` leaves them out. A search product on offer
  also has `offer_unit_price`, the unit price when buying the offer's quantity. Offers and
  favourites have `discount`, the percent off, from the price before the offer or a
  multi-buy deal. In `search` and `offers`, a product an `avoid` rule matches has
  `avoided: true` (`AVOID` in `--text`). The `--text` basket ends with the delivery slot and its
  id (`slot 2405499`), for `--slot`.
- **Several items per call.** `basket add/set/remove` and `lists set` apply their items in order,
  about 0.6 s each. Sending them in parallel was no faster: nemlig handles one basket request
  per session at a time.
  If one fails, the error lists the items that were already `applied`, so an agent can recover
  without adding twice.
- **Errors** go to stderr as `{"error": "<class>", "message": ...}`. Exit codes: 0 ok, 1
  nemlig.com or network error (also `delivery reserve` when the slot isn't reserved), 2 bad
  usage, 3 not logged in or login rejected.
- **Credentials** come from `NEMLIG_USER` / `NEMLIG_PASS` in the environment, `--env-file`
  (or `NEMLIG_ENV_FILE`), or `.env` in the repo root, in that order. The session is saved as
  with the library; `--no-session` turns that off.
- **Preferences** live in `preferences.toml` in the repo root (or `NEMLIG_PREFS_FILE`). It holds
  free text for the agent (household, diet, always, budget) and `[[keep]]` and `[[avoid]]`
  rules. A rule matches when every field it sets matches: `id`, `brand` (ignoring case) and part
  of the `name`. Start from `preferences.example.toml`.
- **The restock model** is a smoothed table of how often this household bought a group, by its
  recent purchase rate and how due it is. Fancier models were tested against it on the order
  history (logistic regression, splines, gradient boosting, isotonic regression on the rate,
  a gap-based renewal model, a burn-rate model). None gained more than about 0.01 in average
  precision, so the table stays.

## Agents

`AGENTS.md` (imported by `CLAUDE.md`) is the brief for coding agents. The skill
[`.claude/skills/nemlig-shopping`](.claude/skills/nemlig-shopping/SKILL.md) is the shopping
playbook: compact `--text` output, one multi-query `search` and one `basket add` per batch, how to choose
products, and how to recover from errors. Claude Code picks it up automatically inside this repo.
[`nemlig-cheaper`](.claude/skills/nemlig-cheaper/SKILL.md) builds on it: it compares unit
prices for what is in the basket and proposes cheaper swaps.
[`nemlig-dinners`](.claude/skills/nemlig-dinners/SKILL.md) makes up varied dinners around the
current offers, agrees on the anchor offers and the dishes with the user, and adds the
ingredients. [`nemlig-restock`](.claude/skills/nemlig-restock/SKILL.md) adds the usual items
that are due, predicted from the order history, and lets the user pick from the less certain
ones. [`nemlig-fill-basket`](.claude/skills/nemlig-fill-basket/SKILL.md) chains them for a
week's basket: it restocks, runs the dinners, then proposes cheaper swaps for the whole basket
in one report. [`nemlig-recipes`](.claude/skills/nemlig-recipes/SKILL.md) turns the planned
dinners into a private recipe page on claude.ai, with a card per night. The fill-basket run
starts it in the background, right after the dinners are added. The shopping skills all read the
household preferences with `nemlig prefs`, and record lasting corrections as `keep` and `avoid`
rules.

To shop from any directory, install the command and the skills for your user:

```sh
uv tool install --editable .                       # puts `nemlig` on PATH
ln -s "$PWD/.claude/skills/nemlig-shopping" ~/.claude/skills/nemlig-shopping
ln -s "$PWD/.claude/skills/nemlig-cheaper" ~/.claude/skills/nemlig-cheaper
ln -s "$PWD/.claude/skills/nemlig-dinners" ~/.claude/skills/nemlig-dinners
ln -s "$PWD/.claude/skills/nemlig-restock" ~/.claude/skills/nemlig-restock
ln -s "$PWD/.claude/skills/nemlig-fill-basket" ~/.claude/skills/nemlig-fill-basket
ln -s "$PWD/.claude/skills/nemlig-recipes" ~/.claude/skills/nemlig-recipes
```

On Windows, `ln -s` needs Developer Mode; `mklink /J` from cmd makes the same links. The
command still reads `.env`, `preferences.toml` and `groups.json` from the repo.

## Tests

```sh
uv run pytest                          # offline, against the fixtures in docs/fixtures/
NEMLIG_LIVE=1 uv run pytest -m live    # against nemlig.com with the .env account
uv run ruff check . && uv run ruff format --check .
```

The live tests only read, plus two reverted writes: a basket quantity change that is set back
afterwards, and a temporary shopping list that is deleted again.
GitHub Actions runs the offline tests on Linux and Windows on every push.

## Repo layout

| Path | What |
| --- | --- |
| `src/nemlig/client.py` | `NemligClient`, the public API |
| `src/nemlig/cli.py` | The `nemlig` command |
| `src/nemlig/models/` | Response models, built from the API's dicts |
| `src/nemlig/order_cache.py`, `restock.py`, `groups.py` | The local order cache, the restock predictions and backtest, and the product groups |
| `src/nemlig/product_cache.py`, `dishes.py` | Recently printed products, and the dinner-plan pricing behind `dishes` |
| `src/nemlig/slots.py` | The delivery-slot suggestions behind `delivery suggest` |
| `src/nemlig/_http.py`, `auth.py`, `session.py` | Transport and retries, login and JWT, cookie persistence |
| `tests/` | Offline unit tests; `tests/live/` hits the real site |
| `docs/nemlig-api.md` | API investigation and endpoint reference. **Start here** for the API |
| `docs/fixtures/` | Trimmed, redacted real responses for each endpoint (shape references and test data) |
| `.env.example`, `preferences.example.toml` | Templates for your `.env` and `preferences.toml`. Those and `groups.json` are gitignored |
| `research/` | The original probe scripts (`login_probe.py`, `capture_fixtures.py`). Research tools, not the client |

## Credentials

`NEMLIG_USER` and `NEMLIG_PASS` go in `.env` in the repo root (copy `.env.example`). It is
listed in `.gitignore`; never commit it.

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
