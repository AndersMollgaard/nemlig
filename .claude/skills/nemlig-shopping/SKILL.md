---
name: nemlig-shopping
description: Shop on nemlig.com (Danish online grocery) for the user with the `nemlig` CLI. Finds products, fills and adjusts the basket, reorders past orders, uses favourites and shopping lists, and shows delivery slots. Use when the user wants groceries found, added, removed, compared or reordered, or asks what is in their nemlig basket. Checkout is not possible; the user pays in the browser.
allowed-tools: Bash(nemlig:*), Bash(uv run nemlig:*)
---

# Shopping on nemlig.com

The `nemlig` CLI talks to the user's real nemlig.com account. Basket changes are real, but
nothing is ordered or paid for here. The user checks out on nemlig.com.

If `nemlig` is not on PATH, run `uv run nemlig` from the repo root instead.

## Be fast

Round trips matter most. Every step below is meant to save one.

- **Always pass `--text`.** It is about 5x smaller than JSON and still shows ids, prices, offers
  and SOLD OUT. Use JSON only when you need fields that text leaves out: `labels` (øko,
  laktosefri, frost...), `brand`, `category`, or per-line `discount`.
- **Start with `nemlig --text basket`.** It shows what is already there and the reserved
  delivery slot, and it logs in if the session has expired.
- **Offers and deals depend on the delivery slot.** Search and offers use the basket's slot
  (the earliest one if none is reserved). If the user plans another day, add `--slot SLOT_ID`
  (from `delivery`) to `search` and `offers` rather than reserving it.
- **Search for every item in one call.** The queries run in parallel, so a whole shopping list
  takes about as long as one search (~1 s):
  ```sh
  nemlig --text search minimælk rugbrød æg "hakket oksekød" --limit 5
  ```
  Each block starts with `N of M results for '<query>'`, in the order you gave the queries.
  Quote queries that have more than one word. Use `--limit 5` (the default is 10). Only page
  with `--offset` if nothing fits.
- **Change the basket in one call.** `nemlig --text basket add 701013:2 5003310 5035265` applies
  all the items and prints the resulting basket. Don't run `basket` again afterwards.
- **Don't run `status`, `product` or `--help` just in case.** Run `product ID` only when the user
  asks about ingredients, allergens or nutrition. It is long.
- **`favourites` is large (~16 KB of text).** Filter it:
  `nemlig --text favourites | grep -i -E "mælk|kaffe"`.

## Core loop: "put these things in my basket"

1. `nemlig --text basket` to see what is there, and to log in.
2. Search for every item in one `search` call, using Danish terms. Translate English and be specific
   ("spaghetti", not "pasta", which returns filled pasta first). If a term finds nothing
   useful, try `nemlig --text suggest <term>`.
3. Pick a product for each item (see *Choosing products*). Don't stop to ask about each one.
4. Run one `basket add` with every pick.
5. Report back (see *Reporting*). Ask any open questions together, in that one message.

For "the usual", "same as last time" or "refill", take the products from order history rather
than searching:
```sh
nemlig --text orders --limit 3                 # recent orders: id, date, total
nemlig --text orders show 88876788             # lines as "QTY x NAME [PRODUCT_ID] PRICE"
nemlig --text orders reorder 88876788          # adds the whole order (additive!)
```
Use `reorder` only when the user wants the whole order again. To pick from it, read the
lines and `basket add` the ones you want.

## Choosing products

In order of priority:

1. **What the user said.** Size, brand, fat %, øko, laktosefri and similar are hard
   constraints.
2. **What the household buys.** If the user has an order history, a product they bought before
   or marked as a favourite beats a new one. Look it up when the item is ambiguous, e.g. milk
   (mini/let/søde, øko or not) or coffee. `orders show` of the latest 1–3 orders plus a grepped
   `favourites` is usually enough. Do it once per session, not once per item.
3. **Otherwise a plain default.** Pick a standard size at a sensible unit price (compare the
   `kr/kg` or `kr/l` in brackets, not the shelf price). Don't pick a novelty or a multipack
   unless it was asked for.

- Skip anything marked `SOLD OUT`. Pick the closest alternative and mention the swap.
- Mention an offer (`offer: 2 for 58 kr`) when it changes what the best buy is, e.g. buying 2.
- "500 g hakket oksekød" means a pack of about that size, not a quantity of 500. Weigh the
  quantity against the pack description (`1 kg`, `10 stk.`).
- Ask before adding only when a wrong guess would be costly or unwanted: a big price
  difference, a dietary or allergy question, or no reasonable match. Otherwise decide, then say
  what you assumed.

## Changing the basket

| Want | Command |
| --- | --- |
| Add (on top of the current quantity) | `nemlig --text basket add ID[:QTY] ...` |
| Set an exact quantity (0 removes) | `nemlig --text basket set ID:QTY ...` |
| Remove | `nemlig --text basket remove ID ...` |
| Drop sold-out lines | `nemlig --text basket remove-sold-out` |

- `add` is **not idempotent**. After an error or a timeout, don't repeat it. The error JSON on
  stderr lists `applied` items. Check with `nemlig --text basket`, then fix it with `basket set`.
- To correct a quantity, use `set`. It is absolute, so it is safe to repeat.
- Product ids are strings of digits, taken from search, basket or order output. Never guess one.
- Don't run `basket clear --yes`, `lists delete --yes` or `delivery reserve` unless the user
  asked for it in this conversation. Clearing the basket keeps the reserved delivery slot.

## Reporting

Keep it short. Show what changed and what the user should check:

```
Added:
- 2 x Minimælk 0,4% (1 l, Arla) 23.00 kr
- Skrabeæg str. M/L (10 stk.) 31.95 kr, offer: 2 for 58 kr
Swapped: San Marzano tomater (sold out) → Tomater 500 g, 18.00 kr
Assumed: "brød" = Solsikkerugbrød, 950 g (you bought it last time)
Basket: 412.30 kr, 87.70 kr below the 500 kr minimum. Delivery tors. 01/10 16-21.
```

Take the totals, the minimum-order line and the delivery slot from the basket output that the
last `basket` command printed.

## Other commands

```sh
nemlig --text offers --limit 20                     # offers for the basket's delivery slot
nemlig --text offers --slot SLOT_ID                 # another slot's offers, without reserving it
nemlig --text lists                                 # shopping lists; lists show ID; lists to-basket ID
nemlig --text lists set LIST_ID ID:QTY ...          # edit a list (0 removes)
nemlig --text delivery --available --days 3         # bookable slots: SLOT_ID time price
nemlig --text delivery reserve SLOT_ID              # only when asked
nemlig --help                                       # everything else
```

## Errors

Errors go to stderr as `{"error": ..., "message": ...}`, or `error: ...` with `--text`.

- Exit 3 means not logged in or the login was rejected. Run `nemlig login` once. If that fails
  too, credentials are missing (`NEMLIG_USER`/`NEMLIG_PASS` in `./.env` or
  `~/.config/nemlig/.env`). Tell the user. Don't go looking for credentials.
- Exit 1 means a nemlig.com or network error. Read-only commands are safe to retry once. For
  writes, check the basket first (see above).
- Exit 2 is a usage error. Fix the arguments.
