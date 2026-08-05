"""Removing a product: deleted outright when unused, deactivated when not.

Rule 3 keeps anything order history points at. A product that has never been
ordered points at nothing, so a typo or a duplicate can go properly rather than
cluttering the catalog forever.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from orders.models import OrderItem, Product, Seller

User = get_user_model()


class DeleteProductTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="boss", email="boss@example.com", password="pw", role=User.Role.ADMIN
        )
        cls.maria = User.objects.create_user(
            username="maria", email="maria@example.com", password="pw"
        )
        cls.dairy = Seller.objects.create(name="Green Valley Dairy")

    def setUp(self):
        self.client.force_login(self.admin)

    def product(self, name="Typo"):
        return Product.objects.create(
            name=name, seller=self.dairy, unit="kg", unit_price=Decimal("1.00")
        )

    def ordered_product(self, name="Whole milk", **item_kwargs):
        product = self.product(name)
        OrderItem.objects.create(
            product=product, quantity=Decimal("2"),
            unit_price_snapshot=product.unit_price, requested_by=self.maria, **item_kwargs
        )
        return product

    def delete(self, product):
        return self.client.post(reverse("delete_product", args=[product.pk]))

    def toggle(self, product):
        return self.client.post(reverse("toggle_product", args=[product.pk]))

    def toast(self, response):
        import json
        return json.loads(response.headers["HX-Trigger"])["toast"]["message"]


class DeleteUnusedProductTests(DeleteProductTestCase):
    def test_a_product_never_ordered_is_deleted_outright(self):
        product = self.product()

        self.delete(product)

        self.assertFalse(Product.objects.filter(pk=product.pk).exists())

    def test_it_confirms_the_deletion(self):
        product = self.product("Duplicate krepes")

        self.assertIn("Duplicate krepes deleted", self.toast(self.delete(product)))

    def test_an_inactive_unused_product_can_also_be_deleted(self):
        product = self.product()
        Product.objects.filter(pk=product.pk).update(is_active=False)

        self.delete(product)

        self.assertFalse(Product.objects.filter(pk=product.pk).exists())

    def test_the_button_is_offered_only_for_unused_products(self):
        unused = self.product("Typo")
        used = self.ordered_product("Whole milk")

        response = self.client.get(reverse("products"))

        self.assertContains(response, reverse("delete_product", args=[unused.pk]))
        self.assertNotContains(response, reverse("delete_product", args=[used.pk]))


class DeleteUsedProductTests(DeleteProductTestCase):
    def test_a_product_with_history_is_refused_rather_than_deleted(self):
        """PROTECT would raise anyway. Catching it here means an explanation
        instead of a 500.
        """
        product = self.ordered_product()

        response = self.delete(product)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())
        self.assertIn("cannot be deleted", self.toast(response))

    def test_the_refusal_says_what_to_do_instead(self):
        product = self.ordered_product()

        self.assertIn("Deactivate it instead", self.toast(self.delete(product)))

    def test_a_completed_order_still_counts_as_history(self):
        product = self.ordered_product(
            completed_at=timezone.now(), completed_by=self.admin
        )

        self.delete(product)

        self.assertTrue(Product.objects.filter(pk=product.pk).exists())

    def test_the_order_item_survives_the_attempt(self):
        product = self.ordered_product()

        self.delete(product)

        self.assertEqual(OrderItem.objects.filter(product=product).count(), 1)


class ToggleProductTests(DeleteProductTestCase):
    def test_deactivating_keeps_the_row(self):
        product = self.ordered_product()

        self.toggle(product)

        product.refresh_from_db()
        self.assertFalse(product.is_active)
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())

    def test_it_toggles_back(self):
        product = self.product()
        self.toggle(product)
        self.toggle(product)

        product.refresh_from_db()
        self.assertTrue(product.is_active)

    def test_the_toast_says_which_way_it_went(self):
        product = self.product()

        off = self.toast(self.toggle(product))
        on = self.toast(self.toggle(product))

        self.assertIn("deactivated", off)
        self.assertIn("reactivated", on)

    def test_a_deactivated_product_leaves_the_quick_add_search(self):
        product = self.product("Whole milk")

        self.toggle(product)

        from orders.search import search_products
        self.assertEqual(search_products("milk"), [])

    def test_a_deactivated_product_cannot_be_added_to_the_list(self):
        product = self.product()
        self.toggle(product)

        from orders.forms import AddOrderItemForm
        form = AddOrderItemForm({"product": product.pk, "quantity": "1"})

        self.assertFalse(form.is_valid())

    def test_deactivating_does_not_touch_existing_orders(self):
        product = self.ordered_product()

        self.toggle(product)

        item = OrderItem.objects.get(product=product)
        self.assertEqual(item.quantity, Decimal("2"))

    def test_it_keeps_the_current_search(self):
        self.product("Whole milk")
        target = self.product("Napkins")

        response = self.client.post(
            reverse("toggle_product", args=[target.pk]), {"q": "napkins"}
        )

        self.assertEqual([p.name for p in response.context["products"]], ["Napkins"])


class ProductRemovalPermissionTests(DeleteProductTestCase):
    def test_an_employee_cannot_delete(self):
        product = self.product()
        self.client.force_login(self.maria)

        self.assertEqual(self.delete(product).status_code, 403)
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())

    def test_an_employee_cannot_deactivate(self):
        product = self.product()
        self.client.force_login(self.maria)

        self.assertEqual(self.toggle(product).status_code, 403)

    def test_both_refuse_a_get(self):
        product = self.product()

        for name in ("delete_product", "toggle_product"):
            with self.subTest(view=name):
                url = reverse(name, args=[product.pk])

                self.assertEqual(self.client.get(url).status_code, 405)

    def test_an_unknown_product_is_a_404(self):
        self.assertEqual(
            self.client.post(reverse("delete_product", args=[999999])).status_code, 404
        )
