"""Context shared by every page."""

# (url name, label, admin only). Order is the order they appear in the header.
# Kept here rather than in the template so the nav has one definition and the
# markup stays a loop.
NAV_LINKS = (
    ("order_list", "Home", False),
    ("dashboard", "Dashboard", True),
    ("history", "History", True),
    ("sellers", "Sellers", True),
    ("products", "Products", True),
    ("users", "Users", True),
)


def navigation(request):
    return {"nav_links": NAV_LINKS}
