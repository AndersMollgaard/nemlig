---
name: nemlig-fill-basket
description: Fill the user's nemlig.com basket for the week in one run. Restocks the usual items that are due, plans dinners around the offers with the user, then proposes cheaper swaps for the whole basket, and reports once, with a recipe page written in the background. Use when the user asks to fill their basket, do the weekly shop, or make a basket for the week.
allowed-tools: Bash(nemlig:*), Bash(uv run nemlig:*)
---

# Fill the nemlig basket for the week

This skill chains the sub-skills in a fixed order: slot, restock, dinners, cheaper. Restock
comes first so its lines count as at home when the dinners are priced. Every basket add carries
the cheaper search for the lines it adds, so the swaps are ready at the report without a pass of
their own. Once the dinners are added, a background agent writes the recipe page while the run
goes on. The run builds on the current basket and never clears it.

**Speed.** The user waits on every model turn, so this flow is laid out turn by turn. Each
numbered step is one message: run its calls together, and don't split them. Reads go in the same
Bash call as the write before them (`basket add …; search …`).

## Flow

1. **Load and read, in one message.** Make four `Skill` calls, for `nemlig-shopping`,
   `nemlig-restock`, `nemlig-dinners` and `nemlig-cheaper`, and the context Bash call, all in
   the same message. Their rules apply here and are not repeated. The context call:
   - When the request names no delivery day:
     ```sh
     nemlig --text prefs; nemlig --text basket; nemlig --text orders show; nemlig --text restock --exclude "kød & fisk"; nemlig --text offers --category koed fisk-og-skaldyr groentsager faerdigretter-og-koederstatning --min-discount 20 --limit 0
     ```
     Restock and offers are for the basket's slot. When it is `(reserved)`, they are the
     run's, and step 2 is skipped unless nights or people are missing.
   - When it names a day:
     ```sh
     nemlig --text prefs; nemlig --text basket; nemlig --text orders show; nemlig --text delivery --available --days 1 --start YYYY-MM-DD
     ```

   This is the run's only `prefs` read, and `orders show` is the latest order the dinners
   count as at home. Fresh meat and fish are left out of restock, because they are the dinners'
   job.
2. **Slot and nights: one question, then reserve.**
   - Slot: the one the user named, or the basket's `(reserved)` slot. `(not reserved)` is only
     the earliest free slot, so it doesn't count.
   - Nights and people: from the request, or `household`.

   Ask once, in one short message, for whatever is missing ("Which day and time is the
   delivery, and how many dinners?"). Add nothing before it is answered. If the user names a
   day, find it with `nemlig --text delivery --available --days 1 --start YYYY-MM-DD`.

   When the slot isn't the basket's reserved one, reserve it and read restock and the offers
   for it in one call. Choosing the slot counts as asking for the reservation:
   ```sh
   nemlig --text delivery reserve SLOT_ID && nemlig --text restock --exclude "kød & fisk" --slot SLOT_ID && nemlig --text offers --category koed fisk-og-skaldyr groentsager faerdigretter-og-koederstatning --min-discount 20 --limit 0 --slot SLOT_ID
   ```
   If the reservation fails, nothing else runs. Stop there, as in the base skill's *Reserving a
   delivery slot*. Keep the price change and the `undeliverable:` lines for the report. From
   here on, every `restock`, `offers` and `search` gets `--slot SLOT_ID`. The basket's last
   line gives the id (`slot 2405499`).
3. **Restock, with the first cheaper search.** If restock says `to review`, review first, as in
   `nemlig-restock`. Judge the rows as in its *Chained* section. Then make one Bash call: add the
   due rows, and search for cheaper swaps for the lines already in the basket and the due rows,
   with queries as in `nemlig-cheaper`:
   ```sh
   nemlig --text basket add ID:QTY ...; nemlig --text search Q1 Q2 --limit 8 --cheaper-than ID1 ID2 --slot SLOT_ID
   ```
   If nothing is due, run only the search, and say so in the report.
4. **Checkpoint 1.** Run `nemlig-dinners` *Chained*, with the slot id, the nights and the
   people. Its offers are already read. Above its first checkpoint, show what step 3 added in
   one line, with the total from `added:`, then the maybes by letter. That way the user
   answers both in one reply:
   ```
   Restocked 6 usual items (187.40 kr): letmælk, solsikkerugbrød, bananer, ...
   Maybe due, pick by letter with the anchors: a. Toiletpapir 8 rl. (last 21/09)  b. Grovhakket leverpostej, 3 for 50 kr (-25%)  c. Falke hvedemel 2 kg
   ```
   The user picks the anchors by number and the maybes by letter ("★ and a, c"). No letters
   means none.
5. **Dishes.** Make up the dishes, then make one Bash call:
   1. Add the picked maybes, so they count as at home.
   2. Run the dish search.
   3. Run the cheaper search for the maybes.
   ```sh
   nemlig --text basket add ID:QTY ...; nemlig --text search kartofler citron "frisk timian" --limit 3 --slot SLOT_ID; nemlig --text search Q1 --limit 8 --cheaper-than ID1 --slot SLOT_ID
   ```
   Then price the dishes with `nemlig --text dishes` and show checkpoint 2, as in
   `nemlig-dinners`.

   When there is no first checkpoint (no dinners this time, or "just pick"), the maybes go to
   the closing question instead.
6. **Add the dinners and start the recipes, in one message.** Send two calls in parallel:
   - **Bash:** `dishes add` for the picked codes, then the cheaper search for the dinner lines:
     ```sh
     nemlig --text dishes add 1a 2a 2b; nemlig --text search Q1 Q2 --limit 8 --cheaper-than ID1 ID2 --slot SLOT_ID
     ```
   - **`Agent` (general-purpose, background):** the prompt "Load the `nemlig-recipes` skill
     and follow its *Subagent* section with this brief:", followed by the brief, in the format
     that skill shows. Build the brief from what the run already has:
     - `household` and `diet` from `prefs`
     - the slot
     - the dishes and their costs from the `dishes` output
     - the bought products from the search output and the spec

     Don't wait for it.

   Skip the `Agent` call when the run adds no dinners.
7. **One report, one question.** First judge every `cheaper than` block from steps 3, 5 and 6
   as in `nemlig-cheaper`, only for lines still in the basket. The rows already carry the
   saving. Then build the report from the handoffs and the last basket output. If that output
   says `(not reserved)`, the hold has lapsed: reserve the slot again first, and take the slot
   from that output.
   ```
   Restocked (8 lines, 231.30 kr): 3 x Letmælk 1,5%, Solsikkerugbrød, 10 x Banan, Toiletpapir, ...
   Merged in restock: æg = frilandsæg + skrabeæg
   Dinners:
   - Fri: Ovnstegt kylling med citron og kartofler, 131 kr
   - Sat: Culotte med bagte rodfrugter, 325 kr (Sun: steaksandwich from the leftovers)
   Cheaper swaps (saves 19.90 kr):
   1. Minimælk øko 1 l, Arla 2x → Øko 2x: 25.95 → 20.95 kr/l, saves 10.00 kr
   2. Hakket oksekød 8-12% 500 g, Coop → Danish Crown (2 for 90 kr): saves 9.90 kr
   Recipes: https://claude.ai/artifact/... (Fri, Sat)
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
   - `Recipes:` gives the link if the recipe agent has handed it back. Otherwise write
     "Recipes: on their way". When the agent hands back later, give the link in one line, in
     the next message or in the reply to the closing question. If it failed, say so in one
     line and offer to make the page with `nemlig-recipes`.

   The restocked line counts the due items and the picked maybes together.

   Apply the answer in **one** `basket set`. It is absolute, so it is safe to repeat after an
   error:
   - accepted swaps as `OLD_ID:0 NEW_ID:QTY`
   - dropped restock lines as `ID:0`
   - picked maybes as `ID:QTY`
   - things the user adds, at their total quantity (one `search` with `--slot` first)

   Record a "never" as `nemlig-cheaper` does alone, and say so. Finish with the new basket
   total and slot from that output. A swap keeps the kind of product, so the recipe page stays
   right. If the user drops or changes a dish, say the page is out of date and offer to redo
   it.

## Rules

- The run asks the user at three points only: the slot and nights (when missing), the dinners'
  two checkpoints (the restock maybes ride along with the first), and the closing question.
  Everything else is decided and reported.
- Each sub-skill gets the slot and its instructions from this skill and hands back one block.
  Only this skill reports to the user. The recipe agent is the exception. It runs on its own,
  never asks, never touches the basket, and hands back only a link.
- Never `basket add` or `dishes add` twice for the same items. If an add fails, follow the base
  skill's *Changing the basket* rules before going on.
