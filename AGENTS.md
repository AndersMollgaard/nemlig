# AGENTS.md

An unofficial client for nemlig.com. `src/nemlig/client.py` holds the API (one method per
operation, returning pydantic models), and `src/nemlig/cli.py` is the `nemlig` CLI built on it
for agents. Nemlig has no public API, so `docs/nemlig-api.md` is the endpoint reference: read it
before changing any request. `docs/fixtures/` holds redacted real responses for the tests.
`docs/roadmap.md` is the plan for the basket-filling skills. Read it before working on them, and
tick off steps as they land.

```sh
uv run pytest                             # offline, against the fixtures
uv run ruff check . && uv run ruff format --check .
NEMLIG_LIVE=1 uv run pytest -m live       # real site with the .env account; only when needed
```

- Never retry writes. `add_to_basket` is not idempotent, so only GETs are retried.
- An expired session doesn't return 401. nemlig answers as an anonymous user. Keep the
  customer-id check on the JWT before account calls.
- Keep personal data (names, addresses, contact details) out of the models and fixtures.
- CLI output costs tokens on every agent call. Keep it lean, and prefer dropping a field to
  adding one.
- When CLI behaviour changes, update `README.md` and `.claude/skills/nemlig-shopping/SKILL.md`.
- `.env` holds real credentials. Never print it or commit it.
