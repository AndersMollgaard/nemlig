# Roadmap: skills that fill the basket

The goal is for Claude to propose and fill a week's basket:

- cheaper swaps for what is in the basket,
- dinners built on the current offers,
- items that are due for restocking, predicted from order history,
- recipes for the planned dinners, as a page to cook from.

Work through the phases in order and tick the boxes as steps land. Note decisions under the step
they belong to. Phase 5 depends only on Phase 2, so it can be done before Phases 3 and 4.

## Principles

- **The CLI does the arithmetic, the skills do the judgement.** Anything that counts, filters or
  reduces data belongs in `nemlig`. Deciding whether two products are interchangeable, or what
  to cook, belongs in a skill. CLI output stays lean (see AGENTS.md).
- **One base skill, sub-skills, and an orchestrator.**
  - `nemlig-shopping` (exists) is the base: CLI conventions, basket rules, choosing products.
    Shared rules live here and only here.
  - `nemlig-cheaper`, `nemlig-dinners` and `nemlig-restock` each do one job and work on their own.
    Each starts with "load `nemlig-shopping` first if it isn't loaded" and doesn't repeat its
    rules.
  - `nemlig-fill-basket` chains them and writes the one report.
- **Narrow descriptions.** Skills trigger on their descriptions. Each sub-skill names its own
  requests ("cheaper alternatives", "what's for dinner"). Only the orchestrator claims "fill my
  basket".
- **One report when chained.** In a chained run, sub-skills hand back their changes and proposals
  instead of reporting to the user. The orchestrator reports once.
- **Personal data stays out of git.** Preferences go in the gitignored `preferences.toml` next to
  `.env` (the repo root). Cached orders go under `~/.cache/nemlig/`.
- **Never retry writes.** This rule still applies to every skill.

## Phase 0: Foundations

- [x] **Preferences file.** It holds household size, diet (e.g. no pork), hard constraints (øko
  milk), products never to swap, and a budget. Document it in the base skill. Skills read it at
  the start and add to it when the user corrects them.
  - Decided (2026-09-30, replacing a first `~/.config/nemlig/preferences.md`): `preferences.toml`
    next to `.env`, so the repo root, gitignored; `NEMLIG_PREFS_FILE` overrides. The free text
    (`household`, `diet`, `always`, `budget`) is for the skills to judge. `[[keep]]` (never
    replace) and `[[avoid]]` (never suggest) rules are enforced by `search --cheaper-than`. A
    rule matches on `id`, `brand` and part of the `name`, all that are set. `nemlig prefs` shows
    the file, and `prefs keep|avoid` appends rules, so skills don't hand-edit TOML. Only lasting
    corrections are recorded.
- [ ] **Order-history paging.** `get_orders` (`src/nemlig/client.py`) sends `page` as `skip`.
  Check live how `GetBasicOrderHistory` pages and how far back history goes. Write the findings
  in `docs/nemlig-api.md`.
- [ ] **Local order cache.** Delivered orders don't change, so cache their lines in
  `~/.cache/nemlig/orders/`. Add a command that syncs them all in parallel (e.g.
  `nemlig orders sync`). Restock needs this, and history starts building up now.
- [x] **Sub-skill conventions.** Write the handoff format and the "load base first" line once, in
  the base skill.
  - Decided: the handoff is one block with `Applied:`, `Proposed:` and `Questions:`. A chained
    sub-skill makes only the basket changes the orchestrator told it to make.

## Phase 1: `nemlig-cheaper` (skill only)

- [x] Flow: `basket`, then one query per line, all in a single `search` call. Compare `kr/kg` or
  `kr/l` for the same unit label. Drop candidates that break a label (øko, laktosefri) or a
  preference. Propose swaps with the saving per line and in total.
  - Decided: a small CLI change after all. Basket lines in JSON now carry `unit_price`,
    `unit_price_label`, `labels` and `offer` (the API already sent them), so the skill has the
    unit price it is trying to beat. `--text` basket output is unchanged. Unit labels are
    normalised to the search spelling, because the basket says `kr./Kg.`.
  - Decided: one generic query per line ("øko minimælk"), not the product name. Labels are read
    from names, with one JSON search only when a name is unclear.
- [x] Take multi-buy offers and pack sizes into account. Compare unit prices, not shelf prices.
  - Decided: a multi-buy price counts only when the swap buys the offer's quantity. "Buy 2 for
    the offer" is its own proposal, for things that keep. Savings under 2 kr or 5% are dropped.
- [x] Alone, it proposes the swaps and applies the ones the user accepts (`basket set`, `remove`,
  `add`). Chained, it returns the proposals.
  - Decided: swaps are applied with one `basket set OLD:0 NEW:QTY ...`, which is absolute and
    safe to repeat. Never `basket add`.
- [x] Only if the search output turns out too large: add a CLI filter (e.g.
  `search --cheaper-than ID`).
  - Needed after all (2026-09-29): 13 queries × 8 results in `--text` came to 8.3 KB (~3k
    tokens) and grows linearly, so a basket 5–10× larger costs 13–28k tokens per pass. Only 17
    of the 96 rows were cheaper per unit with the same unit label (1.2 KB).
  - Built as `search Q... --cheaper-than ID...`: one basket line per query, in order. It keeps
    in-stock products in the line's unit that cost less per kg, l or piece (not per pack), offers
    included. On the same
    basket it printed 2.7 KB instead of 8.3 KB. To count offers, search products gained
    `offer_unit_price` (also shown in `--text` next to the offer). Without it, Lavazza on offer
    at 147.38 kr/kg against 175.56 kr/kg would have been dropped at its 196.50 shelf price.

Done when it finds real savings on a real basket without breaking a constraint.
Live run 2026-09-29 on an 18-line basket (a reorder of a past order): up to 91 kr of 537 kr in
five swaps, with øko and fat % kept. Lessons folded into the skill: single-price offers
(`offer: 18 kr`) are not in search's `kr/kg`; non-product tags such as `Discount` and `Køl` sit in
`labels`; an empty query needs a broader retry; swaps can take the basket below the minimum
order. Single-price offers are now handled by `offer_unit_price` (see box 4).

## Phase 2: `nemlig-dinners`

- [x] **Filter offers in the CLI.** The full `/tilbud` list is over 1,000 products. Add
  `offers --category`, and a way to list the categories with counts, using `Product.category`
  from productbff (`src/nemlig/models/product.py`). Check whether productbff exposes a
  before-price. If it does, add `--min-discount`.
  - Decided (2026-09-30): productbff's `category` is now the path `Koed/Oksekoed`, with no new
    field. `--category` matches either level, ignoring case and folding `æøå` and spaces, so
    `kød` finds `Koed/*` and `Frost/Koed`. `--categories` prints the counts per top and sub
    category.
  - Decided: productbff has a before-price (`priceOriginal`, on 864 of 1350 offers). Multi-buy
    deals are only in `campaignLines` text (`Mix 3 stk. 38,-`) and are now parsed into `offer`
    (`3 for 38 kr`) and `offer_unit_price`. The new `discount` (percent) is the larger of the
    two savings. `--min-discount` filters on it, and `--text` shows `-30%` in place of the
    `Spar …` badge.
  - Sizes: meat, fish, vegetables and meat substitutes come to 131 offers (12.5 KB of text).
    At 20% off or more, 82 (7.5 KB), and at 25%, 46 (4.1 KB). The skill uses 20%.
- [x] **Spike: nemlig recipes.** Search accepts `recipeCount`. Probe whether recipes come back
  with linked products. Decide between nemlig's recipes and dishes Claude makes up. Write the
  result in `docs/nemlig-api.md`.
  - Decided (2026-09-30, by the user): Claude makes up the dishes. The recipes were not probed.
- [x] Skill flow: read preferences (household size, diet), fetch dinner-relevant offers (meat,
  fish, vegetables) and pick N dinners. Build the ingredient list and skip what is in the basket
  or was bought recently (pantry staples). Then one `search` and one `basket add`.

  - Written as `nemlig-dinners`. There are two checkpoints with the user, both as tables.
    First the anchor offers (6–10, spread across proteins) with amount, price, price per
    amount and a note. Then one table per chosen anchor with 3 dish options, their extras and
    the price per portion. An anchor that covers several nights for the household lets the
    user pick that many dishes from its table. A ★ marks a suggested set of N that varies
    cuisine, starch and method. One `search` over every dish's to-buy
    items gives the prices, and the same picks go into the one `basket add`. Pantry staples,
    basket lines and things that keep from the latest order count as at home. "Just pick"
    skips both checkpoints.
  - Decided: offers depend on the delivery slot, so the skill settles the slot before
    fetching any offers. It uses the reserved slot or the one the user named. Otherwise it asks,
    even on "just pick", because an unreserved basket slot is only the earliest free one. It
    passes `--slot` to `offers` and `search`. It reserves the slot before the `basket add`, so
    the basket is priced for the slot the offers came from. `delivery reserve` exits 0 even
    when the reservation fails, so the skill reads the output and adds nothing on
    `not reserved`. Chained without a slot, it hands back the question rather than guessing.

Done when it proposes N plausible dinners for a given slot, most of them built around offers.
Confirmed by the user on live runs (2026-09-30 and 2026-10-01). The first run filled the basket
without reserving the slot. Since then the skill reserves the slot before adding, and
`reserve_slot` confirms with `UpdateDeliveryTime` when the new slot changes prices.

## Phase 3: `nemlig-fill-basket` (orchestrator)

- [ ] Order: restock, then dinners, then cheaper. The cheaper pass reviews the whole basket,
  dinner ingredients included.
- [ ] Until Phase 4 exists, the restock step uses the base skill's "the usual" (the last 1–3
  orders).
- [ ] One final report: what was added and swapped, open questions, totals, the minimum order and
  the delivery slot.

Done when one request produces a full basket and one report, and each sub-skill still works on
its own.

## Phase 4: `nemlig-restock` (predictive)

- [ ] **Data.** Use the Phase 0 cache. Order lines have no category
  (`src/nemlig/models/orders.py`), so look each product up once, via search or product details,
  and cache its category.
- [ ] **Grouping.** Products that are basically the same count as one group ("minimælk 1 l" in any
  brand, øko or not). Claude builds the product → group mapping and it is stored in
  `~/.config/nemlig/groups.json`. Later runs only review new products.
- [ ] **Model.** A hierarchical Bayesian model of the time between purchases per group. It takes
  quantity into account: 2 units last time last longer than 1. Groups with few purchases shrink
  toward their category's prior. Output: the probability that a group runs out before the chosen
  delivery slot. Leave out groups with too few purchases or a wide posterior, rather than using a
  hard count cutoff. Decide the dependencies (pure-Python conjugate model or numpy/scipy/PyMC)
  when this phase starts.
- [ ] **Backtest.** Hold out the last k orders and predict each one from the orders before it.
  Measure precision and recall, and tune the thresholds on that.
- [ ] **CLI.** `nemlig restock [--slot ID]` prints lean lines: group, suggested product id,
  P(due), last bought. It skips what is already in the basket.
- [ ] **Skill.** Write `nemlig-restock` and plug it into the orchestrator in place of the Phase 3
  stopgap.

## Phase 5: `nemlig-recipes` (recipe artifacts)

- [ ] **Skill.** `nemlig-recipes` turns the chosen dinners into one recipe artifact: a private
  claude.ai page with a card per night. Each card has the dish, time, portions (from
  `household`), the ingredients with amounts, and the steps. Ingredients are marked as bought
  on nemlig (name and pack) or assumed at home. A dish that uses another night's leftovers
  says so. Load `artifact-design` before writing the page. It must work on a phone and print
  cleanly.
  - Input: the dishes and picks from `nemlig-dinners` in the same conversation. Alone ("make
    recipes for this week's dinners"), it takes the dishes from the user and reads the basket
    for what was bought. It doesn't guess dishes from basket lines.
  - Its description is narrow ("recipes", "recipe page", "how do I cook these"). It doesn't
    trigger on "what's for dinner".
  - Decide when building: whether a new week's recipes go to a new page or update the same one,
    and whether the page gets a shared checklist for ingredients and steps.
- [ ] **Hook in `nemlig-dinners`.** After the basket add and the report, it offers the recipes
  in one line ("Want the recipes as a page?") and loads `nemlig-recipes` on a yes. It doesn't
  publish without asking. Chained, it doesn't offer. The orchestrator asks once at the end of
  its report instead.

Done when a real dinner run ends with one yes and a recipe page that matches what went into the
basket.

## In every phase

- Offline tests run against redacted fixtures in `docs/fixtures/`. Run live tests only when
  needed.
- When CLI behaviour changes, update `README.md` and `.claude/skills/nemlig-shopping/SKILL.md`.
- `uv run pytest` and `uv run ruff check . && uv run ruff format --check .` pass.
- Tick the boxes here and note the decisions made.
