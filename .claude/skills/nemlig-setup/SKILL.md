---
name: nemlig-setup
description: First-run setup for the nemlig.com skills. Links the skills for Claude Code and Codex, gets the login working, asks about the household to write the preferences, and syncs and reviews the order history for restocking. Use when the user asks to set up nemlig, get started, or "set me up", or when the nemlig credentials or preferences are missing. Does not shop.
allowed-tools: Bash(nemlig:*), Bash(uv run nemlig:*)
---

# Set up nemlig

Load `nemlig-shopping` first if it isn't loaded. Its CLI rules apply here.

Each step is safe to run again, so on a second run skip what is already done. Keep the user's
part short: one message with the questions, not one per question.

## Flow

1. **Check, in one Bash call:** `nemlig --text setup; nemlig --text status`.
   - If `nemlig` is not on PATH, run `uv run nemlig --text setup` from the repo root. Offer
     `uv tool install --editable .` there, so the skills work from any directory, and run it if
     the user agrees.
   - `setup` links the skills for the agents it finds, creates `preferences.toml` from the
     example when missing, and prints where `.env` and `preferences.toml` are. If you are the
     agent it didn't link for, run `nemlig --text setup --agent codex` (or `--agent claude`).
   - A `skipped` skill has something else in its place in the skill folder. Tell the user and
     leave it.
   - Newly linked skills show up in a new session of the agent.
2. **Credentials.** If `setup` says `credentials: missing`, the user fills them in. Never ask
   for the password in chat, and never read or print `.env`. Tell them to copy `.env.example`
   to the path `setup` printed and set `NEMLIG_USER` and `NEMLIG_PASS`, then say when done.
   Then run `nemlig --text login`. Exit 3 means the login was rejected; ask them to check
   the file.
3. **Household, in one message.** Ask, with the current values from `nemlig --text prefs`
   when there are any:
   - who eats: adults, and children with their ages
   - diet: anything never to buy (pork, nuts, lactose...)
   - always: what must be a certain kind (øko milk, frilandsæg...)
   - budget for a week, if any
   - brands or products to always keep, or never to suggest

   Write the answers into the `preferences.toml` that `setup` printed, as the free-text keys
   `household`, `diet`, `always` and `budget`, replacing the commented examples. Leave out a
   key with no answer. Keep each value one or two plain sentences. Add keep and avoid rules
   with the CLI, as in `nemlig-shopping`, for example
   `nemlig --text prefs avoid --brand "First Price" --name toiletpapir --note "too thin"`.
   Finish with `nemlig --text prefs` to check it parses.
4. **Order history.** `nemlig --text orders sync; nemlig --text restock groups`. Review the new
   products as in `nemlig-restock` (merge only what is clearly the same need), then mark them
   reviewed with `nemlig --text restock groups reviewed`. With no past orders, skip this and
   say restocking starts working after a few orders.
5. **Report**, in a few lines: what was linked, that the login works, the preferences in one
   line, and how many orders are cached. End with what to try next: "fill my basket",
   "dinners for 3 nights", "anything cheaper in my basket?".
