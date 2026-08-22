"""Removing a seller: deleted outright when unused, deactivated when not.

Mirrors test_delete_product.py -- same split, same reasoning. Rule 3 keeps
anything order history points at, and a seller with no products isn't pointed
at by anything: PROTECT on Product.seller only bites once a product exists.
"""

import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from orders.models import OrderItem, Product, Seller

User = get_user_model()


class DeleteSellerTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="boss", email="boss@example.com", password="pw", role=User.Role.ADMIN
        )
        cls.maria = User.objects.create_user(
            username="maria", email="maria@example.com", password="pw"
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def seller(self, name="Corner Shop"):
        return Seller.objects.create(name=name)

    def seller_with_product(self, name="Green Valley Dairy"):
        seller = self.seller(name)
        Product.objects.create(name="Whole milk", seller=seller, unit="l", unit_price=Decimal("1.15"))
        return seller

    def delete(self, seller):
        return self.client.post(reverse("delete_seller", args=[seller.pk]))

    def toggle(self, seller):
        return self.client.post(reverse("toggle_seller", args=[seller.pk]))

    def toast(self, response):
        return json.loads(response.headers["HX-Trigger"])["toast"]["message"]


class DeleteUnusedSellerTests(DeleteSellerTestCase):
    def test_a_seller_with_no_products_is_deleted_outright(self):
        seller = self.seller()

        self.delete(seller)

        self.assertFalse(Seller.objects.filter(pk=seller.pk).exists())

    def test_it_confirms_the_deletion(self):
        seller = self.seller("Corner Shop")

        self.assertIn("Corner Shop deleted", self.toast(self.delete(seller)))

    def test_an_inactive_unused_seller_can_also_be_deleted(self):
        seller = self.seller()
        Seller.objects.filter(pk=seller.pk).update(is_active=False)

        self.delete(seller)

        self.assertFalse(Seller.objects.filter(pk=seller.pk).exists())

    def test_the_button_is_offered_only_for_unused_sellers(self):
        unused = self.seller("Corner Shop")
        used = self.seller_with_product("Green Valley Dairy")

        response = self.client.get(
            reverse("sellers"), {"filtered": "1", "active": "1", "inactive": "1"}
        )

        self.assertContains(response, reverse("delete_seller", args=[unused.pk]))
        self.assertNotContains(response, reverse("delete_seller", args=[used.pk]))


class DeleteUsedSellerTests(DeleteSellerTestCase):
    def test_a_seller_with_products_is_refused_rather_than_deleted(self):
        """PROTECT would raise anyway. Catching it here means an explanation
        instead of a 500.
        """
        seller = self.seller_with_product()

        response = self.delete(seller)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Seller.objects.filter(pk=seller.pk).exists())
        self.assertIn("cannot be deleted", self.toast(response))

    def test_the_refusal_says_what_to_do_instead(self):
        seller = self.seller_with_product()

        self.assertIn("Deactivate it instead", self.toast(self.delete(seller)))

    def test_the_product_survives_the_attempt(self):
        seller = self.seller_with_product()

        self.delete(seller)

        self.assertEqual(Product.objects.filter(seller=seller).count(), 1)


class SellerRemovalPermissionTests(DeleteSellerTestCase):
    def test_an_employee_cannot_delete(self):
        seller = self.seller()
        self.client.force_login(self.maria)

        self.assertEqual(self.delete(seller).status_code, 403)
        self.assertTrue(Seller.objects.filter(pk=seller.pk).exists())

    def test_both_refuse_a_get(self):
        seller = self.seller()

        self.assertEqual(
            self.client.get(reverse("delete_seller", args=[seller.pk])).status_code, 405
        )

    def test_an_unknown_seller_is_a_404(self):
        self.assertEqual(
            self.client.post(reverse("delete_seller", args=[999999])).status_code, 404
        )
