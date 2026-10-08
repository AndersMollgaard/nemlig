# The `nemlig` command

`uv sync` installs a `nemlig` command (also `python -m nemlig`), and `uv tool install --editable .`
puts it on PATH. It is written to be driven by an agent: every command prints one JSON document
on stdout, and `nemlig --help` explains the workflow. Add `--text` for a compact human view.

```sh
nemlig search "havregryn" --limit 5       # pick a product "id" from the results
nemlig --text search mælk æg "rugbrød"    # several queries, run in parallel
nemlig basket add 5050406:2 5043017        # add 2 of one product and 1 of another
nemlig basket set 5050406:1                # absolute quantity; 0 removes
nemlig --text basket                       # lines, totals, minimum order, delivery slot
```

## Commands

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
| `setup [--agent {claude,codex}]... [--user] [--remove]` | Offline, no login. Makes the skills in the repo's `.claude/skills/` available to the agents, in sessions started in the repo: Claude Code reads them where they are, and Codex gets a link per skill in `.agents/skills/` (gitignored). `--user` links them into the user's skill folders instead, `~/.claude/skills/` and `~/.agents/skills/`, so every session of the agent loads them. Without `--agent` it sets up both agents, or with `--user` each agent whose home exists (`~/.claude`, `~/.codex`), and Claude when neither does. It makes symlinks, or on Windows a directory junction when symlinks need Developer Mode. Anything already there that isn't its own link is left alone and reported. It also creates `preferences.toml` from `preferences.example.toml` when missing, and reports whether `.env` has credentials. Safe to run again. `--remove` deletes only the links that point into this repo. It needs the cloned repo, because the skills aren't in the wheel |

## Behaviour

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
  per session at a time. If one fails, the error lists the items that were already `applied`,
  so an agent can recover without adding twice.
- **Errors** go to stderr as `{"error": "<class>", "message": ...}`. Exit codes: 0 ok, 1
  nemlig.com or network error (also `delivery reserve` when the slot isn't reserved), 2 bad
  usage, 3 not logged in or login rejected.
- **Credentials** come from `NEMLIG_USER` / `NEMLIG_PASS` in the environment, `--env-file`
  (or `NEMLIG_ENV_FILE`), or `.env` in the repo root, in that order. The session is saved as
  with the library (`~/.config/nemlig/session.json`); `--no-session` turns that off.
- **Preferences** live in `preferences.toml` in the repo root (or `NEMLIG_PREFS_FILE`). It holds
  free text for the agent (household, diet, always, budget) and `[[keep]]` and `[[avoid]]`
  rules. A rule matches when every field it sets matches: `id`, `brand` (ignoring case) and part
  of the `name`. Start from `preferences.example.toml`, or let `nemlig setup` copy it.
- **The restock model** is a smoothed table of how often this household bought a group, by its
  recent purchase rate and how due it is. Fancier models were tested against it on the order
  history (logistic regression, splines, gradient boosting, isotonic regression on the rate,
  a gap-based renewal model, a burn-rate model). None gained more than about 0.01 in average
  precision, so the table stays.
