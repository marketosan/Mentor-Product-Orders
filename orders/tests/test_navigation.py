"""The header nav, and the sellers page it points at."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from orders.models import Product, Seller

User = get_user_model()


class NavigationTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="boss", email="boss@example.com", password="pw", role=User.Role.ADMIN
        )
        cls.maria = User.objects.create_user(
            username="maria", email="maria@example.com", password="pw"
        )


class NavigationTests(NavigationTestCase):
    def test_an_admin_gets_all_three_pages(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("order_list"))

        for name in ("order_list", "dashboard", "sellers"):
            self.assertContains(response, f'href="{reverse(name)}"')

    def test_an_employee_gets_only_home(self):
        """Dashboard and Sellers are admin-only, so an employee's nav is one
        link -- correct, if sparse.
        """
        self.client.force_login(self.maria)

        response = self.client.get(reverse("order_list"))

        self.assertContains(response, f'href="{reverse("order_list")}"')
        self.assertNotContains(response, f'href="{reverse("dashboard")}"')
        self.assertNotContains(response, f'href="{reverse("sellers")}"')

    def test_the_current_page_is_marked(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("sellers"))

        self.assertContains(response, 'aria-current="page"')

    def test_only_one_link_is_marked_current(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.content.decode().count('aria-current="page"'), 1)

    def test_the_nav_is_absent_before_logging_in(self):
        response = self.client.get(reverse("login"))

        self.assertNotContains(response, 'aria-label="Main"')

    def test_the_links_appear_in_a_fixed_order(self):
        self.client.force_login(self.admin)

        markup = self.client.get(reverse("order_list")).content.decode()

        # Labels, not hrefs: href="/" would match the wordmark above the nav.
        self.assertLess(markup.index("Home"), markup.index("Dashboard"))
        self.assertLess(markup.index("Dashboard"), markup.index("Sellers"))


class SellersPageAccessTests(NavigationTestCase):
    def test_an_admin_can_open_it(self):
        self.client.force_login(self.admin)

        self.assertEqual(self.client.get(reverse("sellers")).status_code, 200)

    def test_an_employee_is_refused(self):
        """Only admins create sellers, so the page is admin-only outright."""
        self.client.force_login(self.maria)

        self.assertEqual(self.client.get(reverse("sellers")).status_code, 403)

    def test_a_signed_out_visitor_is_sent_to_login(self):
        response = self.client.get(reverse("sellers"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)


class SellersPageTests(NavigationTestCase):
    def setUp(self):
        self.client.force_login(self.admin)

    def test_it_lists_sellers_with_their_product_counts(self):
        dairy = Seller.objects.create(name="Green Valley Dairy")
        Product.objects.create(name="Whole milk", seller=dairy, unit="l", unit_price="1.15")
        Product.objects.create(name="Oat milk", seller=dairy, unit="l", unit_price="2.40")

        response = self.client.get(reverse("sellers"))

        self.assertContains(response, "Green Valley Dairy")
        self.assertContains(response, "2 products")

    def test_a_seller_with_one_product_is_not_pluralised(self):
        metro = Seller.objects.create(name="Metro Wholesale")
        Product.objects.create(name="Napkins", seller=metro, unit="box", unit_price="8.75")

        response = self.client.get(reverse("sellers"))

        self.assertContains(response, "1 product")
        self.assertNotContains(response, "1 products")

    def test_inactive_sellers_are_shown_and_labelled(self):
        """They are deactivated rather than deleted because history points at
        them, so this page has to show them with the Inactive tickbox on,
        even though the active-only default and product search both hide
        them.
        """
        Seller.objects.create(name="Old Supplier", is_active=False)

        response = self.client.get(
            reverse("sellers"), {"filtered": "1", "active": "1", "inactive": "1"}
        )

        self.assertContains(response, "Old Supplier")
        self.assertContains(response, "inactive")

    def test_the_phone_opens_viber_here_too(self):
        Seller.objects.create(name="Green Valley Dairy", phone="+30 210 555 0198")

        response = self.client.get(reverse("sellers"))

        self.assertContains(response, "viber://chat?number=%2B302105550198")

    def test_a_seller_without_contact_details_says_so(self):
        Seller.objects.create(name="Metro Wholesale")

        self.assertContains(self.client.get(reverse("sellers")), "No contact details")

    def test_it_offers_the_add_and_search_controls(self):
        response = self.client.get(reverse("sellers"))

        self.assertContains(response, reverse("new_seller"))
        self.assertContains(response, 'id="seller-search"')

    def test_an_empty_list_says_so(self):
        response = self.client.get(reverse("sellers"))

        self.assertContains(response, "No sellers yet")

    def test_no_template_syntax_leaks_into_the_page(self):
        Seller.objects.create(name="Green Valley Dairy", phone="+30 210 555 0198")

        markup = self.client.get(reverse("sellers")).content.decode()

        for marker in ("{#", "#}", "{%", "%}"):
            self.assertNotIn(marker, markup)
