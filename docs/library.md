# The Python library

`NemligClient` (`src/nemlig/client.py`) is the API the CLI and the skills are built on. The
quickstart is in the [README](../README.md#library).

## Client API

All methods are synchronous and return pydantic models (snake_case, JSON-serializable via
`model_dump(mode="json")`). Personal data in nemlig's responses (names, addresses, email, phone,
driver notes, order numbers) is never mapped into the models.

Search, suggestions, product pages, delivery days and offers also work without an account:
`NemligClient()` with no credentials and no saved session.

| Area | Methods |
| --- | --- |
| Session | `login()`, `logout()`, `is_logged_in()`, `get_account()`, `get_delivery_context()` |
| Search | `search(query, limit, offset, slot_id)`, `search_many(queries, limit, offset, slot_id)` (parallel), `suggest(query)`, `get_product(id_or_slug)` |
| Basket | `get_basket()`, `add_to_basket(id, qty)` (additive, negative subtracts), `set_quantity(id, qty)` (absolute), `remove_from_basket(id)`, `remove_sold_out()`, `clear_basket()` |
| Delivery | `get_delivery_days(days, start)`, `reserve_slot(slot_id)`, `get_slot_context(slot_id)` |
| Orders | `get_orders(limit, page)`, `get_all_orders()`, `get_order(order_id)`, `get_orders_many(ids)` (parallel), `reorder(order_id)`; `OrderCache().sync(client)` and `.load(client.account_key())` keep finished orders in `~/.cache/nemlig/orders` |
| Favourites and offers | `get_favourites()`, `get_offers(limit, slot_id)` |
| Shopping lists | `get_shopping_lists()`, `get_shopping_list(id)`, `create_shopping_list(name)`, `set_shopping_list_item(list_id, product_id, qty)`, `delete_shopping_list(id)`, `add_shopping_list_to_basket(id)` |

## Behaviour worth knowing

- **Expired sessions.** nemlig doesn't return 401 for an expired session; it silently answers
  as an anonymous user with an empty basket. Before every account call the client checks that
  its bearer token carries a customer id. If not, it logs in again (when it has credentials) or
  raises `NotLoggedInError`.
- **Writes are never retried.** Only GETs are retried (408/425/429/5xx, with backoff), because
  `add_to_basket` is not idempotent.
- **Errors.** `ApiError` (with nemlig's `error_code`), `AuthError` (wrong username or password),
  `NotLoggedInError`, `QueueItError`, all subclasses of `NemligError`.
- **Session file.** Override with `session_file=` or `NEMLIG_SESSION_FILE`; `persist=False`
  keeps the session in memory only. It is written with mode 600, and records a hash of the
  username so a client with credentials never reuses another account's session.
- **Not thread-safe.** Use one client per thread.
- **Prices and offers depend on the delivery slot.** Search and offers use the basket's slot
  (with none chosen, nemlig picks the earliest), or the site's default when anonymous. Pass
  `slot_id` to price them for another slot without reserving it.
- `clear_basket()` empties the lines but keeps the reserved slot. Nothing releases a slot.
