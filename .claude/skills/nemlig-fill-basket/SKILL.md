---
name: nemlig-fill-basket
description: Fill the user's nemlig.com basket for the week in one run. Restocks the usual items that are due, plans dinners around the offers with the user, then proposes cheaper swaps for the whole basket, and reports once. Use when the user asks to fill their basket, do the weekly shop, or make a basket for the week.
allowed-tools: Bash(nemlig:*), Bash(uv run nemlig:*)
---

# Fill the nemlig basket for the week

Load `nemlig-shopping` first if it isn't loaded. Its CLI rules, preferences, product choice and
handoff format apply here and are not repeated.

This skill chains the sub-skills in a fixed order: slot, restock, dinners, cheaper. Restock
comes first so its lines count as at home when the dinners are priced. Cheaper comes last
because it compares against basket lines, so it reviews everything this run added. The run
builds on the current basket and never clears it.

## Flow

1. **Context, in one Bash call:**
   ```sh
   nemlig --text prefs; nemlig --text basket
   ```
   This is the run's only `prefs` read. The sub-skills use it, and the latest basket output.
2. **Slot and nights: one question, then reserve.**
   - Slot: the one the user named, or the basket's `(reserved)` slot. `(not reserved)` is only
     the earliest free slot, so it doesn't count.
   - Nights and people: from the request, or `household`.

   Ask once, in one short message, for whatever is missing ("Which day and time is the
   delivery, and how many dinners?"). Add nothing before it is answered. Find a named day with
   `nemlig --text delivery --available --days 7` (add `--start YYYY-MM-DD` for later days).

   If the slot isn't the reserved one, reserve it before the first add, as in the base skill's
   *Reserving a delivery slot*. Choosing it counts as asking for the reservation. If it fails,
   stop there. Keep the price change and the `undeliverable:` lines for the report. From here
   on, every `restock`, `offers` and `search` gets `--slot SLOT_ID`, and each sub-skill is
   given the slot id.
3. **Restock the usual.** Load `nemlig-restock` and follow its *Chained* section, with the slot
   and `--exclude "kød & fisk"` (fresh meat and fish are the dinners' job). It reviews new
   products if needed, adds the due items in one `basket add`, and hands back the maybes by
   letter and any groups it merged. If nothing is due, say so in the report and go on.
4. **Dinners, with their checkpoints.** Load `nemlig-dinners` and follow its *Chained* section,
   with the slot id, the nights and the people. Above its first checkpoint, show what step 3
   added in one line, then the maybes by letter, so the user answers both in one reply:
   ```
   Restocked 6 usual items (187.40 kr): letmælk, solsikkerugbrød, bananer, ...
   Maybe due, pick by letter with the anchors: a. Toiletpapir 8 rl. (last 21/09)  b. Grovhakket leverpostej, 3 for 50 kr (-25%)  c. Falke hvedemel 2 kg
   ```
   The user picks the anchors by number and the maybes by letter ("★ and a, c"). Add the
   picked letters in **one** `basket add` before dinners' *Dishes* step, so they count as at
   home when the dishes are priced. No letters means none. Then the user picks the dishes as in
   that skill. It adds the dishes and hands back a block instead of reporting.

   When there is no first checkpoint (no dinners this time, or "just pick"), the maybes go to
   the closing question instead.
5. **Cheaper over the whole basket.** Load `nemlig-cheaper` and follow its *Chained* section,
   with the slot id. It reads the basket fresh, so the restocked and dinner lines are reviewed
   with the rest, and hands back proposals without applying any.
6. **One report, one question.** Build it from the handoff blocks and the last basket output.
   If that output says `(not reserved)`, the hold has lapsed: reserve the slot again first, and
   take the slot from that output.
   ```
   Restocked (8 lines, 231.30 kr): 3 x Letmælk 1,5%, Solsikkerugbrød, 10 x Banan, Toiletpapir, ...
   Merged in restock: æg = frilandsæg + skrabeæg
   Dinners:
   - Fri: Ovnstegt kylling med citron og kartofler, 131 kr
   - Sat: Culotte med bagte rodfrugter, 325 kr (Sun: steaksandwich from the leftovers)
   Cheaper swaps (saves 19.90 kr):
   1. Minimælk øko 1 l, Arla 2x → Øko 2x: 25.95 → 20.95 kr/l, saves 10.00 kr
   2. Hakket oksekød 8-12% 500 g, Coop → Danish Crown (2 for 90 kr): saves 9.90 kr
   Check: rice and soy sauce at home? (assumed for Mon)
   Moving to Friday made the basket 91.21 kr cheaper. Undeliverable: Peberfrugt rød.
   Basket: 1,148.20 kr (budget about 1,200 kr). Delivery fre. 02/10 17-18 (reserved).
   Apply the swaps (all, some, none)? Anything to drop from the restock, or anything else to add?
   ```
   - Name the minimum order only when the basket is below it, and the budget only when
     `budget` is set. Put every `Questions:` line from the handoffs under `Check:`.
   - Leave out a section that is empty, and the question about swaps when there are none.
   - Maybes that no checkpoint showed go under the restocked line by letter, with "pick any
     maybes by letter" in the question.

   The restocked line counts the due items and the picked maybes together.

   Apply the answer in **one** `basket set`: accepted swaps as `OLD_ID:0 NEW_ID:QTY`, dropped
   restock lines as `ID:0`, picked maybes as `ID:QTY`, and things the user adds at their total
   quantity (one `search` with `--slot` first). It is absolute, so it is safe to repeat after
   an error. Record a "never" as `nemlig-cheaper` does alone, and say so. Finish with the new
   basket total and slot from that output.

## Rules

- The run asks the user at three points only: the slot and nights (when missing), the dinners'
  two checkpoints (the restock maybes ride along with the first), and the closing question.
  Everything else is decided and reported.
- Each sub-skill gets the slot and its instructions from this skill and hands back one block.
  Only this skill reports to the user.
- Never `basket add` twice for the same items. If an add fails, follow the base skill's
  *Changing the basket* rules before going on.
