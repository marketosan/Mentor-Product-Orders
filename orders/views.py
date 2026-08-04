import json
from itertools import groupby
from urllib.parse import quote

from django.contrib.auth.decorators import login_required
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import shop_admin_required

from .forms import AddOrderItemForm, EditOrderItemForm, ProductForm, SellerForm
from .models import OrderItem, Product, Seller
from .search import search_products

PANEL = "orders/_panel.html"
DASHBOARD_BODY = "orders/_dashboard_body.html"
PRODUCT_FORM = "orders/_product_form.html"
PRODUCT_LIST = "orders/_product_list.html"

# Opens the order message. Greek, because it is read by the supplier, not
# by anyone using the app.
ORDER_GREETING = "Θα ήθελα να παραγγείλω τα παρακάτω:"


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
        "items": OrderItem.objects.open().select_related("product__seller", "requested_by"),
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
        .select_related("product", "requested_by")
        .first()
    )
    if existing:
        # Warn rather than silently duplicating or auto-merging quantities.
        # This reply goes to the modal, not to the panel the form aims at.
        response = render(
            request,
            "orders/_duplicate_warning.html",
            {"existing": existing, "attempted_quantity": form.cleaned_data["quantity"]},
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


def _order_message(items):
    """The order written out, ready to send to the supplier.

    One numbered line per item, `<n>. <name>: <quantity> <unit>`. The name is
    the seller's own where `order_name` is set -- that is the whole reason the
    field exists -- and the shop's name where it is not, with nothing else
    tacked on either way.

    The seller is not named in the message: it is sent to them, in their own
    chat. Prices are left out too -- this says what the shop wants, not what it
    expects to pay.
    """
    lines = [ORDER_GREETING, ""]
    for position, item in enumerate(items, start=1):
        name = item.product.order_name or item.product.name
        urgent = " (urgent)" if item.urgency == OrderItem.Urgency.HIGH else ""
        lines.append(
            f"{position}. {name}: {_format_quantity(item.quantity)} {item.product.unit}{urgent}"
        )
    return "\n".join(lines)


def _viber_forward_url(message):
    """Open Viber with a message ready to send, asking which chat to send it to.

    Used only for sellers with no phone number. Where there is one, the Send
    order button copies the text and opens that seller's chat instead, since
    `viber://chat?number=` takes a recipient but silently drops any text and
    `viber://forward?text=` takes text but no recipient.
    """
    return f"viber://forward?text={quote(message, safe='')}"


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
        .select_related("product__seller", "requested_by")
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
        groups.append({
            "seller": seller,
            "items": seller_items,
            "total": sum(item.line_total for item in seller_items),
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


def _seller_list_context(request):
    """Sellers, narrowed by the search box.

    Plain substring matching on name, phone and email rather than the fuzzy
    ranking products get: a shop has a handful of suppliers and knows their
    names, so predictable beats clever here.

    The term is read from POST as well as GET because the row actions carry it
    along (`hx-include`): deactivating a seller must not wipe the search the
    admin is working through.
    """
    query = (request.POST.get("q") or request.GET.get("q") or "").strip()
    sellers = Seller.objects.annotate(product_count=Count("products"))
    if query:
        sellers = sellers.filter(
            Q(name__icontains=query) | Q(phone__icontains=query) | Q(email__icontains=query)
        )
    return {"sellers": sellers, "query": query}


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
    """Add a missing product without losing the order being typed.

    Rendered into a dialog. On success the reply is a script that closes the
    dialog and drops the new product straight into the quick-add form, so the
    interrupted flow picks up where it left off.
    """
    if request.method == "POST":
        form = ProductForm(request.POST)
        if form.is_valid():
            product = form.save(commit=False)
            product.created_by = request.user
            product.save()
            return _toast(
                render(request, "orders/_product_created.html", {"product": product}),
                f"{product.name} added to the catalog",
            )
        status = 422
    else:
        # Whatever was typed into the search box is almost certainly the name.
        form = ProductForm(initial={"name": request.GET.get("q", "").strip()})
        status = 200

    return render(
        request,
        PRODUCT_FORM,
        {"form": form, "title": "New product", "sellers": Seller.objects.filter(is_active=True)},
        status=status,
    )


def _product_list_context(request):
    """The catalog, narrowed by the search box.

    Plain substring matching over the shop's name, the seller's name for it and
    the supplier -- not `search.search_products`, whose fuzzy ranking exists to
    help someone half-remember a product while adding an order. Managing the
    catalog wants predictable matching instead.

    Read from POST as well as GET so saving an edit keeps the current search.
    """
    query = (request.POST.get("q") or request.GET.get("q") or "").strip()
    products = Product.objects.select_related("seller").annotate(
        open_count=Count("order_items", filter=Q(order_items__completed_at__isnull=True))
    )
    if query:
        products = products.filter(
            Q(name__icontains=query)
            | Q(order_name__icontains=query)
            | Q(seller__name__icontains=query)
        )
    return {"products": products.order_by("name"), "query": query}


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
            # the search rather than resetting to the whole catalog.
            "query": (request.POST.get("q") or request.GET.get("q") or "").strip(),
            "title": "Edit product",
            "sellers": Seller.objects.filter(is_active=True),
        },
        status=status,
    )


def _saved_product(request, product, origin):
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
    return _trigger(response, toast={"message": f"{product.name} updated"}, closeModal=True)
