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
   nemlig --text prefs; nemlig --text basket; nemlig --text orders --limit 1
   ```
   Then `orders show` the latest order in the next call, if there is one. `household` sets the
   portions. `diet` and `avoid` rules are hard constraints, and `budget` guides the price level.
   Take the number of nights and people from the request or `household`. Ask only if neither
   says.
2. **Delivery slot, before any offers.** Offers and deals change with the delivery slot, so the
   anchors are only right for the slot the user will actually get. The basket's last line says
   `delivery: tors. 01/10 kl. 16-17 (reserved)` or `(not reserved)`.
   - `reserved`: use it, and name it in checkpoint 1 ("offers for Thursday 16-17").
   - The user named a day or time in the request ("Friday evening"): find it with
     `nemlig --text delivery --available --days 7` (add `--start YYYY-MM-DD` for later days).
   - Otherwise (`not reserved` means it is only the earliest free slot) **ask first**, in one
     short question: "Which day and time is the delivery? Offers depend on it." Ask this
     together with the number of nights or people if those are also missing, and fetch no
     offers until it is answered. Then look up the slot as above.

   From then on pass `--slot SLOT_ID` to `offers` and `search` unless the slot is the reserved
   one. The slot the user chose here is reserved in step 8, before anything is added. Choosing
   it counts as asking for the reservation, so the base skill's "only when asked" rule is met.
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
6. **Price them with one search.** For each dish, split the ingredients into *to buy* and
   *assumed at home*:
   - Assumed at home: salt, pepper, oil, butter, flour, sugar, dried spices, stock cubes.
   - Also assumed at home: whatever is in the basket, and things that keep that were in the
     latest order (rice, pasta, onions, garlic).
   - Everything else is to buy.

   Run **one** search over the to-buy items of every option, with no duplicates:
   ```sh
   nemlig --text search kartofler citron "frisk timian" kokosmælk ... --limit 3 --slot SLOT_ID
   ```
   The anchor is already priced by its offer, so leave it out of the search. Pick the products
   as the base skill says. The extras for a dish cost the sum of the whole packs it needs. When
   dishes share a pack, count it once in the total and say so.
7. **Checkpoint 2: dishes.** One table per anchor. The heading gives the anchor, its price and
   how many dishes can be picked from the table (the nights it covers):
   ```
   **1. Hel frilandskylling, 1,5 kg, 99 kr (-34%): pick 1**
   | # | Dish | Time | Extras to buy | Extras | Per portion | Note |
   | --- | --- | --- | --- | --- | --- | --- |
   | 1a ★ | Ovnstegt kylling med citron og kartofler | 60 min | kartofler 2 kg, citron, timian | 32 kr | 33 kr | Danish, oven |
   | 1b | Kylling tikka masala med ris | 35 min | kokosmælk, hakkede tomater, ingefær | 38 kr | 34 kr | Indian, pot; ris at home |
   | 1c | Kyllingetacos med majs og salsa | 30 min | tortillas, majs, avocado, lime | 55 kr | 39 kr | Mexican, pan |

   **2. Culottesteg, 1,5–1,8 kg, 280 kr (-30%): pick up to 2**
   | # | Dish | Time | Extras to buy | Extras | Per portion | Note |
   | --- | --- | --- | --- | --- | --- | --- |
   | 2a ★ | Culotte med bagte rodfrugter og bearnaise | 90 min | rodfrugter, bearnaise | 45 kr | 46 kr | Weekend, oven |
   | 2b ★ | Steaksandwich med rucola og syltede løg | 15 min | ciabatta, rucola | 35 kr | 44 kr | Leftovers from 2a |
   | 2c | Oksekødsalat med nudler og chili | 25 min | nudler, agurk, koriander | 30 kr | 43 kr | Thai, cold; uses leftovers |
   ```
   - **Extras** is the cost of the to-buy items for that dish, without the anchor.
   - **Per portion** = (anchor price ÷ dishes it covers + extras) ÷ portions.
   - **Note** gives the cuisine and method, and says what is assumed at home or reuses leftovers.

   Under the tables, give the total for the ★ set (anchors + extras), the slot, and one line
   "Assumed at home: …". Ask once which dishes to use, by code ("1b, 2a, 2b"). Ask in the same
   message whether anything assumed at home is missing. If the slot isn't reserved yet, say
   that it will be reserved before the basket is filled ("I'll reserve fre. 02/10 17-18
   first"). If the picks don't add up to N nights, or exceed what a table covers, say so
   before adding.
8. **Reserve the slot, then add.**
   1. If the chosen slot isn't the basket's reserved slot, reserve it on its own first:
      ```sh
      nemlig --text delivery reserve SLOT_ID
      ```
      It exits 0 even when the reservation fails, so read the output. It must start with
      `reserved:` and name the chosen slot. On `not reserved: …`, stop without adding
      anything. Tell the user, show the nearest bookable slots
      (`nemlig --text delivery --available --days 3 --start DAY`), and ask. A different slot
      can have different offers, so check the anchors against it with
      `offers --slot NEW_ID` before adding.
   2. Run one `basket add` for the chosen dishes, with the ids and quantities from step 6.
      Don't search again. Report as in the base skill, with one line per night (dish, cost).
      Take the basket total, the minimum-order line and the slot from that output. The slot
      should now read `(reserved)`.

If the user says "just pick", "surprise me" or similar, skip both checkpoints. Choose the
anchors and the N dishes yourself, then reserve and add as in step 8, and report the dishes
with the additions. The delivery slot question (step 2) is still asked when no slot is
reserved or named.

When the user corrects you in a way that will hold ("we don't eat lamb", "never that
brand"), record it as the base skill says: food rules in `diet`, products with `prefs avoid`.

## Chained: hand back

Skip the checkpoints and pick the anchors and N dishes yourself. Use the slot the orchestrator
gives, or the reserved one. If neither exists, don't guess: hand back `Applied: none`, no
dishes, and the delivery slot under `Questions:`. Add only if the orchestrator said to, and
then reserve the slot first as in step 8. Hand
back the base skill's block: one `Proposed:` line per dish with its cost and product ids
(`add 5066317:1 2301103:2 ...`). Under `Questions:`, list the assumed-at-home items worth
checking.
