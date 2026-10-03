---
name: nemlig-restock
description: Propose and add the household's usual nemlig.com items that are due, predicted from its past orders. Adds the likely ones and lets the user pick from the rest. Use when the user asks to restock, what they are running low on, what is due, or for the usual items. Does not plan dinners or look for cheaper swaps.
allowed-tools: Bash(nemlig:*), Bash(uv run nemlig:*)
---

# Restock the usual items

Load `nemlig-shopping` first if it isn't loaded. Its CLI rules, preferences, product choice and
reporting apply here and are not repeated.

`nemlig restock` does the arithmetic. It syncs the order cache, learns how this household buys
each kind of product, and gives the chance that each one is bought in the coming order. An
order still on its way counts as bought. You judge the list and talk to the user.

## Reading the output

```
due for fre. 02/10 kl. 17-18 (add):
  5019859  Letmælk 1,5% (1 l / Danmælk)  x3  80%  every ~7 d, last 25/09
maybe (pick by letter):
  a  5012806  Toiletpapir (8 rl. / Lambi)  x2  44%  every ~16 d, last 21/09
  b  5602663  Grovhakket leverpostej (400 g / Tulip)  x1  18%  last 01/10  offer: 3 for 50 kr, -25%
already in the basket: 3 due or maybe
to review: 4 new products (nemlig restock groups)
```

- A row is one need, such as "letmælk" in any brand. It names the product bought most
  recently and the usual quantity (`x3`).
- `80%` is the chance it is bought in this order. **Due** rows (55% and up) were right about
  70% of the time in a backtest on 135 orders. **Maybe** rows were right about half the time,
  so the user picks from them. Slow movers (toilet paper, flour) rarely go above 50%,
  because their gaps vary a lot.
- `offer:` means the product is on offer for the slot. A maybe below 30% shows up only
  because of an offer: it is a stock-up suggestion.
- Products in the basket, `avoid` matches and products not bought for a year are already left
  out.
- The date is the basket's slot. `(not reserved)` means it is only the earliest free one. If
  the user plans another day, pass `--slot SLOT_ID` (from `delivery`).

## Flow

1. **Context, in one Bash call:**
   ```sh
   nemlig --text prefs; nemlig --text restock
   ```
2. **Review new products, only when the output says `to review`.**
   ```sh
   nemlig --text restock groups
   ```
   Each line is `key  xN  category  ids`: a need (by name), how many orders it was in, and
   its products not reviewed yet. Merge keys only when they meet the **same need**, so the
   household would buy one or the other, never both. Then mark the review done, all in one
   Bash call:
   ```sh
   nemlig --text restock groups merge "æg" "frilandsæg str. s/m/l" "skrabeæg str. m/l"; nemlig --text restock groups merge agurk "agurk dansk"; nemlig --text restock groups reviewed
   ```
   - Merge name variants, brands, pack sizes and øko or not ("agurk dansk" and "agurk",
     "piskefløde 36%" and "38%", flavours of the same kids' smoothie).
   - Don't merge a different kind or a different use: "letmælk" and "minimælk", "smør" and
     "smørbar", 20 l and 30 l bin bags, dark and light pålægschokolade. Fat % in dairy is a
     choice, so keep it apart.
   - When unsure, don't merge. Most reviews need no merge. `named groups:` lists the groups
     merged before, and merging into one of those adds to it.
   - A product in the wrong group moves by id: `restock groups merge "toastbrød" 5012678`.

   If anything was merged, run `nemlig --text restock` again. Otherwise go on.
3. **Judge the list.** Drop rows that break `diet` or `always`. If `always` says øko milk and
   the row isn't øko, search for the øko one instead. Keep fresh meat and fish when the user
   asked only for a restock. In a fill-basket run the orchestrator leaves them out.
4. **Alone, when the user asked to restock or for the usual:** add the due rows in **one**
   `nemlig --text basket add ID:QTY ...`. In the same reply, show the maybes by letter and ask
   which to add:
   ```
   Added the usual (6 lines, 187.40 kr): 3 x Letmælk 1,5%, Solsikkerugbrød, 10 x Banan, ...
   Maybe due, pick by letter:
   a. Toiletpapir 8 rl. (last 21/09, usually every ~16 days)
   b. Grovhakket leverpostej, 3 for 50 kr (-25%)
   Basket: 612.30 kr. Delivery fre. 02/10 17-18 (not reserved).
   ```
   Add the picks in one more `basket add`. When the user only asked a question ("what are we
   running low on?"), list both tiers, add nothing, and offer to add them.
5. **Report** as in the base skill. Mention the offer on any row that has one.

When the user says they stopped buying something, leave it out this time and don't record
it. The prediction fades as orders without it come in.

## Chained: hand back

The orchestrator says which categories to leave out (`--exclude "kød & fisk"`). Review new
products as in step 2. Don't ask. Add the due rows in one `basket add` and hand back the base
skill's block:

```
Applied:
- added 6 due lines, 187.40 kr: 5019859:3 Letmælk 1,5%, 5012678:1 Solsikkerugbrød, ...
Proposed:
- a. [5012806] Toiletpapir 8 rl. x2 (44%, last 21/09)
- b. [5602663] Grovhakket leverpostej x1 (18%, offer: 3 for 50 kr, -25%)
Questions:
- none
```
