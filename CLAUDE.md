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

Django 6 · HTMX 2 · Tailwind 4 (CDN, no build step) · SQLite in development,
MariaDB in the shop · Django auth with a custom `accounts.User`.

**Django 6, not the spec's Django 5** — this machine runs Python 3.14, which
Django 5.2 does not support.

## Configuration and deployment

Everything environment-specific is read from a **`.env`** beside `manage.py`
(gitignored; `.env.example` is the committed template). Real environment
variables override the file. Full deployment steps: `DEPLOYMENT.md`.

- **`DEBUG` defaults to False**, and with it off the app **refuses to start**
  without a `SECRET_KEY`. Both are deliberate: forgetting a setting should
  fail on a laptop rather than quietly ship tracebacks to the shop. A fresh
  clone therefore needs a `.env` before it will run at all.
- `ALLOWED_HOSTS` takes bare hostnames; `CSRF_TRUSTED_ORIGINS` needs the
  scheme. Getting the second wrong makes pages load and every form fail.
- All the HTTPS-dependent settings hang off one `HTTPS` flag, off by default.
  Turning it on before Apache serves a certificate does not warn — it makes
  cookies secure-only and nobody can log in.
- `STATIC_ROOT` + `collectstatic` are required in production: with `DEBUG` off
  Django serves no static files, so skipping it yields a working app with no
  styling at all.
- Unhandled exceptions go to `logs/mentor.log` (rotating). With `DEBUG` off
  they would otherwise go nowhere.
- **Database**: **SQLite in the shop as well as in development.** That is a
  decision, not a leftover: one machine runs everything off one disk, so the
  usual objections (several web servers sharing a database over a network,
  heavy concurrent writes) do not apply, and a backup is a file copy.
  - `DB_ENGINE=mysql` switches to MariaDB with utf8mb4 and
    `STRICT_TRANS_TABLES`, but **XAMPP cannot run it**: XAMPP bundles MariaDB
    10.4 and Django 6 requires 10.6+, so it refuses with
    `NotSupportedError: MariaDB 10.6 or later is required (found 10.4.32)`.
    Tried on 2026-08-04; no setting fixes it. It needs a newer MariaDB
    installed outside XAMPP.
  - `config/__init__.py` prefers `mysqlclient` and falls back to **PyMySQL** —
    pure Python, so `pip install` cannot fail for want of a C compiler. Do not
    override `pymysql.version_info` there: PyMySQL already reports the
    mysqlclient release it emulates, and overriding it breaks Django's check.
- **Serving**: `serve.py` runs Waitress (gunicorn is not an option on Windows);
  Apache reverse-proxies to it and serves `/static/` itself. Django does not
  run inside Apache — `mod_wsgi` is compiled and version-tied.

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

## Navigation

Three pages, defined once in `orders/context_processors.py` as `NAV_LINKS`
(url name, label, admin-only) and rendered as a loop in `base.html`. Add a page
by adding a tuple, not by editing markup.

| Link | URL | Who sees it |
|---|---|---|
| Home | `/` | everyone |
| Dashboard | `/dashboard/` | admins |
| History | `/history/` | admins |
| Sellers | `/sellers/` | admins |
| Products | `/products/` | admins |
| Users | `/users/` | admins |

Wordmark, nav pills and account details share one row; the account block takes
`ml-auto` so it hugs the right edge whatever the nav's width, and the row wraps
rather than crushing on a narrow screen. The current page is a filled pill and
carries `aria-current="page"`, off `request.resolver_match.url_name`. An
employee sees a one-link nav, which is correct if sparse.

`/sellers/` is full CRUD: substring search over name/phone/email, add and edit
through the shared `<dialog id="modal">`, and deactivate/reactivate. **Delete
is a deactivation** — rule 3 keeps sellers as rows because history reaches them
through their products. Inactive sellers stay listed here (this is the only
page that can revive one) while dropping out of product search and the
new-product dropdown.

`/users/` is user admin, living in the `accounts` app (views, forms, urls,
templates under `templates/accounts/`) since it is about people, not orders.
Search, add, edit and deactivate, same dialog pattern. Nobody self-registers.

Two rules protect the shop from being locked out of its own app, and both are
worth keeping in mind before touching that view:

- **You cannot deactivate or demote your own account.** This is what actually
  maintains "at least one active admin": whoever is clicking is an active
  admin, so any *other* account can safely go.
- `User.is_last_admin()` blocks demoting the final admin. Given the rule above
  it is **currently unreachable** in both the view and the form — kept as a
  backstop in case access ever widens, and commented as such. Do not write a
  test that pretends to reach it; test the invariant instead.

Passwords go through `AUTH_PASSWORD_VALIDATORS` on create and on change.
Editing with the password boxes left blank keeps the existing password, so
fixing somebody's email cannot silently lock them out.

Dialog saves reply with `HX-Retarget: #seller-list` plus an `HX-Trigger`
carrying both the toast and a `closeModal` event — the form posts from inside
the dialog, so the fresh list must be aimed at the page behind it. `_trigger()`
merges events so a response can fire several. Backdrop/`closeModal` handling
lives in `static/js/modal.js`, loaded on every page and inert without a dialog.

## Editing a product

Clicking a **product name** on either the order list or the dashboard opens the
catalog entry in the shared dialog — name, `order_name`, seller, unit, price.
That is a different thing from the pencil on the right, which edits the *row*
(quantity, urgency), hence a separate control.

- `ProductForm` serves add and edit. Its case-insensitive duplicate check
  **excludes `self.instance.pk`**; without that, saving a price change would
  clash with the product's own name.
- The form posts from inside the dialog, so it always targets `#modal-body` and
  the response cannot tell which page opened it. An `origin` value (`panel`,
  `dashboard` or `products`) travels on the GET and again as a hidden field,
  and decides the `HX-Retarget`. It is re-rendered on a rejected save so fixing
  the error still refreshes the right page. `q` rides along the same way, so
  editing from `/products/` keeps the current search.
- `/products/` is the catalog page: substring search over name, `order_name`
  and seller, plus edit. **Adding** stays on the order list, where it is useful
  mid-order — the success path there returns a script calling `selectProduct()`,
  which only exists on that page. Matching here is plain `icontains`, not
  `search.search_products`, whose fuzzy ranking exists to forgive typos while
  ordering; managing a catalog wants predictable results.
- Editing a product **never touches open order items**: quantities are their
  own and `unit_price_snapshot` keeps the price they were requested at, per
  rule 2. A new price applies only to what is added next.

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
  wrap a response in `_toast(response, message)`; `static/js/app.js` listens
  for the `toast` event and builds the element.
- **CSS and JS live in `static/`, never inline in a page template.**
  `static/css/app.css` plus `static/js/app.js` (loaded by `base.html` for every
  page) and `static/js/product-search.js` (pulled in through the `extra_head`
  block by the one page that needs it). Both scripts are `defer`, so the DOM is
  parsed before they run.
  - `app.css` holds only what a utility class cannot reach: elements built at
    runtime by JS, states applied at runtime, and browser-owned pseudo-elements
    like `::backdrop`. Ordinary styling stays as Tailwind classes in the markup.
  - The **exception** is a fragment returned to htmx — `_product_created.html`,
    `_duplicate_warning.html`, the focus line in `_panel.html`. Those scripts
    work precisely because they execute when swapped in, so they stay inline.
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
- `Product.order_name` — optional: the seller's own name for the item, for use
  when placing the order. Settable in the new-product modal (everyone) and
  **displayed only on the admin dashboard**, where an order is actually placed.
  It never appears in product search or the employee order list, and search
  still matches on `name` alone. It was admin-only at first; showing it in the
  add form was a later, deliberate change.
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

**Done — the admin dashboard** (`/dashboard/`, admin-only, read-only so far)
- Open items grouped by seller, sellers alphabetical, urgent first within each.
- Per-seller total and urgent count, plus a summary across all sellers. Totals
  use the frozen `unit_price_snapshot`, never the live catalog price.
- **Tapping the seller's phone number copies that supplier's whole order and
  opens their Viber chat**, so sending is one paste rather than a contact
  search. `_order_message` builds the text: products named `order_name or
  name`, urgent items flagged, quantities stripped of trailing zeros, prices
  left out — it says what the shop wants, not what it expects to pay.
  - **Viber has no scheme carrying both a recipient and text.**
    `viber://chat?number=` opens the right chat and silently drops any text;
    `viber://forward?text=` carries text but asks which chat. That is why
    `static/js/order-message.js` copies to the clipboard and then navigates to
    the chat. Do not try to merge the two URLs — the text vanishes with no error.
  - The behaviour is **the same on every device and origin**, deliberately.
    `navigator.clipboard` is undefined on an insecure origin — which is exactly
    how a phone reaches a dev server — so `copyText()` falls back to an
    off-screen `<textarea>` plus `document.execCommand("copy")`, which has no
    secure-context requirement. Do not drop that fallback: without it the copy
    silently does nothing over plain HTTP.
  - The link's `href` is the **chat** URL, so a failed script degrades to
    opening the chat rather than doing nothing.
  - `viber://forward` now appears **only** for sellers with no phone number,
    where there is no chat to open.
  - A labelled **Send order** button appears only for sellers with no phone
    number, so every supplier has exactly one way to send and none are stranded.
  - Phone numbers should be stored in **international format** (`+30…`).
    `viber://chat?number=` resolves a contact far more reliably with a country
    code; a bare local number may simply not be found.
  - `Seller.viber_url` still powers the plain chat link on `/sellers/`, where
    there is no order to attach. Numbers are stored as people write them, so it
    strips all but digits and a leading `+` and percent-encodes the `+`; a field
    holding only punctuation yields `""` so no dead link renders. The number
    stays visible as text — the link is inert unless Viber is installed and the
    seller is a Viber user, which a landline will not be.
- `order_name` surfaces here and nowhere else.
- A seller filter (`?seller=<pk>`) narrowing the page to one supplier. Its
  options are built from the groups, not from `Seller.objects`, so it can only
  offer a seller that has something open — no choice leads to an empty page,
  and a seller whose last item was just completed drops out of the list. An
  unknown or malformed pk falls back to showing everything rather than erroring.
  The summary follows the filter; the option list does not, or picking a seller
  would leave no way back.
- Filtering swaps `_dashboard_body.html` via htmx on the same URL, chosen by
  the `HX-Request` header, with `hx-push-url` — so `?seller=` stays shareable
  and the back button works.
- Gated by `accounts.decorators.shop_admin_required`: employees get a 403, not
  a login redirect, since re-logging-in would never grant access. The header
  link only renders for admins.

- Per-row actions: mark ordered, edit in place, delete. Completing is
  admin-only (`complete_item`); editing and deleting reuse the employee views.
  Each screen gets its own fragment back, chosen by the `HX-Target` header, so
  one view serves both without a flag threaded through the templates. Row
  actions `hx-include` the seller filter, so acting while filtered stays
  filtered.
- "Mark all as ordered" per seller (`complete_seller`) — rule 4's whole-seller
  batch. One `.update()` over the seller's open rows, so the whole batch shares
  a single `completed_at`; that shared timestamp is what will let order history
  group a batch without a batch table. No rows changed (double tap, another
  tab) re-renders without a toast rather than 404ing, since htmx swallows a
  404 and would leave stale markup on screen.
- Seller headers are a solid `#4a7355` bar — the lightest of the three greens
  that can carry white text (5.42:1). Secondary text on it is `stone-100`
  (4.97:1); `stone-200` measures 4.32:1 there and is under the floor. The brand
  `#71a07c` is never a text background at any size.
- Both the dashboard and the employee list show `€unit/measure · €line total`
  per row, using `unit_price_snapshot`. The live catalog price would contradict
  the line total, which is quantity times the snapshot.

**Done — order history** (`/history/`, admin-only)
- Completed orders newest first. **An order is a batch**: completing one item
  or a whole seller writes the same `completed_at` to every row it touches, and
  those timestamps are microsecond-precise, so no two actions collide. That
  shared timestamp identifies a batch without the table rule 4 forbids.
- Period filter (24 hours / 7 days / 30 days / all time) and page size
  (5/10/20/50, default 20), both validated against their allowed values — an
  unoffered `?size=` would otherwise be a way to load the whole table.
- **Paging is over the distinct timestamps, not the rows**, so a page is twenty
  *orders* rather than twenty items and the database does the slicing. Only the
  current page's rows are then fetched; this table is the one expected to grow
  without limit. Keep it that way — grouping in Python over the whole queryset
  would load everything ever ordered.
- Filters travel in every pager link, so paging cannot quietly widen the window.
  A junk or out-of-range `?page=` lands on the first or last page rather than
  404ing, which is what a stale bookmark deserves.

- **Undo** (`uncomplete_item`), on every history row: clears `completed_at` and
  `completed_by` so the item returns to the list. Refused when that product
  already has something open — rule 1 keeps a product off the list twice, and
  if it is already back there then what the admin wanted is already true.
  Filters and page ride in the URL's query string, not `hx-include`, because
  the page number is not an input on the screen.

**Which actions ask for confirmation, and why**

| Action | Confirm? | Reason |
|---|---|---|
| Mark one item ordered | no | fastest, most repeated action; undo is one tap |
| Mark a whole seller ordered | **yes** | undo is per item, so reversing ten is ten taps |
| Delete an open item | **yes** | the row is gone for good, nothing to undo |
| Undo a completion | **yes** | it puts an item back on the live order list |

**Not started**
- Multi-select completion (picking several specific items across the list).
  Individual and whole-seller batch both exist; this is the remaining mode.
- Order history (admin-only).
- Admins adding new sellers (employees cannot).
- Any mobile pass over the finished employee page.
