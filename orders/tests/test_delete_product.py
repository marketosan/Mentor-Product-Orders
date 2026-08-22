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

    def delete_all(self):
        return self.client.post(reverse("delete_all_products"))

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
            reverse("toggle_product", args=[target.pk]),
            # Both tickboxes on: toggling flips Napkins to inactive, and the
            # default (active-only) filter would otherwise hide the very row
            # this test is checking the search kept.
            {"q": "napkins", "filtered": "1", "active": "1", "inactive": "1"},
        )

        self.assertEqual([p.name for p in response.context["products"]], ["Napkins"])


class DeleteAllProductsTests(DeleteProductTestCase):
    def test_unused_products_are_deleted_and_used_ones_deactivated(self):
        unused = self.product("Typo")
        used = self.ordered_product("Whole milk")

        self.delete_all()

        self.assertFalse(Product.objects.filter(pk=unused.pk).exists())
        used.refresh_from_db()
        self.assertFalse(used.is_active)
        self.assertTrue(Product.objects.filter(pk=used.pk).exists())

    def test_an_already_inactive_used_product_is_left_alone(self):
        used = self.ordered_product("Whole milk")
        Product.objects.filter(pk=used.pk).update(is_active=False)

        response = self.delete_all()

        used.refresh_from_db()
        self.assertFalse(used.is_active)
        self.assertNotIn("deactivated", self.toast(response))

    def test_the_toast_reports_both_counts(self):
        self.product("Typo")
        self.ordered_product("Whole milk")

        message = self.toast(self.delete_all())

        self.assertIn("1 deleted", message)
        self.assertIn("1 deactivated", message)

    def test_an_empty_catalog_says_so(self):
        message = self.toast(self.delete_all())

        self.assertIn("No products to remove", message)

    def test_it_ignores_the_search_box_and_acts_on_everyone(self):
        """The deletion itself is not scoped to whatever the search box holds
        -- only the redisplayed list is, same as any row action.
        """
        hidden_by_search = self.product("Typo")

        self.client.post(reverse("delete_all_products"), {"q": "nothing matches this"})

        self.assertFalse(Product.objects.filter(pk=hidden_by_search.pk).exists())

    def test_it_ignores_the_active_filter_too(self):
        """Whole-catalog action: even a product hidden by the Inactive-only
        view still gets swept up.
        """
        hidden_by_filter = self.product("Typo")

        self.client.post(
            reverse("delete_all_products"), {"filtered": "1", "active": "0", "inactive": "1"}
        )

        self.assertFalse(Product.objects.filter(pk=hidden_by_filter.pk).exists())


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

    def test_an_employee_cannot_delete_all(self):
        product = self.product()
        self.client.force_login(self.maria)

        self.assertEqual(self.delete_all().status_code, 403)
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())

    def test_both_refuse_a_get(self):
        product = self.product()

        for name in ("delete_product", "toggle_product"):
            with self.subTest(view=name):
                url = reverse(name, args=[product.pk])

                self.assertEqual(self.client.get(url).status_code, 405)

        self.assertEqual(self.client.get(reverse("delete_all_products")).status_code, 405)

    def test_an_unknown_product_is_a_404(self):
        self.assertEqual(
            self.client.post(reverse("delete_product", args=[999999])).status_code, 404
        )
