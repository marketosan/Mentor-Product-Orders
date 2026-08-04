"""Role gating for the shop's own admin pages."""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def shop_admin_required(view_func):
    """Restrict a view to users whose shop role is admin.

    A signed-out visitor is sent to the login page; a signed-in employee gets a
    403. Bouncing an employee to a login form would be a lie -- they are already
    logged in, and no amount of logging in again would grant access.

    This is the shop's `role`, not Django's `is_staff`: staff opens /admin, this
    opens the dashboard, and the two are deliberately separate.
    """

    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_shop_admin:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapper
