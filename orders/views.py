import json
from datetime import timedelta
from decimal import Decimal
from itertools import groupby
from urllib.parse import quote

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import shop_admin_required

from .forms import AddOrderItemForm, EditOrderItemForm, ProductForm, SellerForm, UnitForm
from .models import OrderItem, Product, Seller, Unit
from .product_import import (
    InvalidWorkbook,
    build_template_workbook,
    import_products,
    parse_workbook,
    workbook_to_bytes,
)
from .search import search_products

PANEL = "orders/_panel.html"
DASHBOARD_BODY = "orders/_dashboard_body.html"
PRODUCT_FORM = "orders/_product_form.html"
PRODUCT_LIST = "orders/_product_list.html"
PRODUCT_IMPORT_FORM = "orders/_product_import_form.html"
HISTORY_BODY = "orders/_history_body.html"
UNIT_LIST = "orders/_unit_list.html"
UNIT_FORM = "orders/_unit_form.html"

# Closes the order message. Greek, because it is read by the supplier, not
# by anyone using the app. The opening greeting depends on the time of day --
# see _order_greeting.
ORDER_SIGNOFF = "Ευχαριστώ"


def _trigger(response, **events):
    """Fire client-side events off the response, merging with any already set.

    htmx turns the HX-Trigger header into DOM events, which is how the server
    asks the page to do something -- show a message, shut a dialog -- without
    that instruction living in the swapped markup.
    """
    fired = json.loads(response.headers.get("HX-Trigger", "{}"))
    fired.update(events)
    response["HX-Trigger"] = json.dumps(fired)
    return response


def _toast(response, message):
    """Confirm an action to the user without putting it in the swapped markup."""
    return _trigger(response, toast={"message": message})


def _panel_context(*, add_form=None, edit_form=None, editing_id=None, just_added=False):
    """Context for the order panel.

    Every action re-renders the whole panel (form + count + rows) into a single
    HTMX swap. It keeps the count and the list from ever drifting out of sync,
    and the add form clears itself simply by being rendered fresh.
    """
    return {
        "items": OrderItem.objects.open().select_related(
            "product__seller", "product__unit", "requested_by"
        ),
        "add_form": add_form if add_form is not None else AddOrderItemForm(),
        "edit_form": edit_form,
        "editing_id": editing_id,
        "just_added": just_added,
    }


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@login_required
def order_list(request):
    """The shared open order list. Everyone sees every open item, not just
    their own, so the shop has a single view of what still needs ordering.
    """
    return render(request, "orders/order_list.html", _panel_context())


@login_required
def panel(request):
    """Re-render the panel, optionally with one row switched to edit mode.
    Serves both 'start editing' and 'cancel editing'.
    """
    editing_id = _int_or_none(request.GET.get("editing"))
    return render(request, PANEL, _panel_context(editing_id=editing_id))


@login_required
@require_POST
def add_item(request):
    form = AddOrderItemForm(request.POST)
    if not form.is_valid():
        return render(request, PANEL, _panel_context(add_form=form), status=422)

    existing = (
        OrderItem.objects.open()
        .filter(product=form.cleaned_data["product"])
        .select_related("product__unit", "requested_by")
        .first()
    )
    if existing:
        # Warn rather than silently duplicating or auto-merging quantities.
        # This reply goes to the modal, not to the panel the form aims at.
        attempted_quantity = form.cleaned_data["quantity"]
        response = render(
            request,
            "orders/_duplicate_warning.html",
            {
                "existing": existing,
                "attempted_quantity": attempted_quantity,
                "attempted_unit": existing.product.unit.label_for(attempted_quantity),
            },
        )
        response["HX-Retarget"] = "#modal-body"
        response["HX-Reswap"] = "innerHTML"
        return response

    item = form.save(requested_by=request.user)
    return _toast(
        render(request, PANEL, _panel_context(just_added=True)),
        f"{item.product.name} added to the list",
    )


@login_required
@require_POST
def edit_item(request, pk):
    item = get_object_or_404(OrderItem.objects.open(), pk=pk)
    form = EditOrderItemForm(request.POST, instance=item)
    if form.is_valid():
        form.save()
        return _toast(_render_after_change(request), f"{item.product.name} updated")
    return _render_after_change(request, status=422, edit_form=form, editing_id=pk)


@login_required
@require_POST
def delete_item(request, pk):
    """Open items can be deleted outright -- nothing has been bought yet, so
    there is no history to preserve.
    """
    item = get_object_or_404(OrderItem.objects.open(), pk=pk)
    name = item.product.name
    item.delete()
    return _toast(_render_after_change(request), f"{name} removed from the list")


def _format_quantity(quantity):
    """3.000 -> "3", 1.500 -> "1.5". The column is DecimalField(3), and
    Decimal.normalize() would turn 24.000 into 2.4E+1.
    """
    return f"{quantity:.3f}".rstrip("0").rstrip(".") or "0"


def _order_greeting():
    """Καλημέρα before 1pm local time, Καλησπέρα from 1pm on -- the supplier
    reads this in their own chat, so it follows the time they'll see it. On a
    Monday it adds "και καλή βδομάδα", since that is the first order of the
    week.
    """
    now = timezone.localtime()
    greeting = "Καλημέρα" if now.hour < 13 else "Καλησπέρα"
    return f"{greeting} και καλή βδομάδα" if now.weekday() == 0 else greeting + '!'


def _order_message(items):
    """The order written out, ready to send to the supplier.

    A time-of-day greeting, one bulleted `<quantity> <unit> <name>` line per
    item, and a closing thank-you -- reads like a message a person typed, not
    a numbered form. The name is the seller's own where `order_name` is set --
    that is the whole reason the field exists -- and the shop's name where it
    is not.

    The seller is not named in the message: it is sent to them, in their own
    chat. Prices are left out too -- this says what the shop wants, not what it
    expects to pay.
    """
    lines = [_order_greeting(), ""]
    for item in items:
        name = item.product.order_name or item.product.name
        urgent = " SOS" if item.urgency == OrderItem.Urgency.HIGH else ""
        lines.append(f"• {_format_quantity(item.quantity)} {item.unit_display} {name}{urgent}")
    lines += ["", ORDER_SIGNOFF]
    return "\n".join(lines)


def _viber_forward_url(message):
    """Open Viber with a message ready to send, asking which chat to send it to.

    Used only for sellers with no phone number. Where there is one, the Send
    order button copies the text and opens that seller's chat instead, since
    `viber://chat?number=` takes a recipient but silently drops any text and
    `viber://forward?text=` takes text but no recipient.
    """
    return f"viber://forward?text={quote(message, safe='')}"


def _sum_line_totals(items):
    """Total the rows that have a price, and count the ones that do not.

    Returns (total, unpriced_count). Unpriced rows are excluded rather than
    counted as zero, and the count travels alongside so the screen can say the
    figure is incomplete. A total that silently omits items is worse than no
    total, because it looks authoritative.
    """
    total = Decimal("0")
    unpriced = 0
    for item in items:
        line = item.line_total
        if line is None:
            unpriced += 1
        else:
            total += line
    return total, unpriced


def _open_items_by_seller():
    """Open items bundled into one group per seller, each with its own total.

    Grouping happens in Python rather than the template because a template
    `regroup` cannot also sum a group, and the admin needs the per-seller total
    to sanity-check an order before placing it.

    Urgency is ranked explicitly. Sorting on the raw column happens to work --
    "high" sorts before "low" -- but only by an accident of the alphabet that
    a third urgency level would silently break.
    """
    items = (
        OrderItem.objects.open()
        .select_related("product__seller", "product__unit", "requested_by")
        .annotate(
            urgency_rank=Case(
                When(urgency=OrderItem.Urgency.HIGH, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("product__seller__name", "urgency_rank", "product__name")
    )

    groups = []
    for seller, seller_items in groupby(items, key=lambda item: item.product.seller):
        seller_items = list(seller_items)
        message = _order_message(seller_items)
        total, unpriced = _sum_line_totals(seller_items)
        groups.append({
            "seller": seller,
            "items": seller_items,
            "total": total,
            "unpriced_count": unpriced,
            "urgent_count": sum(1 for item in seller_items if item.urgency == OrderItem.Urgency.HIGH),
            "message": message,
            "viber_forward_url": _viber_forward_url(message),
        })
    return groups


def _dashboard_context(request, *, edit_form=None, editing_id=None):
    """Context for the dashboard body, honouring the current seller filter.

    The filter value is read from POST as well as GET because the row actions
    carry it along (`hx-include`): completing an item while filtered to one
    seller must not silently bounce back to the full board.
    """
    groups = _open_items_by_seller()
    sellers = [group["seller"] for group in groups]

    # An unknown or malformed pk means no filter rather than an error: the only
    # way to get one is a stale link, usually because the seller's last open
    # item was completed, and showing everything is friendlier than a dead end.
    wanted = _int_or_none(request.POST.get("seller") or request.GET.get("seller"))
    selected_seller = next((seller for seller in sellers if seller.pk == wanted), None)
    if selected_seller:
        groups = [group for group in groups if group["seller"] == selected_seller]

    return {
        "groups": groups,
        "sellers": sellers,
        "selected_seller": selected_seller,
        "item_count": sum(len(group["items"]) for group in groups),
        "grand_total": sum(group["total"] for group in groups),
        "unpriced_count": sum(group["unpriced_count"] for group in groups),
        "edit_form": edit_form,
        "editing_id": editing_id,
    }


def _render_after_change(request, *, status=200, edit_form=None, editing_id=None, just_added=False):
    """Re-render whichever screen the action came from.

    Editing and deleting are reachable from both the employee panel and the
    admin dashboard, and each expects its own fragment back. htmx names the
    element it is about to swap in the HX-Target header, which says which
    screen is asking without threading a flag through every template.
    """
    if request.headers.get("HX-Target") == "dashboard-body":
        context = _dashboard_context(request, edit_form=edit_form, editing_id=editing_id)
        return render(request, DASHBOARD_BODY, context, status=status)

    context = _panel_context(edit_form=edit_form, editing_id=editing_id, just_added=just_added)
    return render(request, PANEL, context, status=status)


@shop_admin_required
def dashboard(request):
    """What still needs ordering, split into one block per seller.

    The shop orders by phoning or emailing one supplier at a time, so the
    seller is the unit of work here -- not the product, and not the requester.

    `?seller=<pk>` narrows the page to one of them. The filter's options come
    from the groups themselves rather than from Seller.objects, so it can only
    ever offer a seller that has something open -- picking one never lands on
    an empty page. `?editing=<pk>` opens one row for editing in place.
    """
    context = _dashboard_context(request, editing_id=_int_or_none(request.GET.get("editing")))

    # Filtering swaps just the body, so the same URL serves the fragment and
    # the full page. That keeps ?seller= shareable and the back button working.
    if request.headers.get("HX-Request"):
        return render(request, DASHBOARD_BODY, context)
    return render(request, "orders/dashboard.html", context)


@shop_admin_required
@require_POST
def complete_item(request, pk):
    """Mark one item as ordered.

    Completing is admin-only: employees flag what is running low, an admin
    decides it has actually been bought. The row leaves the dashboard, since
    the dashboard only ever shows what is still open.
    """
    item = get_object_or_404(OrderItem.objects.open().select_related("product"), pk=pk)
    OrderItem.objects.filter(pk=item.pk).update(
        completed_at=timezone.now(), completed_by=request.user
    )
    return _toast(_render_after_change(request), f"{item.product.name} marked as ordered")


SELLER_LIST = "orders/_seller_list.html"
SELLER_FORM = "orders/_seller_form.html"


def _active_filter(request):
    """The Active/Inactive tickboxes' state, wherever they rode in on.

    Shared by the sellers and products pages, which both filter this way. An
    unticked checkbox vanishes from the request entirely, same as any HTML
    form -- there is no value to read, ticked or not. So a plain hidden
    `filtered` marker rides alongside the tickboxes instead: its presence
    means "the filter UI submitted this request, read active/inactive as
    given, including neither being ticked". Its absence means the tickboxes
    have never been on the page for this request at all -- true only of the
    very first, plain page load -- and that is the one place the default
    (active only) applies.
    """
    source = request.POST if request.method == "POST" else request.GET
    if "filtered" not in source:
        return True, False
    return source.get("active") == "1", source.get("inactive") == "1"


def _seller_list_context(request):
    """Sellers, narrowed by the search box and the Active/Inactive tickboxes.

    Plain substring matching on name, phone and email rather than the fuzzy
    ranking products get: a shop has a handful of suppliers and knows their
    names, so predictable beats clever here.

    The term is read from POST as well as GET because the row actions carry it
    along (`hx-include`): deactivating a seller must not wipe the search the
    admin is working through.
    """
    query = (request.POST.get("q") or request.GET.get("q") or "").strip()
    show_active, show_inactive = _active_filter(request)
    sellers = Seller.objects.annotate(
        # Whether the row can be deleted outright. A seller with any products
        # is either in use or reachable through order history via them, and
        # PROTECT on Product.seller would refuse the delete anyway.
        product_count=Count("products"),
    )
    if query:
        sellers = sellers.filter(
            Q(name__icontains=query) | Q(phone__icontains=query) | Q(email__icontains=query)
        )
    if show_active and not show_inactive:
        sellers = sellers.filter(is_active=True)
    elif show_inactive and not show_active:
        sellers = sellers.filter(is_active=False)
    elif not show_active and not show_inactive:
        sellers = sellers.none()
    return {
        "sellers": sellers,
        "query": query,
        "show_active": show_active,
        "show_inactive": show_inactive,
    }


@shop_admin_required
def sellers(request):
    """The suppliers the shop buys from. Admin-only: employees never create
    these, they pick from the list when adding a product.
    """
    context = _seller_list_context(request)
    if request.headers.get("HX-Request"):
        return render(request, SELLER_LIST, context)
    return render(request, "orders/sellers.html", context)


@shop_admin_required
def new_seller(request):
    """Add a supplier, in the same dialog pattern the new-product form uses."""
    if request.method == "POST":
        form = SellerForm(request.POST)
        if form.is_valid():
            seller = form.save()
            return _saved_seller(request, f"{seller.name} added")
        return render(request, SELLER_FORM, {"form": form, "title": "New seller"}, status=422)

    return render(request, SELLER_FORM, {"form": SellerForm(), "title": "New seller"})


@shop_admin_required
def edit_seller(request, pk):
    seller = get_object_or_404(Seller, pk=pk)
    if request.method == "POST":
        form = SellerForm(request.POST, instance=seller)
        if form.is_valid():
            form.save()
            return _saved_seller(request, f"{seller.name} updated")
        return render(
            request, SELLER_FORM, {"form": form, "seller": seller, "title": "Edit seller"}, status=422
        )

    return render(
        request,
        SELLER_FORM,
        {"form": SellerForm(instance=seller), "seller": seller, "title": "Edit seller"},
    )


def _saved_seller(request, message):
    """Reply to a successful dialog save.

    The form posts from inside the dialog, so the fresh list has to be aimed at
    the page behind it, and the dialog told to shut. Both travel as headers
    rather than as markup the dialog would have to carry.
    """
    response = render(request, SELLER_LIST, _seller_list_context(request))
    response["HX-Retarget"] = "#seller-list"
    response["HX-Reswap"] = "outerHTML"
    return _trigger(response, toast={"message": message}, closeModal=True)


@shop_admin_required
@require_POST
def toggle_seller(request, pk):
    """Deactivate a supplier, or bring one back.

    Never a real delete: order history points at sellers through their
    products, so rule 3 keeps them as rows and hides them instead. An inactive
    seller drops out of product search and the new-product dropdown but stays
    visible here.
    """
    seller = get_object_or_404(Seller, pk=pk)
    seller.is_active = not seller.is_active
    seller.save(update_fields=["is_active"])

    verb = "reactivated" if seller.is_active else "deactivated"
    return _toast(
        render(request, SELLER_LIST, _seller_list_context(request)),
        f"{seller.name} {verb}",
    )


@shop_admin_required
@require_POST
def delete_seller(request, pk):
    """Remove a supplier outright -- only one with no products at all.

    Same reasoning as `delete_product`: a seller with nothing under it was
    never really used, so a typo or an abandoned entry can go for good.
    Anything with products is refused rather than deleted -- PROTECT on
    Product.seller would raise anyway, and those products (and any history
    behind them) still need a seller to point at.
    """
    seller = get_object_or_404(Seller, pk=pk)

    if seller.products.exists():
        return _toast(
            render(request, SELLER_LIST, _seller_list_context(request)),
            f"{seller.name} has products, so it cannot be deleted. Deactivate it instead.",
        )

    name = seller.name
    seller.delete()
    return _toast(
        render(request, SELLER_LIST, _seller_list_context(request)),
        f"{name} deleted",
    )


@shop_admin_required
@require_POST
def uncomplete_item(request, pk):
    """Put a completed item back on the list -- rule 4's undo.

    Refused when that product already has something open: the shop never lists
    the same product twice (rule 1), and if it is already back on the list then
    what the admin wanted is already true.

    The filters and page travel in the URL's query string rather than through
    hx-include, because the page number is not an input on the screen.
    """
    item = get_object_or_404(
        OrderItem.objects.completed().select_related("product"), pk=pk
    )

    if OrderItem.objects.open().filter(product=item.product).exists():
        return _toast(
            render(request, HISTORY_BODY, _history_context(request)),
            f"{item.product.name} is already on the list",
        )

    OrderItem.objects.filter(pk=item.pk).update(completed_at=None, completed_by=None)
    return _toast(
        render(request, HISTORY_BODY, _history_context(request)),
        f"{item.product.name} moved back to the list",
    )


@shop_admin_required
@require_POST
def complete_seller(request, pk):
    """Mark everything still open for one seller as ordered.

    The shop places one order per supplier, so clearing a whole seller in one
    tap is the common case rather than the exception. It is the same write as
    completing a single item applied to more rows -- no batch record, per the
    spec's rule 4.

    Completing the seller currently being filtered on leaves that seller with
    nothing open, so the filter quietly falls back to the whole board. That is
    the wanted behaviour: the supplier is done, here is what is left.
    """
    seller = get_object_or_404(Seller, pk=pk)
    count = (
        OrderItem.objects.open()
        .filter(product__seller=seller)
        .update(completed_at=timezone.now(), completed_by=request.user)
    )

    # Re-render before deciding on a toast, so the board always reflects the
    # database even when this changed nothing.
    response = _render_after_change(request)
    if not count:
        # A double tap, or another tab got there first. Showing the refreshed
        # board beats a 404, which htmx would swallow and leave stale markup.
        return response

    plural = "" if count == 1 else "s"
    return _toast(response, f"{count} item{plural} from {seller.name} marked as ordered")


@login_required
def product_search(request):
    query = request.GET.get("q", "").strip()
    products = search_products(query)
    return render(request, "orders/_product_results.html", {"products": products, "query": query})


@login_required
def new_product(request):
    """Add a product to the catalog, from the order list or the products page.

    From the order list this interrupts an order being typed, so success hands
    the new product straight back to the quick-add form and the interrupted
    flow carries on. From the products page there is no order in progress, so
    success just refreshes the list.

    `origin` says which, the same way `edit_product` uses it -- the form posts
    from inside the dialog and always targets #modal-body, which does not say
    what opened it.
    """
    origin = request.POST.get("origin") or request.GET.get("origin") or ""
    query = (request.POST.get("q") or request.GET.get("q") or "").strip()
    show_active, show_inactive = _active_filter(request)

    if request.method == "POST":
        form = ProductForm(request.POST)
        if form.is_valid():
            product = form.save(commit=False)
            product.created_by = request.user
            product.save()

            if origin == "products":
                return _saved_product(
                    request, product, origin, f"{product.name} added to the catalog"
                )
            # Back to the quick-add form, which only exists on the order list.
            return _toast(
                render(request, "orders/_product_created.html", {"product": product}),
                f"{product.name} added to the catalog",
            )
        status = 422
    else:
        # Whatever was typed into the search box is almost certainly the name.
        form = ProductForm(initial={"name": query})
        status = 200

    return render(
        request,
        PRODUCT_FORM,
        {
            "form": form,
            "origin": origin,
            "query": query,
            "show_active": show_active,
            "show_inactive": show_inactive,
            "title": "New product",
            "sellers": Seller.objects.filter(is_active=True),
            "units": Unit.objects.all(),
        },
        status=status,
    )


# How far back the history page can look. "" is all time, and is last so the
# narrowest window is the first thing offered.
HISTORY_PERIODS = (
    ("day", "Last 24 hours", 1),
    ("week", "Last 7 days", 7),
    ("month", "Last 30 days", 30),
    ("", "All time", None),
)
HISTORY_PAGE_SIZES = (5, 10, 20, 50)
DEFAULT_HISTORY_PAGE_SIZE = 20


def _history_context(request):
    """Completed orders, newest first, a page at a time.

    An "order" is a batch: completing one item or a whole seller writes the
    same `completed_at` to every row it touches, and those timestamps are
    microsecond-precise, so no two actions collide. That shared timestamp is
    what identifies a batch without the separate table rule 4 rules out.

    Paging is over the *distinct timestamps* rather than the rows, so a page is
    twenty orders rather than twenty items, and the database does the slicing.
    Only the current page's rows are then fetched -- the table is expected to
    outgrow anything worth loading whole.
    """
    period = request.GET.get("period", "")
    if period not in {slug for slug, _, _ in HISTORY_PERIODS}:
        period = ""
    days = next(days for slug, _, days in HISTORY_PERIODS if slug == period)

    page_size = _int_or_none(request.GET.get("size"))
    if page_size not in HISTORY_PAGE_SIZES:
        page_size = DEFAULT_HISTORY_PAGE_SIZE

    items = OrderItem.objects.completed().select_related(
        "product__seller", "product__unit", "requested_by", "completed_by"
    )
    if days is not None:
        items = items.filter(completed_at__gte=timezone.now() - timedelta(days=days))

    stamps = items.order_by("-completed_at").values_list("completed_at", flat=True).distinct()
    paginator = Paginator(stamps, page_size)
    # get_page swallows a junk or out-of-range page rather than raising, which
    # is what a stale bookmark deserves.
    page = paginator.get_page(request.GET.get("page"))

    rows = items.filter(completed_at__in=list(page.object_list)).order_by(
        "-completed_at", "product__name"
    )

    orders = []
    for completed_at, batch in groupby(rows, key=lambda item: item.completed_at):
        batch = list(batch)
        batch_total, batch_unpriced = _sum_line_totals(batch)
        orders.append({
            "completed_at": completed_at,
            "completed_by": batch[0].completed_by,
            # Every batch comes from one action, which only ever spans one
            # seller -- individually or as that seller's whole list.
            "seller": batch[0].product.seller,
            "items": batch,
            "total": batch_total,
            "unpriced_count": batch_unpriced,
        })

    return {
        "orders": orders,
        "page": page,
        "paginator": paginator,
        "period": period,
        "periods": HISTORY_PERIODS,
        "page_size": page_size,
        "page_sizes": HISTORY_PAGE_SIZES,
    }


@shop_admin_required
def history(request):
    """What has already been ordered. Admin-only, per the spec."""
    context = _history_context(request)
    if request.headers.get("HX-Request"):
        return render(request, HISTORY_BODY, context)
    return render(request, "orders/history.html", context)


def _product_list_context(request):
    """The catalog, narrowed by the search box and the Active/Inactive tickboxes.

    Plain substring matching over the shop's name, the seller's name for it and
    the supplier -- not `search.search_products`, whose fuzzy ranking exists to
    help someone half-remember a product while adding an order. Managing the
    catalog wants predictable matching instead.

    Read from POST as well as GET so saving an edit keeps the current search
    and filter.
    """
    query = (request.POST.get("q") or request.GET.get("q") or "").strip()
    show_active, show_inactive = _active_filter(request)
    products = Product.objects.select_related("seller", "unit").annotate(
        open_count=Count("order_items", filter=Q(order_items__completed_at__isnull=True)),
        # Whether the row can be deleted outright. A product that has ever been
        # ordered is part of history and only gets deactivated -- PROTECT on
        # OrderItem.product would refuse the delete anyway.
        order_count=Count("order_items"),
    )
    if query:
        products = products.filter(
            Q(name__icontains=query)
            | Q(order_name__icontains=query)
            | Q(seller__name__icontains=query)
        )
    if show_active and not show_inactive:
        products = products.filter(is_active=True)
    elif show_inactive and not show_active:
        products = products.filter(is_active=False)
    elif not show_active and not show_inactive:
        products = products.none()
    return {
        "products": products.order_by("name"),
        "query": query,
        "show_active": show_active,
        "show_inactive": show_inactive,
    }


@shop_admin_required
def products(request):
    """The catalog, for searching and correcting entries.

    Adding a product stays where it is useful -- mid-order, from the order
    list -- so this page only searches and edits.
    """
    context = _product_list_context(request)
    if request.headers.get("HX-Request"):
        return render(request, PRODUCT_LIST, context)
    return render(request, "orders/products.html", context)


@login_required
def edit_product(request, pk):
    """Correct a catalog entry -- every field, including `order_name`.

    Reachable from both the order list and the dashboard, so the reply has to
    know which screen to refresh. `origin` travels with the request rather than
    being sniffed from HX-Target, because the form posts from inside the dialog
    and so always targets #modal-body whichever page opened it.

    Editing a product does not touch open order items: their quantity is their
    own, and `unit_price_snapshot` deliberately keeps the price they were
    requested at. A new price applies to whatever is added next.
    """
    product = get_object_or_404(Product, pk=pk)
    origin = request.POST.get("origin") or request.GET.get("origin") or ""
    show_active, show_inactive = _active_filter(request)

    if request.method == "POST":
        form = ProductForm(request.POST, instance=product)
        if form.is_valid():
            form.save()
            return _saved_product(request, product, origin)
        status = 422
    else:
        form = ProductForm(instance=product)
        status = 200

    return render(
        request,
        PRODUCT_FORM,
        {
            "form": form,
            "product": product,
            "origin": origin,
            # Carried through the dialog so saving from the products page keeps
            # the search and Active/Inactive filter rather than resetting them.
            "query": (request.POST.get("q") or request.GET.get("q") or "").strip(),
            "show_active": show_active,
            "show_inactive": show_inactive,
            "title": "Edit product",
            "sellers": Seller.objects.filter(is_active=True),
            "units": Unit.objects.all(),
        },
        status=status,
    )


@shop_admin_required
@require_POST
def toggle_product(request, pk):
    """Take a product out of circulation, or bring it back.

    Deactivating is the answer for anything that has ever been ordered: rule 3
    keeps those rows because history points at them. An inactive product drops
    out of the quick-add search and cannot be added to the list, but stays
    visible here and in the orders it already appears in.
    """
    product = get_object_or_404(Product, pk=pk)
    product.is_active = not product.is_active
    product.save(update_fields=["is_active"])

    verb = "reactivated" if product.is_active else "deactivated"
    return _toast(
        render(request, PRODUCT_LIST, _product_list_context(request)),
        f"{product.name} {verb}",
    )


@shop_admin_required
@require_POST
def delete_product(request, pk):
    """Remove a product outright -- only one that has never been ordered.

    That case is real and worth supporting: a typo, a duplicate, something
    added to the catalog by mistake. Deactivating those would leave clutter in
    the list forever for no reason.

    Anything with order items is refused rather than deleted. It is history,
    rule 3 says keep it, and PROTECT on OrderItem.product would raise anyway --
    catching it here means an explanation instead of a 500.
    """
    product = get_object_or_404(Product, pk=pk)

    if product.order_items.exists():
        return _toast(
            render(request, PRODUCT_LIST, _product_list_context(request)),
            f"{product.name} has been ordered before, so it cannot be deleted. "
            f"Deactivate it instead.",
        )

    name = product.name
    product.delete()
    return _toast(
        render(request, PRODUCT_LIST, _product_list_context(request)),
        f"{name} deleted",
    )


@shop_admin_required
@require_POST
def delete_all_products(request):
    """Clear the whole catalog in one action, whatever the search box holds.

    Same split as the per-row buttons, applied to every product: never
    ordered gets deleted outright; anything with order history is
    deactivated instead, since PROTECT would refuse the delete and rule 3
    says keep it for history.
    """
    never_ordered_ids = list(
        Product.objects.annotate(order_count=Count("order_items"))
        .filter(order_count=0)
        .values_list("pk", flat=True)
    )
    deleted_count = len(never_ordered_ids)
    Product.objects.filter(pk__in=never_ordered_ids).delete()

    deactivated_count = Product.objects.filter(is_active=True).update(is_active=False)

    parts = []
    if deleted_count:
        parts.append(f"{deleted_count} deleted")
    if deactivated_count:
        parts.append(f"{deactivated_count} deactivated")
    message = ", ".join(parts) if parts else "No products to remove"

    return _toast(
        render(request, PRODUCT_LIST, _product_list_context(request)),
        message,
    )


@shop_admin_required
def download_product_template(request):
    """The starting point for a bulk import -- headers, one example row, and
    the exact list of units a sheet has to match.
    """
    content = workbook_to_bytes(build_template_workbook())
    response = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="products-template.xlsx"'
    return response


@shop_admin_required
def import_products_view(request):
    """Bulk-add products from an admin-supplied sheet.

    Validated in full before anything is written -- see product_import.py.
    A sheet with any bad row is rejected whole, with every problem listed at
    once, rather than half-imported with no clean way to tell what happened.
    """
    if request.method == "POST":
        upload = request.FILES.get("file")
        if upload is None:
            return render(
                request, PRODUCT_IMPORT_FORM,
                {"file_error": "Choose a file to import."}, status=422,
            )

        try:
            rows, errors = parse_workbook(upload)
        except InvalidWorkbook:
            return render(
                request, PRODUCT_IMPORT_FORM,
                {"file_error": "That doesn't look like a valid .xlsx file."}, status=422,
            )

        if errors:
            return render(
                request, PRODUCT_IMPORT_FORM, {"row_errors": errors}, status=422
            )

        if not rows:
            return render(
                request, PRODUCT_IMPORT_FORM,
                {"file_error": "That sheet has no product rows to import."}, status=422,
            )

        result = import_products(rows, created_by=request.user)

        parts = [f"{result.created_count} added"]
        if result.sellers_created_count:
            parts.append(f"{result.sellers_created_count} seller{'s' if result.sellers_created_count != 1 else ''} created")
        if result.skipped_count:
            parts.append(f"{result.skipped_count} already on the catalog, skipped")

        response = render(request, PRODUCT_LIST, _product_list_context(request))
        response["HX-Retarget"] = "#product-list"
        response["HX-Reswap"] = "outerHTML"
        return _trigger(response, toast={"message": ", ".join(parts)}, closeModal=True)

    return render(request, PRODUCT_IMPORT_FORM, {})


def _saved_product(request, product, origin, message=None):
    """Shut the dialog and refresh whichever list is behind it."""
    if origin == "dashboard":
        response = render(request, DASHBOARD_BODY, _dashboard_context(request))
        response["HX-Retarget"] = "#dashboard-body"
    elif origin == "products":
        response = render(request, PRODUCT_LIST, _product_list_context(request))
        response["HX-Retarget"] = "#product-list"
    else:
        response = render(request, PANEL, _panel_context())
        response["HX-Retarget"] = "#panel"

    response["HX-Reswap"] = "outerHTML"
    return _trigger(
        response,
        toast={"message": message or f"{product.name} updated"},
        closeModal=True,
    )


@shop_admin_required
def units(request):
    """The measures products can be ordered in. A products subpage, not a
    top-level one -- a unit belongs to no single product, but nothing outside
    the catalog cares about it either.
    """
    return render(request, "orders/units.html", {"units": Unit.objects.all()})


@shop_admin_required
def new_unit(request):
    """Add a unit, in the same dialog pattern the new-seller form uses."""
    if request.method == "POST":
        form = UnitForm(request.POST)
        if form.is_valid():
            unit = form.save()
            return _saved_unit(request, f"{unit.name} added")
        return render(request, UNIT_FORM, {"form": form, "title": "New unit"}, status=422)

    return render(request, UNIT_FORM, {"form": UnitForm(), "title": "New unit"})


@shop_admin_required
def edit_unit(request, pk):
    unit = get_object_or_404(Unit, pk=pk)
    if request.method == "POST":
        form = UnitForm(request.POST, instance=unit)
        if form.is_valid():
            form.save()
            return _saved_unit(request, f"{unit.name} updated")
        return render(
            request, UNIT_FORM, {"form": form, "unit": unit, "title": "Edit unit"}, status=422
        )

    return render(
        request, UNIT_FORM, {"form": UnitForm(instance=unit), "unit": unit, "title": "Edit unit"}
    )


def _saved_unit(request, message):
    """Reply to a successful dialog save, same shape as `_saved_seller`."""
    response = render(request, UNIT_LIST, {"units": Unit.objects.all()})
    response["HX-Retarget"] = "#unit-list"
    response["HX-Reswap"] = "outerHTML"
    return _trigger(response, toast={"message": message}, closeModal=True)
