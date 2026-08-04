"""User administration. Admin-only: there is no self-registration."""

import json

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from .decorators import shop_admin_required
from .forms import EditUserForm, NewUserForm
from .models import User

USER_LIST = "accounts/_user_list.html"
USER_FORM = "accounts/_user_form.html"


def _trigger(response, **events):
    """Fire client-side events off the response, merging with any already set."""
    fired = json.loads(response.headers.get("HX-Trigger", "{}"))
    fired.update(events)
    response["HX-Trigger"] = json.dumps(fired)
    return response


def _toast(response, message):
    return _trigger(response, toast={"message": message})


def _user_list_context(request):
    """Accounts, narrowed by the search box.

    The term is read from POST as well as GET because the row actions carry it
    along (`hx-include`), so acting on a row does not wipe the search.
    """
    query = (request.POST.get("q") or request.GET.get("q") or "").strip()
    users = User.objects.annotate(request_count=Count("order_items_requested"))
    if query:
        users = users.filter(Q(username__icontains=query) | Q(email__icontains=query))
    return {"users": users.order_by("username"), "query": query}


@shop_admin_required
def users(request):
    context = _user_list_context(request)
    if request.headers.get("HX-Request"):
        return render(request, USER_LIST, context)
    return render(request, "accounts/users.html", context)


@shop_admin_required
def new_user(request):
    if request.method == "POST":
        form = NewUserForm(request.POST, editor=request.user)
        if form.is_valid():
            created = form.save()
            return _saved_user(request, f"{created.username} added")
        return render(request, USER_FORM, {"form": form, "title": "New user"}, status=422)

    return render(request, USER_FORM, {"form": NewUserForm(), "title": "New user"})


@shop_admin_required
def edit_user(request, pk):
    account = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        form = EditUserForm(request.POST, instance=account, editor=request.user)
        if form.is_valid():
            form.save()
            return _saved_user(request, f"{account.username} updated")
        return render(
            request, USER_FORM,
            {"form": form, "account": account, "title": "Edit user"}, status=422,
        )

    return render(
        request, USER_FORM,
        {"form": EditUserForm(instance=account, editor=request.user),
         "account": account, "title": "Edit user"},
    )


def _saved_user(request, message):
    """The form posts from inside the dialog, so the fresh list is aimed at the
    page behind it and the dialog is told to shut, both as headers.
    """
    response = render(request, USER_LIST, _user_list_context(request))
    response["HX-Retarget"] = "#user-list"
    response["HX-Reswap"] = "outerHTML"
    return _trigger(response, toast={"message": message}, closeModal=True)


@shop_admin_required
@require_POST
def toggle_user(request, pk):
    """Switch an account on or off.

    Never a real delete: order items point at whoever requested them with
    PROTECT, so removing anyone who has ever flagged a product is impossible
    anyway. Deactivating also blocks login, which is what "remove this person"
    actually means for a shop.
    """
    account = get_object_or_404(User, pk=pk)

    refusal = None
    if account.pk == request.user.pk:
        # This alone keeps at least one admin active: whoever is clicking is an
        # active admin, so any *other* account can go without emptying the role.
        refusal = "You cannot deactivate your own account."
    elif account.is_active and account.is_last_admin():
        # Unreachable while only shop admins can reach this view -- kept as a
        # backstop in case that ever widens (a superuser tool, a management
        # command), since the cost is two lines and the failure is a lockout.
        refusal = f"{account.username} is the only admin left. Promote someone else first."

    if refusal:
        # Nothing changes, but the list still re-renders so the screen matches
        # the database, and the toast explains why the click did nothing.
        return _toast(render(request, USER_LIST, _user_list_context(request)), refusal)

    account.is_active = not account.is_active
    account.save(update_fields=["is_active"])

    verb = "reactivated" if account.is_active else "deactivated"
    return _toast(
        render(request, USER_LIST, _user_list_context(request)),
        f"{account.username} {verb}",
    )
