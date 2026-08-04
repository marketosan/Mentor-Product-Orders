"""The HTMX flows end to end.

These cover the contract between the views and the front end -- status codes,
response headers and which fragment comes back -- because that contract is
invisible to the models and forms and is what actually breaks in the browser.
"""

import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from orders.models import OrderItem, Product, Seller

User = get_user_model()


class OrdersTestCase(TestCase):
    """Shared fixture: one shop with two sellers and a few products."""

    @classmethod
    def setUpTestData(cls):
        cls.maria = User.objects.create_user(
            username="maria", email="maria@example.com", password="pw"
        )
        cls.dairy = Seller.objects.create(name="Green Valley Dairy")
        cls.metro = Seller.objects.create(name="Metro Wholesale")
        cls.milk = Product.objects.create(
            name="Whole milk", seller=cls.dairy, unit="l", unit_price="1.15"
        )
        cls.oat = Product.objects.create(
            name="Oat milk", seller=cls.dairy, unit="l", unit_price="2.40"
        )
        cls.napkins = Product.objects.create(
            name="Napkins", seller=cls.metro, unit="box", unit_price="8.75"
        )

    def setUp(self):
        self.client.force_login(self.maria)

    def open_item(self, product=None, quantity="24", urgency=OrderItem.Urgency.LOW):
        product = product or self.milk
        return OrderItem.objects.create(
            product=product, quantity=quantity, urgency=urgency,
            unit_price_snapshot=product.unit_price, requested_by=self.maria,
        )

    def assertToast(self, response, fragment):
        """Confirmations ride on the HX-Trigger header, not the swapped markup."""
        self.assertIn("HX-Trigger", response.headers)
        message = json.loads(response.headers["HX-Trigger"])["toast"]["message"]
        self.assertIn(fragment, message)


class AuthenticationTests(TestCase):
    def test_every_page_requires_a_login(self):
        for name, args in [
            ("order_list", []), ("panel", []), ("product_search", []), ("new_product", []),
        ]:
            with self.subTest(view=name):
                response = self.client.get(reverse(name, args=args))

                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response.url)


class OrderListTests(OrdersTestCase):
    def test_it_shows_everyones_open_items_not_just_your_own(self):
        """One shared list is the point -- the shop needs a single view of what
        still needs ordering.
        """
        someone_else = User.objects.create_user(
            username="nikos", email="nikos@example.com", password="pw"
        )
        OrderItem.objects.create(
            product=self.napkins, quantity="2", unit_price_snapshot="8.75",
            requested_by=someone_else,
        )

        response = self.client.get(reverse("order_list"))

        self.assertContains(response, "Napkins")
        self.assertContains(response, "nikos")

    def test_completed_items_drop_off_the_list(self):
        self.open_item()
        self.open_item(product=self.napkins)
        OrderItem.objects.filter(product=self.napkins).update(completed_at=timezone.now())

        response = self.client.get(reverse("order_list"))

        self.assertContains(response, "Whole milk")
        self.assertNotContains(response, "Napkins")

    def test_an_empty_list_says_so(self):
        response = self.client.get(reverse("order_list"))

        self.assertContains(response, "Nothing to order")

    def test_each_row_shows_the_price_per_unit(self):
        self.open_item()

        response = self.client.get(reverse("order_list"))

        self.assertContains(response, "&euro;1.15/l")

    def test_the_unit_price_shown_is_the_frozen_one(self):
        """The line total is quantity times this number, so showing the live
        catalog price instead would make the row's arithmetic look wrong.
        """
        self.open_item(quantity="24")
        Product.objects.filter(pk=self.milk.pk).update(unit_price=Decimal("99.00"))

        response = self.client.get(reverse("order_list"))

        self.assertContains(response, "&euro;1.15/l")
        self.assertContains(response, "&euro;27.60")
        self.assertNotContains(response, "&euro;99.00")

    def test_it_pulls_in_the_stylesheet_and_scripts(self):
        """The CSS and JS live in static/ rather than inline, so a page that
        forgets to reference them looks fine to the server and is dead in the
        browser -- no highlight, no toasts, no dropdown.
        """
        response = self.client.get(reverse("order_list"))

        self.assertContains(response, "css/app.css")
        self.assertContains(response, "js/app.js")
        self.assertContains(response, "js/product-search.js")

    def test_the_panel_can_open_one_row_for_editing(self):
        item = self.open_item()

        response = self.client.get(reverse("panel"), {"editing": item.pk})

        self.assertEqual(response.context["editing_id"], item.pk)
        self.assertContains(response, "Save")

    def test_a_junk_editing_id_is_ignored_rather_than_crashing(self):
        self.open_item()

        response = self.client.get(reverse("panel"), {"editing": "nonsense"})

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["editing_id"])


class AddItemTests(OrdersTestCase):
    def test_it_adds_an_item_and_returns_the_whole_panel(self):
        response = self.client.post(
            reverse("add_item"), {"product": self.milk.pk, "quantity": "24"}
        )

        self.assertEqual(response.status_code, 200)
        item = OrderItem.objects.get()
        self.assertEqual(item.quantity, Decimal("24"))
        self.assertEqual(item.requested_by, self.maria)
        self.assertToast(response, "Whole milk added")

    def test_it_puts_the_cursor_back_for_the_next_item(self):
        response = self.client.post(
            reverse("add_item"), {"product": self.milk.pk, "quantity": "24"}
        )

        self.assertTrue(response.context["just_added"])

    def test_an_invalid_quantity_answers_422_with_the_error(self):
        """422 rather than 400 because base.html opts that one status back
        into swapping; anything else htmx would silently drop.
        """
        response = self.client.post(
            reverse("add_item"), {"product": self.milk.pk, "quantity": "0"}
        )

        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "more than zero", status_code=422)
        self.assertFalse(OrderItem.objects.exists())

    def test_a_product_already_on_the_list_warns_instead_of_duplicating(self):
        existing = self.open_item(quantity="24")

        response = self.client.post(
            reverse("add_item"), {"product": self.milk.pk, "quantity": "10"}
        )

        self.assertEqual(OrderItem.objects.count(), 1)
        self.assertContains(response, "Already on the list")
        # The post aimed at #panel, so the reply has to redirect itself.
        self.assertEqual(response.headers["HX-Retarget"], "#modal-body")
        self.assertEqual(response.headers["HX-Reswap"], "innerHTML")
        self.assertEqual(response.context["existing"], existing)
        self.assertEqual(response.context["attempted_quantity"], Decimal("10"))

    def test_the_warning_offers_only_to_update_the_quantity(self):
        """Agreed deviation from the spec: there is no "add anyway"."""
        self.open_item()

        response = self.client.post(
            reverse("add_item"), {"product": self.milk.pk, "quantity": "10"}
        )

        self.assertContains(response, "Update quantity")
        self.assertNotContains(response, "Add anyway")

    def test_a_completed_item_does_not_block_reordering(self):
        """Ordering the same thing next week is normal; only open items clash."""
        self.open_item().completed_at = None
        OrderItem.objects.update(completed_at=timezone.now())

        response = self.client.post(
            reverse("add_item"), {"product": self.milk.pk, "quantity": "10"}
        )

        self.assertEqual(OrderItem.objects.open().count(), 1)
        self.assertNotIn("HX-Retarget", response.headers)

    def test_a_different_product_is_not_a_duplicate(self):
        self.open_item(product=self.milk)

        self.client.post(reverse("add_item"), {"product": self.oat.pk, "quantity": "6"})

        self.assertEqual(OrderItem.objects.open().count(), 2)

    def test_it_refuses_a_get(self):
        response = self.client.get(reverse("add_item"))

        self.assertEqual(response.status_code, 405)


class EditItemTests(OrdersTestCase):
    def test_it_updates_quantity_and_urgency(self):
        item = self.open_item()

        response = self.client.post(
            reverse("edit_item", args=[item.pk]), {"quantity": "30", "urgent": "1"}
        )

        item.refresh_from_db()
        self.assertEqual(item.quantity, Decimal("30"))
        self.assertEqual(item.urgency, OrderItem.Urgency.HIGH)
        self.assertToast(response, "Whole milk updated")

    def test_an_invalid_edit_answers_422_and_keeps_the_row_open(self):
        item = self.open_item()

        response = self.client.post(reverse("edit_item", args=[item.pk]), {"quantity": "-5"})

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.context["editing_id"], item.pk)
        item.refresh_from_db()
        self.assertEqual(item.quantity, Decimal("24"))

    def test_a_completed_item_cannot_be_edited(self):
        item = self.open_item()
        OrderItem.objects.filter(pk=item.pk).update(completed_at=timezone.now())

        response = self.client.post(reverse("edit_item", args=[item.pk]), {"quantity": "30"})

        self.assertEqual(response.status_code, 404)


class DeleteItemTests(OrdersTestCase):
    def test_it_removes_an_open_item_outright(self):
        """Nothing has been bought yet, so there is no history to preserve."""
        item = self.open_item()

        response = self.client.post(reverse("delete_item", args=[item.pk]))

        self.assertFalse(OrderItem.objects.filter(pk=item.pk).exists())
        self.assertToast(response, "Whole milk removed")

    def test_a_completed_item_cannot_be_deleted(self):
        item = self.open_item()
        OrderItem.objects.filter(pk=item.pk).update(completed_at=timezone.now())

        response = self.client.post(reverse("delete_item", args=[item.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(OrderItem.objects.filter(pk=item.pk).exists())


class ProductSearchViewTests(OrdersTestCase):
    def test_it_returns_matching_products(self):
        response = self.client.get(reverse("product_search"), {"q": "milk"})

        self.assertContains(response, "Whole milk")
        self.assertContains(response, "Oat milk")
        self.assertNotContains(response, "Napkins")

    def test_a_blank_query_renders_nothing_at_all(self):
        """An empty dropdown must collapse, not show an empty white box."""
        response = self.client.get(reverse("product_search"), {"q": "   "})

        self.assertEqual(response.content.strip(), b"")

    def test_a_miss_offers_to_create_the_product(self):
        response = self.client.get(reverse("product_search"), {"q": "Cinnamon"})

        self.assertContains(response, "No product matches")
        self.assertContains(response, "as a new product")

    def test_no_template_syntax_leaks_into_the_dropdown(self):
        """A `{# #}` comment only works on one line -- spread over two it stops
        being a comment and renders to the user as literal text. This dropdown
        shipped that way once.
        """
        response = self.client.get(reverse("product_search"), {"q": "milk"})
        markup = response.content.decode()

        for marker in ("{#", "#}", "{%", "%}"):
            self.assertNotIn(marker, markup)


class NewProductTests(OrdersTestCase):
    def test_it_prefills_the_name_from_the_search_box(self):
        """Whatever was typed is almost certainly the name."""
        response = self.client.get(reverse("new_product"), {"q": "Cinnamon syrup"})

        self.assertEqual(response.context["form"].initial["name"], "Cinnamon syrup")

    def test_it_only_offers_active_sellers(self):
        Seller.objects.filter(pk=self.metro.pk).update(is_active=False)

        response = self.client.get(reverse("new_product"))

        self.assertContains(response, "Green Valley Dairy")
        self.assertNotContains(response, "Metro Wholesale")

    def test_it_creates_the_product_and_credits_the_author(self):
        response = self.client.post(reverse("new_product"), {
            "name": "Cinnamon syrup", "seller": self.dairy.pk,
            "unit": "l", "unit_price": "6.50",
        })

        product = Product.objects.get(name="Cinnamon syrup")
        self.assertEqual(product.created_by, self.maria)
        self.assertToast(response, "Cinnamon syrup added to the catalog")

    def test_the_form_offers_the_order_name(self):
        response = self.client.get(reverse("new_product"))

        self.assertContains(response, 'name="order_name"')

    def test_it_stores_the_order_name_when_given(self):
        self.client.post(reverse("new_product"), {
            "name": "Cinnamon syrup", "order_name": "SYR-CIN-1L",
            "seller": self.dairy.pk, "unit": "l", "unit_price": "6.50",
        })

        self.assertEqual(Product.objects.get(name="Cinnamon syrup").order_name, "SYR-CIN-1L")

    def test_success_hands_the_product_back_to_the_quick_add_form(self):
        """The reply is a script that closes the dialog and resumes the order
        that was interrupted.
        """
        response = self.client.post(reverse("new_product"), {
            "name": "Cinnamon syrup", "seller": self.dairy.pk,
            "unit": "l", "unit_price": "6.50",
        })

        self.assertContains(response, "selectProduct(")
        self.assertContains(response, 'getElementById("modal").close()')

    def test_an_invalid_product_answers_422_and_creates_nothing(self):
        response = self.client.post(reverse("new_product"), {
            "name": "Cinnamon syrup", "seller": self.dairy.pk,
            "unit": "l", "unit_price": "0",
        })

        self.assertEqual(response.status_code, 422)
        self.assertFalse(Product.objects.filter(name="Cinnamon syrup").exists())

    def test_it_explains_itself_when_there_are_no_sellers_yet(self):
        """Employees cannot create sellers, so this is a dead end they need
        told about rather than an empty dropdown.
        """
        Seller.objects.update(is_active=False)

        response = self.client.get(reverse("new_product"))

        self.assertContains(response, "no sellers yet")
        self.assertNotContains(response, "Add product")
