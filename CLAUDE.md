# Mentor — working notes for Claude

Internal coffee-shop procurement tool. Employees flag products running low;
an admin sees them grouped by seller, places the orders outside the app, then
marks them completed.

Full requirements: [`specs/mentor-app-spec.md`](specs/mentor-app-spec.md).
Run/reset/login instructions: [`README.md`](README.md).
This file records the decisions and constraints that the spec does not.

## How to work on this

- **One reviewable slice at a time.** Build a slice, stop, and let the user
  look at it. Do not run ahead into the next feature.
- **Raise spec tensions instead of silently resolving them.** The user wants
  objections and feedback on the spec, not quiet workarounds.
- **Tests are wanted now.** The earlier hold was lifted on 2026-08-03. Keep
  the suite green and extend it with each slice — `manage.py test`.
- **The user runs the dev server.** Hand them the command; don't start one and
  leave it running — it holds port 8000 and breaks their own `runserver`.
  Prefer verification that needs no server: `manage.py check`, `manage.py
  shell`, reading rendered templates.

## Stack

Django 6 · HTMX 2 · Tailwind 4 (CDN, no build step) · SQLite · Django auth
with a custom `accounts.User`.

**Django 6, not the spec's Django 5** — this machine runs Python 3.14, which
Django 5.2 does not support.

## Design constraints

**The app is used mostly on phones.** This is the most load-bearing constraint
on any UI work: large tap targets, 16px inputs so iOS does not zoom on focus,
layouts that survive a narrow screen.

**Colour.** The shop's colour is `#71a07c`. It measures 2.99:1 on white —
below the 3:1 floor even for large text — so it is **decorative only**: never
behind text, never as text. Text and buttons use darker siblings of the same
hue:

| Colour | Contrast on white | Use |
|---|---|---|
| `#71a07c` | 2.99:1 | borders, focus rings, checkbox accent — never text |
| `#4a7355` | 5.42:1 | wordmark, primary buttons |
| `#3d6047` | 7.09:1 | button hover, toast background |

Red is reserved for urgency. It is never a brand colour.

## Tests

`manage.py test` — 73 tests, no external dependencies, ~2.5s.

Tests live inside the app they cover, per Django's convention. `orders` has
outgrown a single module, so it uses a `tests/` package; `accounts` still fits
in one `tests.py` and stays that way until it doesn't. New test modules must be
named `test_*.py` or the runner will not find them, and imports are absolute
(`from orders.models import ...`) — a relative `from .models` inside the
package resolves to `orders.tests.models` and fails.

| File | Covers |
|---|---|
| `accounts/tests.py` | roles, `is_shop_admin` vs `is_staff`, login, persistent session |
| `orders/tests/test_search.py` | search ranking: prefixes, typos, seller fallback |
| `orders/tests/test_models.py` | per-seller uniqueness, `PROTECT`, price snapshot, `line_total` |
| `orders/tests/test_forms.py` | the urgent tick box, quantity/price floors, case-insensitive duplicates |
| `orders/tests/test_views.py` | the HTMX contract: status codes, `HX-*` headers, which fragment comes back |

Two things that bite when writing more:

- **Use `Decimal`, not `str`, in fixtures.** `Product.objects.create(unit_price="1.15")`
  leaves the *in-memory* instance holding a string — no coercion happens until
  a database round trip — so `line_total` raises `TypeError`. A fetched object
  is fine; a just-created one is not.
- **The view tests assert on headers**, not just markup: `HX-Trigger` carries
  the toast, `HX-Retarget` redirects the duplicate warning into the modal, and
  invalid forms must answer `422` (not 400) or htmx drops the response.

## Decisions that differ from the spec

Both agreed with the user:

1. **Products are unique per seller**, not globally (`UniqueConstraint` on
   `seller, name`). The same item can be stocked from two suppliers without
   renaming it.
2. **The duplicate warning offers only "update the quantity"** — there is no
   "add anyway", despite the spec's wording.

## Architecture conventions

- **Every mutation re-renders the whole panel** (`orders/_panel.html`) into a
  single HTMX swap targeting `#panel`. The item count and the list can never
  drift apart, and the add form clears itself just by being rendered fresh.
- **Toasts ride on the `HX-Trigger` header**, not the swapped markup. Views
  wrap a response in `_toast(response, message)`; `base.html` listens for the
  `toast` event and builds the element. Toast CSS is plain CSS, not Tailwind
  classes — a CDN Tailwind build has no markup to generate them from.
- **Invalid forms answer `422`** with the re-rendered form. `base.html` has an
  `htmx:beforeSwap` hook opting that one status back into swapping, since htmx
  ignores 4xx by default.
- **CSRF is a body-level `hx-headers` attribute**, so buttons that post from
  outside a `<form>` (delete) carry the token too.
- **The duplicate warning retargets mid-flight** — `add_item` answers with
  `HX-Retarget: #modal-body` so one form post can reply into the modal instead
  of the panel it aimed at.
- **Search ranks in Python** (`orders/search.py`), not SQL: word-prefix
  matching with typo tolerance on plain SQLite, no search extension. Fine for a
  coffee shop's catalog; revisit past a few thousand rows.

## Progress

**Done — models and auth**
- `accounts.User` extends `AbstractUser` with unique email + `role`
  (employee/admin) and an `is_shop_admin` property.
- `Seller`, `Product`, `OrderItem` per the spec's schema: price snapshot on
  every order item, `PROTECT` on the FKs that history depends on, `is_active`
  soft-delete flags, `OrderItem.objects.open()` / `.completed()`.
- `Product.order_name` — optional, admin-only: the seller's own name for the
  item, for use when placing the order. Deliberately absent from the employee
  UI and from search, which still matches on `name`. Editable through the
  Django admin only, until the admin dashboard exists to carry it.
- Persistent login (30-day sliding session), login page, logout.
- `manage.py seed_demo` — idempotent demo sellers, products, open items, plus
  `maria` / `mentor123` (employee) and `admin` / `admin`.

**Done — the employee page** (`/`, the shared open order list)
- Quick-add: live product search (150ms debounce) resolving into a hidden id,
  quantity, urgent checkbox; focus returns to the search box after a
  successful add for fast back-to-back entry.
- "+ Add new Product" modal, prefilled with whatever was typed into the search
  box; on success it closes and drops the new product into the quick-add form
  so the interrupted flow resumes.
- Duplicate warning when the product already has an open item.
- Open-items list: inline edit (quantity + urgency) and delete with
  confirmation, urgency shown as a full-height red edge marker plus a badge,
  seller / requester / timestamp, line totals, empty state.
- Toasts confirming add, edit, delete and product creation.

**Not started**
- Admin dashboard: open items grouped by seller.
- Marking items completed — individually, multi-select, or per-seller batch —
  and undoing a completion.
- Order history (admin-only).
- Admins adding new sellers (employees cannot).
- Any mobile pass over the finished employee page.
