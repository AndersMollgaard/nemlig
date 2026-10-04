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
- **Personal data stays out of git.** Preferences and product groups go in `~/.config/nemlig/`.
  Cached orders go under `~/.cache/nemlig/`.
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
  - Moved (2026-10-03, after a design review): `~/.config/nemlig/preferences.toml`, next to
    `groups.json`. "Next to `.env`" depended on the working directory: run from another
    project, the skills read that project's missing file and lost `diet` and the avoid rules
    without a word, and an unrelated `./.env` hid the credentials. `./.env` now counts only
    when it sets `NEMLIG_USER`. Avoid rules are also marked `AVOID` in `search` and `offers`,
    the two commands dinners picks from, so no skill matches rules by eye.
- [x] **Order-history paging.** `get_orders` (`src/nemlig/client.py`) sends `page` as `skip`.
  Check live how `GetBasicOrderHistory` pages and how far back history goes. Write the findings
  in `docs/nemlig-api.md`.
  - Found (2026-10-01): `skip` is an offset rounded down to a whole page, so `orders --page 2`
    had been returning page 1. A `skip` past the end repeats the last page. Fixed:
    `get_orders` sends `(page - 1) * limit` and returns nothing past `NumberOfPages`, and
    `get_all_orders()` pages by 100. The whole history is there: 136 orders back to 2023-10-03.
- [x] **Local order cache.** Delivered orders don't change, so cache their lines in
  `~/.cache/nemlig/orders/`. Add a command that syncs them all in parallel (e.g.
  `nemlig orders sync`). Restock needs this, and history starts building up now.
  - Decided: `OrderCache` (`src/nemlig/order_cache.py`) writes one `Order` JSON per order under
    `~/.cache/nemlig/orders/<account>/`. `<account>` is a hash of the customer id, so two
    accounts never mix and the path reveals neither. An order is cached once its delivery
    window has ended and it isn't editable, because status 3 also covers orders not delivered
    yet. `get_orders_many` fetches lines 8 at a time, written every 16 orders, so a failed
    sync keeps its progress. The first live sync took 3.6 s for 135 orders (4,753 lines,
    1.1 MB), and a repeat took 0.8 s.
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

Order: settle the slot, restock, dinners, then cheaper. Restock goes before dinners so its lines
count as at home when the dishes are priced. Cheaper goes last because `search --cheaper-than`
compares against basket lines, so the dinner ingredients must be in the basket before it can
review them. Skill only: no CLI change is planned.

- [x] **Skill and trigger.** Write `nemlig-fill-basket`. Its description claims "fill my basket",
  "do the weekly shop" and "basket for the week", and no other skill does. The base skill's
  description says it "fills and adjusts the basket", so narrow that to adding, removing and
  adjusting items. The orchestrator works on top of the current basket and never clears it.
- [x] **Start: one question, then reserve.** Read context in one Bash call: `prefs`, `basket`,
  `orders --limit 3`. Take the slot and the number of nights from the request, the reserved
  slot and `household`. Ask once, in one message, for whatever is missing, before anything is
  added. Reserve the slot before the first add, exactly as `nemlig-dinners` step 8 does
  (choosing it counts as asking; check for `reserved:`, stop on `not reserved`, carry the
  undeliverable and price notes to the report). Every later step then uses the reserved
  slot, with no `--slot` needed.
- [x] **Restock stopgap** (replaced by `nemlig-restock` in Phase 4). The base skill's "the usual", made concrete:
  `orders show` the last 3 delivered orders in one Bash call (an order still on its way is
  skipped, and so are its products). Add the products bought in at least 2 of
  them, at last time's quantity, in one `basket add`. Skip lines already in the basket,
  sold-out products, `avoid` matches and fresh meat and fish (picking those is the dinners'
  job). Show what was added in one line above dinners' checkpoint 1, so the user sees it
  before the first question rather than only at the end.
- [x] **Dinners, with both checkpoints.** Load `nemlig-dinners` and run it chained, with the slot
  and the number of nights. It keeps both checkpoints (anchors, then dishes), skips its slot
  question because the slot is settled and reserved, adds the chosen dishes, and hands back
  instead of reporting. Changed for this:
  - `nemlig-dinners` *Chained*: keep the checkpoints, take the slot from the orchestrator
    (step 8 reduces to the add), and list the added dishes under `Applied:` with their cost.
    It used to skip the checkpoints and list dishes under `Proposed:` even when it added.
  - `nemlig-shopping` *Sub-skills*: chained means no report and no basket changes beyond what
    the orchestrator asked for. A sub-skill's own checkpoints still ask the user (it used to
    say "no questions").
  - Decided (2026-10-01, by the user): a fill-basket run goes through the dinners checkpoints.
    The user picks the anchors and the dishes; only the final report is merged.
- [x] **Cheaper over the whole basket.** Load `nemlig-cheaper` and run it chained, after the
  dinner add. It reads the basket fresh, so restocked and dinner lines are both reviewed, and
  hands back `Applied: none` and the proposals.
- [x] **One report, one question.** Built from the last basket output and the handoff blocks:
  ```
  Restocked (usual items, from your last 3 orders): 2 x Minimælk øko 1 l, Rugbrød, ... (14 lines, 312.40 kr)
  Dinners:
  - Fri: Ovnstegt kylling med citron og kartofler, 131 kr
  - Sat: ...
  Cheaper swaps (saves 38.50 kr):
  1. Hakket oksekød 8-12% 500 g, Coop → Danish Crown (2 for 90 kr): saves 9.90 kr
  Check: is there rice at home? (assumed for 2b)
  Basket: 1,148.20 kr (budget about 1,200 kr). Delivery fre. 02/10 17-18 (reserved).
  Apply the swaps (all, some, none)? Anything to drop from the restock?
  ```
  Apply accepted swaps and drops in one `basket set`, and record "never" answers as
  `nemlig-cheaper` does alone. Mention the minimum order when the basket is below it, and the
  budget only when `budget` is set.
  - Decided (2026-10-01, by the user): swaps are only proposed, and applied after one yes in
    the report.
  - Phase 5 starts the recipe page as a background subagent after the dinner add, and the
    report carries its link (it used to plan "Want the recipes as a page?" here).
- [x] **Docs.** List `nemlig-fill-basket` in the base skill's *Sub-skills* and its reserve rule
  (choosing a slot there counts as asking), and in `README.md` with its install symlink.
- [x] **Live run.** One "fill my basket for the week" on the real account, and `nemlig-cheaper`
  and `nemlig-dinners` alone again after their *Chained* sections changed.
- [x] **Hardening** (2026-10-03, after a design review). None of it adds a call to a run.
  - `delivery reserve` exits 1 when the slot isn't reserved (or another one is), instead of
    exit 0 and a `not reserved:` line every skill had to parse. The reserve procedure lives
    once, in the base skill's *Reserving a delivery slot*.
  - After reserving, the run passes `--slot` to `restock`, `offers` and `search`. It costs no
    request for the basket's own slot, and keeps the prices for the chosen slot if the hold
    lapses. The report re-reserves when the last basket output says `(not reserved)`.
  - Chained sub-skills don't read `prefs` or the text basket again (it was read 4 and 3
    times a run). Cross-skill references name sections instead of step numbers, and
    `tests/test_skills.py` parses every `nemlig` command the skills quote.
  - The restock maybes move to the closing question when dinners has no first checkpoint
    ("just pick", no dinners). The closing question asks for anything else to add, and
    everything it settles goes in one `basket set`. Restock's group merges are reported.

Done when one request produces a full basket and one report, and each sub-skill still works on
its own. Confirmed by the user on a live run (2026-10-01).

## Phase 4: `nemlig-restock` (predictive)

Replanned at the start (2026-10-01, with the user): the goal is to propose relevant items, and
the method follows the data. An exploratory backtest on the 135 cached orders showed:

- About 81% of an order's groups were bought before, which caps recall.
- Timing helps for weekly items. For slow movers it hardly helps, because their gaps vary
  widely (toilet paper: 3–38 days).
- Quantity barely matters.

So the model is simple and calibrated rather than a tight interval model. Decided with the
user: the sure items are added without asking, and the "maybe" items come as a lettered pick
list with the dinners' first checkpoint. Groups are automatic by name, and Claude merges new
products only. Offer stock-up and upcoming orders are in. Seasonality and recording "stopped
buying" are out.

- [x] **Data.** Order lines already carry a category, so no per-product lookup is needed.
  - `OrderLine.category` comes from `MainGroupName`. It was set on all 136 orders back to
    2023, in 12 values, and `Kød & fisk` is exactly fresh meat and fish.
  - `OriginalProductNumber` (substitutions) was never set, so it isn't mapped. Findings are in
    `docs/nemlig-api.md`.
  - The cache has a `format` file. `sync` refetches every order when it is older (2.9 s
    live), and exposes the ids of orders on their way (`SyncResult.upcoming_ids`, not printed).
- [x] **Grouping.** A product's group is its latest name, lowercased, without the øko mark.
  - Latest, because nemlig renamed 25 of 1104 ids ("Letmælk" → "Letmælk 1,5%").
  - nemlig names are generic with the brand in the description, so names already merge most
    brands: the last year's 584 ids made 523 groups.
  - `~/.config/nemlig/groups.json` (`NEMLIG_GROUPS_FILE`) records named groups, whose members
    are auto keys or product ids (an id wins over its name), and the reviewed ids.
    `restock groups` lists unreviewed products from the last year in groups bought twice or
    more. `merge` and `reviewed` maintain the file.
  - The first review (390 products, 14 KB of text) merged 23 clear same-need groups, e.g. æg =
    frilandsæg + skrabeæg, and agurk = agurk + agurk dansk.
- [x] **Model.** Pure Python, no new dependencies (`src/nemlig/restock.py`).
  - Per group: the purchase rate per order, decayed with an 8-order half-life, and the days
    since the last purchase ÷ the median of the last 6 gaps.
  - P(bought in this order) is this household's share in that (rate bin, ratio bin) cell,
    smoothed toward the rate bin and that toward the overall share. That is the hierarchical
    shrinkage, done as empirical Bayes. Upcoming orders count as bought on their delivery date.
  - Tiers: due at P ≥ 0.55. Maybe at P ≥ 0.3, the likeliest 12. Plus up to 3 groups at
    P ≥ 0.1 with a product on offer at 20% or more for the slot, if bought in 3 or more orders
    in the last year (added after the burn-rate experiment below).
  - The suggested product is the group's latest one that no `avoid` rule matches. Brand rules
    use the description's last part. The quantity is the median of the last 3 purchases.
  - Tried and dropped, because none moved precision or recall by more than 0.02: category as a
    pooling level, gaps adjusted for quantity, purchase count as a level, and other half-lives,
    gap windows, smoothing and bin edges. The model is flat in all of them.
- [x] **Backtest.** `nemlig restock backtest [--last N]` predicts each order from the ones before it,
  as the model learns its table in one pass. On the last 40 orders, without `Kød & fisk`, after
  the first review:

  | Method | Items | Precision | Recall |
  | --- | --- | --- | --- |
  | due | 8.1 | 0.70 | 0.15 |
  | due + maybe | 18.4 | 0.54 | 0.27 |
  | decayed rate alone, same size | 18.4 | 0.55 | 0.27 |
  | stopgap (2 of last 3) | 19.4 | 0.44 | 0.23 |

  Calibration: predicted 0.3–0.4 was bought 37% of the time, 0.5–0.6 50%, 0.7–0.8 73% and
  0.8–0.9 77%. The rate alone ranks as well as the model. Due-ness adds the calibrated
  probabilities, which the tiers need, and holds back items that were just bought. Offer
  stock-up and upcoming orders can't be backtested, since there are no past offers or orders
  on their way.
- [x] **CLI.** `nemlig restock [--slot ID] [--exclude CAT...] [--no-offers]` takes 1.8 s live,
  syncs first, and prints due rows and lettered maybe rows: id, product, quantity, chance, usual
  gap, last bought, offer.
- [x] **Skill.** `nemlig-restock` covers the review, the judgment (diet, `always`), adding the
  due rows and the pick list. It replaces the stopgap as `nemlig-fill-basket` step 3, run with
  `--exclude "kød & fisk"`, and its maybes ride along with dinners' checkpoint 1. The base
  skill sends "the usual" and "restock" to it.
- [ ] **Live run.** One "fill my basket for the week" with the new step 3, and `nemlig-restock`
  alone.
- [x] **Burn-rate model experiment** (2026-10-04, asked by the user). Each group gets a daily
  burn rate in pack units (g, ml, stk, parsed from the description; 98% of lines parse) and a
  stash carried over from recent buys. It is due when the stash runs out before the next
  order, for regular groups only. A harness with numpy, scipy, scikit-learn and pandas compared
  it with the current model (C), tuned on orders −80..−41 and reported on the last 40, without
  `Kød & fisk`. The model and the harness were removed after the decision below.

  | Holdout | Due items | Precision | Recall | Precision at C's due+maybe size |
  | --- | --- | --- | --- | --- |
  | C, the current model | 8.1 | 0.70 | 0.15 | 0.54 |
  | B1 burn, tuned for F1 | 26.0 | 0.42 | 0.30 | 0.41 |
  | B1 burn, in ≥40% of the last 12 orders | 7.1 | 0.67 | 0.13 | |
  | B2 burn as P(stash runs out), fitted with scipy | 23.9 | 0.43 | 0.27 | 0.44 |
  | B4 C's table with stash cover for the gap ratio | 9.2 | 0.66 | 0.16 | 0.55 |
  | B3 logistic regression on every feature | 8.9 | 0.69 | 0.17 | 0.55 |

  - We tried 64 gated burn configs, varying order share, steadiness, an overdue cut,
    carryover, and window or ewma rates. None had higher precision than C at the same due-list
    size on the tuning orders. On the holdout the best gained 0.01. A burn rule reaches C's
    precision only when gated to groups in ≥40% of recent orders, and then it is a frequency
    rule.
  - Among the groups the burn model calls due, the share bought rises with C's per-order rate
    (0.12 to 0.76) but hardly with cover. The false due rows are meal-driven or occasional
    groups that pass a buy-count gate: burger and hotdog buns, pita, sausages, soda, pizza
    sauce. They aren't used up steadily, so a stash model misreads their gaps.
  - Swapping the gap ratio for stash cover (B4 against C refitted on the same rows) changes
    nothing measurable. In gradient boosting, C's per-order rate carries the ranking: it drops
    average precision by 0.215 when permuted, and every burn feature by 0.013 or less. B2 is
    overconfident: of rows it put at 0.9 or more, 45% were bought.
  - The burn quantity, enough to last one order gap, was off by 0.89 packs on hits. The median
    of the last 3 was off by 0.61.
  - C never put a group bought fewer than 3 times a year in due or maybe (max 0.15). About 7
    such rows per order clear `OFFER_FLOOR` (0.1), so a once-a-year item on offer could still
    come up as a stock-up.
  - Decided (2026-10-04, by the user): keep the current model. A stock-up on offer now needs
    `OFFER_MIN_BUYS` (3) orders in the last year. In the backtest, groups bought once or twice
    a year were 7 of the 77 rows per order between 0.1 and 0.3, and 0–12% of them were
    bought.

Done when the user accepts most of the due rows and finds the maybe list relevant.

## Phase 5: `nemlig-recipes` (recipe artifacts)

- [x] **Skill.** `nemlig-recipes` turns the chosen dinners into one recipe artifact: a private
  claude.ai page with a card per night. Each card has the dish, time, portions (from
  `household`), the ingredients with amounts, and the steps. Ingredients are marked as bought
  on nemlig (name and pack) or assumed at home. A dish that uses another night's leftovers
  says so. It must work on a phone and print cleanly.
  - Input: the dishes and picks from `nemlig-dinners` in the same conversation. Alone ("make
    recipes for this week's dinners"), it takes the dishes from the user and reads the basket
    for what was bought. It doesn't guess dishes from basket lines.
  - Its description is narrow ("recipes", "recipe page", "how do I cook these"). It doesn't
    trigger on "what's for dinner".
  - Decided (2026-10-03, after a first page made by hand): the design is fixed in
    `template.html`, and `render.py` fills it from a JSON file (`example.json` is week 41). A
    run writes content only, which keeps it fast and the pages consistent, and the renderer
    escapes every text. `tests/test_recipes.py` renders the example.
  - Decided: each week gets a new page, `Week NN Dinners`, so earlier weeks stay. Ticks on
    ingredients and steps are per viewer in `localStorage`, not shared: one phone cooks from it,
    and a shared checklist would need the `db` capability. The page is in English with the
    Danish dish and product names. It names the kind of product, not the brand, so a cheaper
    swap of the same kind keeps it right.
  - Decided: the cooking order follows what keeps the shortest (fish first, then mince, other
    meat, vegetarian and frozen). The first night is the delivery day only if the slot ends by
    17:00.
- [x] **Hook in `nemlig-dinners`.** After the basket add and the report, it offers the recipes
  in one line ("Want the recipes as a page?") and loads `nemlig-recipes` on a yes. It doesn't
  publish without asking. Chained, it doesn't offer.
- [x] **Hook in `nemlig-fill-basket`.** Right after the dinner add, the orchestrator starts
  `nemlig-recipes` as a background subagent (one `Agent` call) with a recipe brief built from
  what the run already has, and goes on to cheaper without waiting. The report carries the link,
  or "on their way" and the link in the next message.
  - Decided (2026-10-03, by the user): a subagent, so the page never blocks the order flow with
    the user. It costs no `nemlig` call. The agent never asks and never touches the basket.
- [ ] **Live run.** One fill-basket run where the link arrives without holding up the report.

Done when a real dinner run ends with a recipe page that matches what went into the basket.

## In every phase

- Offline tests run against redacted fixtures in `docs/fixtures/`. Run live tests only when
  needed.
- When CLI behaviour changes, update `README.md` and `.claude/skills/nemlig-shopping/SKILL.md`.
- `uv run pytest` and `uv run ruff check . && uv run ruff format --check .` pass.
- Tick the boxes here and note the decisions made.
