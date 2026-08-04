"""Editing a catalog entry, from either the order list or the dashboard."""

import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from orders.models import OrderItem, Product, Seller

User = get_user_model()


class EditProductTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.maria = User.objects.create_user(
            username="maria", email="maria@example.com", password="pw"
        )
        cls.dairy = Seller.objects.create(name="Green Valley Dairy")
        cls.metro = Seller.objects.create(name="Metro Wholesale")
        cls.milk = Product.objects.create(
            name="Whole milk", seller=cls.dairy, unit="l", unit_price=Decimal("1.15")
        )

    def setUp(self):
        self.client.force_login(self.maria)

    def edit(self, product=None, origin="panel", **overrides):
        product = product or self.milk
        data = {
            "name": product.name, "order_name": product.order_name,
            "seller": product.seller_id, "unit": product.unit,
            "unit_price": product.unit_price, "origin": origin,
        }
        data.update(overrides)
        return self.client.post(reverse("edit_product", args=[product.pk]), data)


class EditProductFormTests(EditProductTestCase):
    def test_it_opens_prefilled_with_every_field(self):
        self.milk.order_name = "MILK-1L"
        self.milk.save()

        response = self.client.get(reverse("edit_product", args=[self.milk.pk]))

        self.assertContains(response, "Edit product")
        self.assertContains(response, "Whole milk")
        self.assertContains(response, "MILK-1L")
        self.assertContains(response, "1.15")

    def test_it_offers_every_editable_field(self):
        response = self.client.get(reverse("edit_product", args=[self.milk.pk]))

        for field in ("name", "order_name", "seller", "unit", "unit_price"):
            with self.subTest(field=field):
                self.assertContains(response, f'name="{field}"')

    def test_an_unknown_product_is_a_404(self):
        self.assertEqual(
            self.client.get(reverse("edit_product", args=[999999])).status_code, 404
        )

    def test_it_requires_a_login(self):
        self.client.logout()

        response = self.client.get(reverse("edit_product", args=[self.milk.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)


class EditProductSaveTests(EditProductTestCase):
    def test_it_changes_every_field(self):
        self.edit(
            name="Whole milk 1L", order_name="MILK-1L",
            seller=self.metro.pk, unit="pack", unit_price="1.40",
        )

        self.milk.refresh_from_db()
        self.assertEqual(self.milk.name, "Whole milk 1L")
        self.assertEqual(self.milk.order_name, "MILK-1L")
        self.assertEqual(self.milk.seller, self.metro)
        self.assertEqual(self.milk.unit, "pack")
        self.assertEqual(self.milk.unit_price, Decimal("1.40"))

    def test_order_name_can_be_added_to_an_existing_product(self):
        """It did not exist when most of the catalog was created."""
        self.edit(order_name="MILK-1L")

        self.milk.refresh_from_db()
        self.assertEqual(self.milk.order_name, "MILK-1L")

    def test_order_name_can_be_cleared_again(self):
        self.milk.order_name = "MILK-1L"
        self.milk.save()

        self.edit(order_name="")

        self.milk.refresh_from_db()
        self.assertEqual(self.milk.order_name, "")

    def test_saving_without_renaming_is_not_a_duplicate(self):
        """The case-insensitive clash check has to exclude the row being saved,
        or editing a price would fail on the product's own name.
        """
        response = self.edit(unit_price="1.40")

        self.assertEqual(response.status_code, 200)
        self.milk.refresh_from_db()
        self.assertEqual(self.milk.unit_price, Decimal("1.40"))

    def test_taking_another_products_name_under_one_seller_is_rejected(self):
        Product.objects.create(
            name="Oat milk", seller=self.dairy, unit="l", unit_price=Decimal("2.40")
        )

        response = self.edit(name="oat milk")

        self.assertEqual(response.status_code, 422)
        self.milk.refresh_from_db()
        self.assertEqual(self.milk.name, "Whole milk")

    def test_a_free_product_is_rejected(self):
        response = self.edit(unit_price="0")

        self.assertEqual(response.status_code, 422)
        self.milk.refresh_from_db()
        self.assertEqual(self.milk.unit_price, Decimal("1.15"))

    def test_open_items_keep_the_price_they_were_requested_at(self):
        """Rule 2: a catalog correction must not rewrite what the shop already
        agreed to pay.
        """
        item = OrderItem.objects.create(
            product=self.milk, quantity=Decimal("24"),
            unit_price_snapshot=Decimal("1.15"), requested_by=self.maria,
        )

        self.edit(unit_price="9.99")

        item.refresh_from_db()
        self.assertEqual(item.unit_price_snapshot, Decimal("1.15"))
        self.assertEqual(item.line_total, Decimal("27.60"))

    def test_open_items_keep_their_quantity(self):
        item = OrderItem.objects.create(
            product=self.milk, quantity=Decimal("24"),
            unit_price_snapshot=Decimal("1.15"), requested_by=self.maria,
        )

        self.edit(name="Whole milk 1L", unit="pack")

        item.refresh_from_db()
        self.assertEqual(item.quantity, Decimal("24"))


class EditProductOriginTests(EditProductTestCase):
    """The form posts from inside the dialog, so it always targets #modal-body.
    `origin` is what tells the reply which page to refresh.
    """

    def test_saving_from_the_order_list_refreshes_the_panel(self):
        response = self.edit(origin="panel", unit_price="1.40")

        self.assertTemplateUsed(response, "orders/_panel.html")
        self.assertEqual(response.headers["HX-Retarget"], "#panel")

    def test_saving_from_the_dashboard_refreshes_the_dashboard(self):
        response = self.edit(origin="dashboard", unit_price="1.40")

        self.assertTemplateUsed(response, "orders/_dashboard_body.html")
        self.assertEqual(response.headers["HX-Retarget"], "#dashboard-body")

    def test_a_missing_origin_falls_back_to_the_panel(self):
        response = self.edit(origin="", unit_price="1.40")

        self.assertEqual(response.headers["HX-Retarget"], "#panel")

    def test_saving_shuts_the_dialog_and_confirms(self):
        response = self.edit(unit_price="1.40")

        fired = json.loads(response.headers["HX-Trigger"])
        self.assertTrue(fired["closeModal"])
        self.assertIn("Whole milk updated", fired["toast"]["message"])

    def test_the_origin_survives_a_rejected_save(self):
        """Otherwise fixing the error would refresh the wrong page."""
        response = self.edit(origin="dashboard", unit_price="0")

        self.assertEqual(response.status_code, 422)
        self.assertContains(response, 'value="dashboard"', status_code=422)


class EditProductEntryPointTests(EditProductTestCase):
    """Reachable from both lists, as the product name itself."""

    def item(self):
        return OrderItem.objects.create(
            product=self.milk, quantity=Decimal("24"),
            unit_price_snapshot=Decimal("1.15"), requested_by=self.maria,
        )

    def test_the_order_list_links_the_product_name(self):
        self.item()

        response = self.client.get(reverse("order_list"))

        self.assertContains(response, f"{reverse('edit_product', args=[self.milk.pk])}?origin=panel")

    def test_the_dashboard_links_the_product_name(self):
        self.item()
        admin = User.objects.create_user(
            username="boss", email="boss@example.com", password="pw", role=User.Role.ADMIN
        )
        self.client.force_login(admin)

        response = self.client.get(reverse("dashboard"))

        self.assertContains(
            response, f"{reverse('edit_product', args=[self.milk.pk])}?origin=dashboard"
        )

    def test_the_dashboard_has_a_dialog_to_open_it_into(self):
        """It had none until product editing arrived -- without it the form
        would render nowhere.
        """
        admin = User.objects.create_user(
            username="boss", email="boss@example.com", password="pw", role=User.Role.ADMIN
        )
        self.client.force_login(admin)

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, 'id="modal"')
        self.assertContains(response, 'id="modal-body"')
