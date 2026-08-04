"""Pieces that everything else leans on, tested directly rather than through a
page: the nav table, quantity formatting, and the demo-data command.
"""

from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from orders.context_processors import NAV_LINKS
from orders.models import OrderItem, Product, Seller
from orders.views import _format_quantity

User = get_user_model()


class NavLinkTests(TestCase):
    """A typo in NAV_LINKS raises NoReverseMatch while rendering base.html,
    which breaks *every* page rather than one -- worth catching here.
    """

    def test_every_link_resolves(self):
        for name, _label, _admin_only in NAV_LINKS:
            with self.subTest(link=name):
                try:
                    reverse(name)
                except NoReverseMatch:
                    self.fail(f"NAV_LINKS points at {name!r}, which is not a url name")

    def test_every_link_has_a_label(self):
        for name, label, _admin_only in NAV_LINKS:
            with self.subTest(link=name):
                self.assertTrue(label.strip(), f"{name} has no label")

    def test_the_admin_flag_is_a_boolean(self):
        """A truthy string here would quietly open an admin page to everyone."""
        for name, _label, admin_only in NAV_LINKS:
            with self.subTest(link=name):
                self.assertIsInstance(admin_only, bool)

    def test_home_is_the_only_link_everyone_gets(self):
        public = [name for name, _, admin_only in NAV_LINKS if not admin_only]

        self.assertEqual(public, ["order_list"])


class FormatQuantityTests(TestCase):
    """The column is DecimalField(max_digits=10, decimal_places=3), so every
    quantity arrives with three decimal places whether or not it needs them.
    """

    def test_whole_numbers_lose_the_decimals(self):
        self.assertEqual(_format_quantity(Decimal("24.000")), "24")

    def test_a_half_keeps_one_place(self):
        self.assertEqual(_format_quantity(Decimal("1.500")), "1.5")

    def test_a_thousandth_keeps_all_three(self):
        self.assertEqual(_format_quantity(Decimal("0.001")), "0.001")

    def test_zero_stays_zero_rather_than_emptying(self):
        """Stripping "0.000" naively leaves an empty string."""
        self.assertEqual(_format_quantity(Decimal("0.000")), "0")

    def test_a_large_quantity_is_not_rendered_in_scientific_notation(self):
        """Decimal.normalize() would turn this into 1E+3."""
        self.assertEqual(_format_quantity(Decimal("1000.000")), "1000")


class SeedDemoTests(TestCase):
    """README tells the user this is safe to re-run, so that had better hold."""

    def seed(self):
        call_command("seed_demo", stdout=StringIO())

    def test_it_creates_a_working_shop(self):
        self.seed()

        self.assertTrue(Seller.objects.exists())
        self.assertTrue(Product.objects.exists())
        self.assertTrue(OrderItem.objects.open().exists())

    def test_it_creates_the_two_documented_logins(self):
        self.seed()

        admin = User.objects.get(username="admin")
        maria = User.objects.get(username="maria")

        self.assertTrue(admin.is_shop_admin)
        self.assertTrue(admin.check_password("admin"))
        self.assertFalse(maria.is_shop_admin)
        self.assertTrue(maria.check_password("mentor123"))

    def test_running_it_twice_duplicates_nothing(self):
        self.seed()
        counts = (Seller.objects.count(), Product.objects.count(), OrderItem.objects.count())

        self.seed()

        self.assertEqual(
            (Seller.objects.count(), Product.objects.count(), OrderItem.objects.count()),
            counts,
        )

    def test_re_running_does_not_reset_a_changed_password(self):
        """get_or_create only sets the password on creation; a second run must
        not hand the shop's admin account back to the default.
        """
        self.seed()
        admin = User.objects.get(username="admin")
        admin.set_password("something-the-shop-chose")
        admin.save()

        self.seed()

        admin.refresh_from_db()
        self.assertTrue(admin.check_password("something-the-shop-chose"))

    def test_the_seeded_items_are_priced_from_their_products(self):
        self.seed()

        for item in OrderItem.objects.select_related("product"):
            with self.subTest(item=item.product.name):
                self.assertEqual(item.unit_price_snapshot, item.product.unit_price)
