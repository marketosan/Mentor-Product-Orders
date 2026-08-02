    # Mentor — Coffee Shop Procurement App

## What this app does
Mentor is an internal tool for a coffee shop to track products that need to be reordered. Employees flag items running low with a quantity and urgency; the admin sees everything grouped by supplier, places the actual orders outside the app (phone, email, in person), then marks items as completed. The admin can also review order history.

## Recommended Tech Stack
- **Backend**: Django 5 (Python)
- **Frontend**: Django templates + HTMX for interactivity (live product search, inline add/complete actions) — no separate JS framework, no build step for v1
- **Styling**: Tailwind CSS via CDN — no build pipeline needed
- **Database**: SQLite for both development and production, for now — a one-line Django config change if a move to PostgreSQL is needed later as usage grows
- **Auth**: Django's built-in auth system, with the `User` model extended by a `role` field

A REST API + React/Vue frontend can be added later as a second phase without rewriting the Django models or business logic — v1 doesn't need to plan for that yet.

## User Roles
Two roles, one per user account:

**Employee**
- Can stay logged in across sessions (persistent / "remember me" login)
- Searches the product catalog
- Adds items to the shared order list with a quantity and urgency (low / high)
- Adds new products to the catalog (name, unit, price per unit, choosing a seller from the existing list — employees can't create new sellers)
- Can view the full open order list (everyone's items, not just their own) and edit or delete any item on it

**Admin**
- Logs in with admin credentials (same login form, different role/permissions)
- Has all the same abilities as Employee too (search products, add to order list, add new products, edit/delete any open order-list item) — implemented as the same shared pages/views rather than duplicated per role
- Can also add new sellers (employees cannot)
- Sees a main dashboard: all open order-list items, grouped by seller
- Marks items completed — individually, via multi-select (choosing several specific items), or as a whole seller batch — and can undo a completion if it was marked by mistake
- Views order history (admin-only — employees don't get this view, kept simple for them)

## Employee Main Page

The main page shows the full open order list, with a quick-add form pinned above it:

- Product field is a live search-as-you-type (same search used elsewhere), plus quantity and urgency.
- Pressing Enter or the Add button submits the new item straight into the list below **without a full page reload** — an HTMX request swaps in the updated list.
- On success, the form clears itself immediately so the next item can be typed right away, supporting fast back-to-back entry without touching the mouse.

## Database Schema

```
users
  id              PK
  username        unique, not null
  email           unique, not null
  password_hash   not null
  role            enum(employee, admin), not null
  is_active       boolean, default true
  created_at      timestamptz

sellers
  id              PK
  name            unique, not null
  phone           nullable
  email           nullable
  notes           nullable
  is_active       boolean, default true
  created_at      timestamptz

products
  id              PK
  name            unique, not null
  unit            enum(kg, g, l, ml, piece, pack, box), not null
  unit_price      numeric(10,2)               -- current price, euros
  seller_id       FK -> sellers.id ON DELETE RESTRICT
  is_active       boolean, default true
  created_by      FK -> users.id
  created_at      timestamptz

order_items
  id                    PK
  product_id            FK -> products.id ON DELETE RESTRICT
  quantity              numeric(10,3)         -- e.g. 1.5 kg
  urgency               enum(low, high), default low
  unit_price_snapshot   numeric(10,2)         -- price at time of request
  requested_by          FK -> users.id
  created_at            timestamptz
  completed_at          timestamptz, nullable  -- null = open, set = completed
  completed_by          FK -> users.id, nullable
  INDEX (completed_at, product_id)
```

**Relationships**: one seller → many products. One product → many order_items.

## Key Business Rules

1. **Duplicate warning, not auto-merge.** Before an employee adds a product to the order list, check for an existing `order_items` row for that product where `completed_at IS NULL` (still open). If one exists, warn them (e.g. "Coffee beans is already on the list — 5 kg requested by Maria — add anyway, or update the existing quantity?") instead of silently creating a duplicate or merging quantities automatically.

2. **Price snapshot for accurate history.** `order_items.unit_price_snapshot` stores the product's price at the moment it was added to the list. Later changes to `products.unit_price` must not retroactively change historical order records.

3. **Soft delete only.** Products and sellers are deactivated (`is_active = false`), never hard-deleted — they're referenced by order history, and the FK constraints (`ON DELETE RESTRICT`) block deletion of anything with existing references anyway. Inactive sellers/products should be hidden from employee search and the "add product" seller dropdown, but remain visible in historical records.

4. **Completion is flexible and reversible.** Admin can mark items completed individually, via multi-select (picking several specific items across the list), or as a whole seller batch — all apply the same update to one or more `order_items` rows (setting `completed_at` and `completed_by`), not a separate "batch" table. Completing can be undone by clearing `completed_at` and `completed_by`, which moves the item back to open.

5. **Editing/deleting open items.** Editing an open item (`completed_at` still null) can change its `quantity` or `urgency` (swapping to a different product means adding a new item, not repointing an existing one). Deleting an open item removes the row entirely — nothing's been purchased yet for something still open, so there's no order history being lost.

## Not in scope for this version
Basic functionality only — more features are expected later, so keep the models reasonably extensible (e.g. don't hard-code assumptions that would block adding new order statuses, roles, or fields down the line).
