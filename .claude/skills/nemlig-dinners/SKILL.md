---
name: nemlig-dinners
description: Plan dinners around the current nemlig.com offers. Proposes varied dishes for N nights with prices, then adds the ingredients to the basket. Use when the user asks what's for dinner, for dinner ideas, a meal plan, or dinners for the week or N nights. Does not look for cheaper swaps.
allowed-tools: Bash(nemlig:*), Bash(uv run nemlig:*)
---

# Dinners from the nemlig offers

Load `nemlig-shopping` first if it isn't loaded. Its CLI rules, preferences, product choice and
reporting apply here and are not repeated.

Claude makes up the dishes. nemlig's recipes are not used. The user agrees on the direction at
two checkpoints, both as tables: the anchor offers first, then 3 dishes per anchor. Nothing is
added before both.

## Flow

1. **Context, in one Bash call:**
   ```sh
   nemlig --text prefs; nemlig --text basket; nemlig --text orders show; nemlig --text delivery suggest
   ```
   `orders show` with no id shows the latest order. `delivery suggest` is for step 2. Use
   `--start YYYY-MM-DD --days 1` when the request names a day, and leave it out when it names
   a time. `household` sets the portions. `diet` and
   `avoid` rules are hard constraints, and `budget` guides the price level. Take the number of
   nights and people from the request or `household`. Ask only if neither says.
2. **Delivery slot, before any offers.** Offers and deals change with the delivery slot, so the
   anchors are only right for the slot the user will actually get. The basket's last line says
   `delivery: tors. 01/10 kl. 16-17 (reserved, slot 2405499)` or `(not reserved, …)`.
   - `reserved`: use it and its slot id, and name it in checkpoint 1 ("offers for Thursday
     16-17").
   - The user named a day and time in the request ("Friday 16-21"): find it with
     `nemlig --text delivery --available --days 1 --start YYYY-MM-DD`.
   - Otherwise (`not reserved` means it is only the earliest free slot) **choose it**:
     `nemlig --text delivery suggest` ranks the bookable slots by the household's past slots
     and the fee, one per day. Add `--start YYYY-MM-DD --days 1` for a day the user named. Take
     the top row, and fetch its offers with `--slot`. In checkpoint 1, say which slot it is and
     why ("Delivery Fri 09/10 16-21 (19 kr), your usual Friday window. Say if you want another
     time."). If the user picks another, fetch the offers for it and show the anchors again.

   From then on pass `--slot SLOT_ID` to `offers` and `search`, also when it is the reserved
   one (that costs nothing, and keeps the prices right if the hold lapses). The slot is
   reserved in step 8, before anything is added. Asking for dinners to be added counts as
   asking for the reservation, so the base skill's "only when asked" rule is met.
3. **Dinner offers, in one call:**
   ```sh
   nemlig --text offers --category koed fisk-og-skaldyr groentsager faerdigretter-og-koederstatning --min-discount 20 --limit 0 --slot SLOT_ID
   ```
   `koed` and `fisk-og-skaldyr` include the frozen ones (`Frost/Koed`). Top-level
   `frugt-og-groent` is mostly dried fruit and nuts, so ask for `groentsager` instead. `-34%` is
   the discount. `offer: 3 for 112,50 kr (133.92 kr/kg)` is a multi-buy, and "Mix" deals on
   the site usually let the user mix products in the same offer. If fewer than about 10
   products come back, drop `--min-discount`. `nemlig --text offers --categories` lists the
   category names with counts.
4. **Checkpoint 1: anchors.** Shortlist 6–10 offers that can carry a dinner, grouped as meat,
   fish and vegetarian. Choose them by:
   - **A main-meal ingredient** that suits an ordinary dinner: not oysters on a Tuesday, not a
     2 kg roast for one.
   - **Pack size.** It fits the household. A big roast can be offered as "2 nights".
   - **A real saving:** 20% or more, or a multi-buy worth buying at its quantity.
   - **Spread.** At most 2 from the same animal. Include a fish and a vegetarian option when
     the offers and the diet allow.

   Show one table per group, numbered across the tables so the user can pick by number. Mark
   the suggested set with ★:
   ```
   **Meat**
   | # | Item | Amount | Price | Price/amount | Note |
   | --- | --- | --- | --- | --- | --- |
   | 1 ★ | Hel frilandskylling | 1,5 kg | 99 kr (-34%) | 66 kr/kg | Roast, 4 portions |
   | 2 | Kyllingebrystfilet | 280 g | 43,95 kr, 3 for 112,50 kr (-15%) | 134 kr/kg at 3 | Wok or wraps; mix with lårsteak |
   | 3 ★ | Culottesteg | 1,5–1,8 kg | 280 kr (-30%) | 187 kr/kg | 2 nights: roast, then sandwiches |
   ```
   - **Amount** is the pack size from the offer row (`1,50 kg`, `6 stk. / 900 g`).
   - **Price** is the shelf price with the discount. For a multi-buy, add the deal.
   - **Price/amount** is the bracketed `kr/kg`, `kr/l` or `kr/stk`. For a multi-buy, use the
     offer's unit price and say "at 3".
   - **Note** says what the item suits, and flags a pack for two nights, a frozen item or a
     deal that needs more than one pack.

   Under the tables, name the slot the offers are for. Then ask once: "Build on the ★ ones,
   or pick others by number (or 'you choose')?"
5. **Dishes: 3 options per anchor.** First work out how many nights each anchor covers for the
   household. Allow about 150 g boneless meat or fish per adult and about 300 g bone-in, and
   half that per child. A 1,5 kg whole chicken feeds 4 once, and a 1,6 kg culotte feeds 4
   twice. Then make up 3 dishes per anchor that differ from each other in cuisine, starch and
   method. Across the tables, vary:
   - **Cuisine:** Danish, Italian, Asian, Mexican, Middle Eastern and so on.
   - **Starch:** potatoes, rice, pasta, bread or tortillas, grains.
   - **Method:** pan, oven, pot or stew.
   - **Time.** Weeknight dishes take 40 min or less. Label a slow one.
   - **A vegetarian night** when N is 3 or more and the diet allows.

   When an anchor covers 2 nights, make its options work as a pair: the second can use
   leftovers ("culotte: roast Sunday, sandwiches Monday"). Suggest a set of N dishes that
   varies across the tables, and mark it with ★.
6. **Find the products with one search.** For each dish, split the ingredients into *to buy*
   and *assumed at home*:
   - Assumed at home: salt, pepper, oil, butter, flour, sugar, dried spices, stock cubes.
   - Also assumed at home: whatever is in the basket, and things that keep that were in the
     latest order (rice, pasta, onions, garlic).
   - Chained, a restock maybe the user didn't pick may be running low. If a dish needs it, keep
     it at home but name it first in the "Assumed at home" line, so the user can say.
   - Everything else is to buy.

   Run **one** search over the to-buy items of every option, with no duplicates:
   ```sh
   nemlig --text search kartofler citron "frisk timian" kokosmælk ... --limit 3 --slot SLOT_ID
   ```
   The anchor is already priced by its offer, so leave it out of the search. Pick the products
   as the base skill says, at whole packs.
7. **Checkpoint 2: price the dishes with `dishes`, then show them.** Write the plan as a spec
   and let the CLI do the sums. It prices the products from the latest `search` and `offers`
   output, so it makes no request:
   ```sh
   nemlig --text dishes <<'EOF'
   portions 3
   anchor 1 5066317:1 nights 1
   1a* Ovnstegt kylling med citron og kartofler | 60 min | 5014541:2 2301103:1 | Danish, oven
   1b Kylling tikka masala med ris | 35 min | 5060435:1 5016560:1 | Indian, pot; ris at home
   1c Kyllingetacos med majs og salsa | 30 min | 5048583:1 5064869:1 | Mexican, pan
   anchor 2 5602181:1 nights 2
   2a* Culotte med bagte rodfrugter og bearnaise | 90 min | 5016873:1 | Weekend, oven
   2b* Steaksandwich med rucola og syltede løg | 15 min | 5021833:1 | Leftovers from 2a
   2c Oksekødsalat med nudler og chili | 25 min | 5070655:1 | Thai, cold; uses leftovers
   EOF
   ```
   - `portions`: 1 per adult and 0.5 per child.
   - `anchor KEY ID:QTY nights N`, with the nights the anchor covers. A night without an
     anchor offer is `anchor V nights 1 | Vegetarian`.
   - One dish per line: code (`*` marks ★), name, time, the to-buy `ID:QTY`s (`-` for none),
     and a note with the cuisine and method, what is assumed at home, or the leftovers it uses.
   - A product on several dishes is one shared pack, bought once at the largest quantity. When
     two dishes each need their own pack, put the total on one of them.
   - `no price for ID` means that id wasn't in a `search` or `offers` output. Search for it,
     and don't guess.

   It prints one table per anchor and the ★ set's total. Copy the tables as they are. Under
   them, give the ★ total, the slot, and one line "Assumed at home: …". A `warning:` line means
   the ★ set takes more dishes from an anchor than it covers. Fix the spec and run it again.
   Ask once which dishes to use, by code ("1b, 2a, 2b"). Ask in the same message whether
   anything assumed at home is missing. If the slot isn't reserved yet, say that it will be
   reserved before the basket is filled ("I'll reserve fre. 02/10 17-18 first"). If the picks
   don't add up to N nights, or exceed what a table covers, say so before adding.
8. **Reserve the slot, then add.**
   1. If the chosen slot isn't the basket's reserved slot, reserve it first, as in the base
      skill's *Reserving a delivery slot*. If it fails, add nothing. When the user then picks
      another slot, its offers can differ, so check the anchors with `offers --slot NEW_ID`
      before adding.

      If a dish relied on an undeliverable line (step 6 counted basket lines as at home), add
      a replacement from the step-6 search to this add as `ID:QTY`, or search once for just
      those items.
   2. Add the picked dishes in one call. It adds their anchors and extras, each product once,
      plus any `ID:QTY` given:
      ```sh
      nemlig --text dishes add 1b 2a 2b
      ```
      Don't search again. It prints one line per dish (code, name, cost, ids), the `added:`
      total and the basket. Report as in the base skill, with one line per night (dish, cost).
      Take the basket total, the minimum-order line and the slot from that output. The slot
      should now read `(reserved)`. End the report with one line, "Want the recipes as a
      page?", and load `nemlig-recipes` on a yes.

If the user says "just pick", "surprise me" or similar, skip both checkpoints. Choose the
anchors and the N dishes yourself, then reserve and add as in step 8, and report the dishes
and the slot with the additions.

When the user corrects you in a way that will hold ("we don't eat lamb", "never that
brand"), record it as the base skill says: food rules in `diet`, products with `prefs avoid`.

## Chained: hand back

Run the flow with both checkpoints, as alone. The orchestrator has read `prefs`, the basket,
the latest order and the offers, settled and reserved the slot, and gives its id, the nights
and the people. So skip *Context*, *Delivery slot* and the offers call, and start
at *Checkpoint 1*. The orchestrator puts the step-6 search in a call with its own reads. In
*Reserve the slot, then add*, skip the reservation, and run `dishes add` in the orchestrator's
call. Don't report or offer the recipes (the orchestrator starts them). Hand back the base
skill's block: one `Applied:` line per night with the dish, its cost and the product ids from
the `dishes add` output (`Fri: Ovnstegt kylling med citron, 131 kr: 5066317:1 2301103:2`).
Under `Questions:`, list the assumed-at-home items worth checking.
