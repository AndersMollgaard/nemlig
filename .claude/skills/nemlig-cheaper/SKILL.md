---
name: nemlig-cheaper
description: Find cheaper alternatives for what is already in the user's nemlig.com basket by comparing unit prices (kr/kg, kr/l), and propose swaps with the saving per line and in total. Use when the user asks for cheaper alternatives, cheaper swaps, or how to save money on their nemlig basket. Does not fill the basket.
allowed-tools: Bash(nemlig:*), Bash(uv run nemlig:*)
---

# Cheaper swaps for the nemlig basket

Load `nemlig-shopping` first if it isn't loaded. Its CLI rules, preferences and reporting apply
here and are not repeated.

## Flow

1. **Preferences:** `nemlig --text prefs`. `always` and `diet` are hard constraints, and
   `household` sets reasonable pack sizes. `keep` and `avoid` rules are applied by the CLI in
   step 4.
2. **Basket, as JSON, once:** `nemlig basket`. Each line has `unit_price`, `unit_price_label`,
   `labels` (øko, laktosefri...), `offer` and `description` (pack size). JSON is needed here;
   `--text` leaves these out.
3. **Pick the lines to check.** Skip sold-out lines, lines a `keep` rule matches, and lines that are
   already a budget product with nothing plainer to swap to. For each remaining line, write
   one generic Danish query that keeps what defines it: "øko minimælk", "laktosefri
   letmælk", "hakket oksekød 8-12%", "havregryn". Don't search the product name verbatim;
   it mostly returns the same product. Tags like `Discount`, `Prisfald`, `Prismatch` and `Køl`
   in `labels` are not constraints, and `Discount` doesn't mean a budget range.
4. **One search**, with the basket line id of each query after the queries, in the same order:
   ```sh
   nemlig --text search "øko minimælk" kaffebønner --limit 8 --cheaper-than 103368 5027015
   ```
   `--cheaper-than` keeps only products that are in stock, in the line's unit (kr/kg with
   kr/kg), and cheaper per kg, l or piece than the line, offers included. It compares
   `kr/kg`, never the shelf price, so a bigger pack can pass while costing more in total, and
   a multi-buy offer passes even if it needs 3 bought. Step 7 sorts that out. `kr/stk` is
   crude: a small and a large cauliflower are both 1 stk. It also drops products an `avoid`
   rule matches, and for a line a `keep` rule matches it prints `skipped '<query>': keep
   rule ...` instead of searching. `0 of 38 results` means nothing is cheaper. If the user plans a delivery slot other than the basket's, add
   `--slot SLOT_ID`. If a query finds nothing at all (`0 of 0`), retry just that one with a
   broader term ("rugknækbrød" → "knækbrød").
5. **Judge the candidates per line.** Keep one only if it:
   - is the **same kind of product**: judge it. Thighs are not a whole chicken, portion
     packs are not a 1 l carton, and a flavoured variant is not the plain one.
   - keeps every **constraint label** of the original (øko, laktosefri, glutenfri, fat %) and
     every preference. Read them from the name ("øko.", "laktosefri"). If a name doesn't
     settle it, run one JSON `nemlig search` for just those queries and check `labels`.
   - has a **sensible pack size** for the household. No 5 kg sack to replace 500 g unless the
     household would use it.
6. **Compare unit prices, not shelf prices.**
   - An offer shows its unit price in brackets: `offer: 3 for 50 kr (33.33 kr/kg)` is the
     price per kg when buying 3, and `offer: 18 kr (24.00 kr/kg)` is the price now. A
     multi-buy price counts only if the swap buys at least that many. Otherwise use the plain
     unit price.
   - The basket line's `unit_price` already includes a single-price offer. A multi-buy
     `offer` on the line counts only if its quantity reaches the offer's.
   - "Buy 2 to hit the offer" is a separate kind of proposal. Suggest it only for things that
     keep (dry goods, frozen, household), or when the basket already has 2+.
7. **Saving per line** = current line total − new line total for about the same amount, in
   whole packs (2 × 500 g replaces 1 kg). Drop savings under 2 kr or under 5%, which aren't
   worth a swap. Add up the total. If the swaps would take the basket below the minimum
   order, say so.

## Alone: propose, then apply

Show the proposals, the biggest saving first, and ask once which to apply:

```
Cheaper swaps (saves 19.90 kr of 612.00 kr):
1. Minimælk øko 1 l, Arla 2x → Minimælk øko 1 l, Øko 2x: 25.95 → 20.95 kr/l, saves 10.00 kr
2. Hakket oksekød 8-12% 500 g, Coop 2x → 500 g, Danish Crown 2x (2 for 90 kr): 99.90 → 90.00 kr/kg, saves 9.90 kr
Kept: Lavazza (keep rule), Skyr (already the cheapest øko)
Apply all, some (numbers), or none? Say "never" for any you don't want suggested again.
```

When the user turns a swap down for a reason that will hold, record it so it isn't proposed
again, and say so:
- Against the replacement ("never", "too thin", "we don't like that brand"): `nemlig prefs avoid`
  for the candidate. Use `--brand` with `--name` for a brand in one kind of product, or `--id`
  for one product.
- For the original ("leave the coffee", "we always buy that one"): `nemlig prefs keep` for the
  basket line.

Apply the accepted swaps in **one** `basket set` call. It is absolute, so it is safe to
repeat after an error:

```sh
nemlig --text basket set OLD_ID:0 NEW_ID:QTY OLD_ID2:0 NEW_ID2:QTY
```

Never use `basket add` for a swap. Report as in the base skill, with the new basket total and
the minimum-order line from that command's output.

## Chained: hand back

Don't ask or apply anything. Return the base skill's handoff block, with `Applied: none` and
one `Proposed:` line per swap (old id → new id, quantity, saving, unit prices). Put choices
only the user can make, such as a borderline "same kind", under `Questions:`.
