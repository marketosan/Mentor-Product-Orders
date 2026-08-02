from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from .forms import AddOrderItemForm, EditOrderItemForm, ProductForm
from .models import OrderItem, Seller
from .search import search_products

PANEL = "orders/_panel.html"


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
    if form.is_valid():
        form.save(requested_by=request.user)
        return render(request, PANEL, _panel_context(just_added=True))
    return render(request, PANEL, _panel_context(add_form=form), status=422)


@login_required
@require_POST
def edit_item(request, pk):
    item = get_object_or_404(OrderItem.objects.open(), pk=pk)
    form = EditOrderItemForm(request.POST, instance=item)
    if form.is_valid():
        form.save()
        return render(request, PANEL, _panel_context())
    return render(request, PANEL, _panel_context(edit_form=form, editing_id=pk), status=422)


@login_required
@require_POST
def delete_item(request, pk):
    """Open items can be deleted outright -- nothing has been bought yet, so
    there is no history to preserve.
    """
    item = get_object_or_404(OrderItem.objects.open(), pk=pk)
    item.delete()
    return render(request, PANEL, _panel_context())


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
            return render(request, "orders/_product_created.html", {"product": product})
        status = 422
    else:
        # Whatever was typed into the search box is almost certainly the name.
        form = ProductForm(initial={"name": request.GET.get("q", "").strip()})
        status = 200

    return render(
        request,
        "orders/_product_form.html",
        {"form": form, "sellers": Seller.objects.filter(is_active=True)},
        status=status,
    )
