---
name: nemlig-cheaper
description: Find cheaper alternatives for what is already in the user's nemlig.com basket by comparing unit prices (kr/kg, kr/l), and propose swaps with the saving per line and in total. Use when the user asks for cheaper alternatives, cheaper swaps, or how to save money on their nemlig basket. Does not fill the basket.
allowed-tools: Bash(nemlig:*), Bash(uv run nemlig:*)
---

# Cheaper swaps for the nemlig basket

Load `nemlig-shopping` first if it isn't loaded. Its CLI rules, preferences and reporting apply
here and are not repeated.

## Flow

1. **Context, in one Bash call:** `nemlig --text prefs; nemlig --text basket`. `always` and
   `diet` are hard constraints, and `household` sets reasonable pack sizes. `keep` and `avoid`
   rules are applied by the CLI in step 3. The basket gives each line's id, quantity, pack size
   and total. The search adds the line's unit price.
2. **Pick the lines to check.** Skip sold-out lines, lines a `keep` rule matches, and lines that are
   already a budget product with nothing plainer to swap to. For each remaining line, write
   one generic Danish query that keeps what defines it: "øko minimælk", "laktosefri
   letmælk", "hakket oksekød 8-12%", "havregryn". Don't search the product name verbatim;
   it mostly returns the same product.
3. **One search**, with the basket line id of each query after the queries, in the same order:
   ```sh
   nemlig --text search "øko minimælk" kaffebønner --limit 8 --cheaper-than 103368 5027015
   ```
   `--cheaper-than` does the arithmetic. It keeps only products that are in stock, in the
   line's unit (kr/kg with kr/kg), cheaper per kg, l or piece than the line, offers included,
   and that save enough on the line. The rest is dropped:
   ```
   2 of 18 results for 'øko minimælk' cheaper than 2 x Minimælk øko. (1 l / Arla) 51.90 kr (25.95 kr/l)
   5012345  Minimælk øko.  1 l / Øko  20.95 kr (20.95 kr/l)  2x saves 10.00 kr
   5012999  Minimælk øko.  1 l / Thise  22.95 kr (22.95 kr/l)  offer: 3 for 60 kr (20.00 kr/l)  buy 3 for the offer
   ```
   - `2x saves 10.00 kr`: the packs that hold about the line's amount, and the line total
     minus their cost, with a multi-buy price only when the packs reach it. `(4.5x the
     amount)` means the packs hold much more or less than the line does.
   - `buy 3 for the offer`: only buying the multi-buy quantity makes it cheaper.
   - The biggest saving comes first. Savings under 2 kr or 5% are left out.
   - `kr/stk` is crude: a small and a large cauliflower are both 1 stk.
   - Products an `avoid` rule matches are dropped. For a line a `keep` rule matches, it prints
     `skipped '<query>': keep rule ...` instead of searching.
   - `0 of 38 results` means nothing is cheaper. If a query finds nothing at all (`0 of 0`),
     retry just that one with a broader term ("rugknækbrød" → "knækbrød").
   - If the user plans a delivery slot other than the basket's, add `--slot SLOT_ID`.
4. **Judge the candidates per line.** Keep one only if it:
   - is the **same kind of product**: judge it. Thighs are not a whole chicken, portion
     packs are not a 1 l carton, frozen is not fresh, and a flavoured variant is not the plain
     one.
   - keeps every **constraint label** of the original (øko, laktosefri, glutenfri, fat %) and
     every preference. Read them from the name ("øko.", "laktosefri"). If a name doesn't
     settle it, run one `nemlig search Q...` without `--text` for just those queries and check
     `labels`. Tags like `Discount`, `Prisfald`, `Prismatch` and `Køl` are not constraints.
   - has a **sensible amount** for the household. No 5 kg sack to replace 500 g unless the
     household would use it, which a large `x the amount` flags.
5. **Offers to stock up on.** Propose a `buy N for the offer` row only for things that keep (dry
   goods, frozen, household), or when the basket already has N or more. Give it with the unit
   prices, and leave it out of the total.
6. **Total.** Add up the `saves` of the swaps you keep. If the swaps would take the basket
   below the minimum order, say so.

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

The orchestrator has read `prefs`, and it runs your searches itself. It appends one
`search --cheaper-than` to each of its basket adds, with queries written as in step 2. At its
report, judge every `cheaper than` block as in steps 4–6, for lines still in the basket. Don't
ask or apply anything. Return the base skill's handoff block, with `Applied: none` and one
`Proposed:` line per swap (old id → new id, quantity, saving, unit prices). Put choices only
the user can make, such as a borderline "same kind", under `Questions:`.
