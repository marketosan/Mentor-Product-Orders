"""Products without a price.

A product can be added mid-order by someone who does not know what it costs.
Unknown is a real state, and deliberately not the same as zero: a zero would
be a claim the item is free and would quietly understate every total holding it.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from orders.forms import AddOrderItemForm, ProductForm
from orders.models import OrderItem, Product, Seller, Unit

User = get_user_model()


class OptionalPriceTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="boss", email="boss@example.com", password="pw", role=User.Role.ADMIN
        )
        cls.maria = User.objects.create_user(
            username="maria", email="maria@example.com", password="pw"
        )
        cls.dairy = Seller.objects.create(name="Green Valley Dairy")
        cls.litre = Unit.objects.create(name="l", plural="l")
        cls.milk = Product.objects.create(
            name="Whole milk", seller=cls.dairy, unit=cls.litre, unit_price=Decimal("1.15")
        )
        cls.mystery = Product.objects.create(
            name="Cinnamon syrup", seller=cls.dairy, unit=cls.litre, unit_price=None
        )

    def order(self, product, quantity="10", **kwargs):
        return OrderItem.objects.create(
            product=product, quantity=Decimal(quantity),
            unit_price_snapshot=product.unit_price, requested_by=self.maria, **kwargs
        )


class ProductFormPriceTests(OptionalPriceTestCase):
    def form(self, **overrides):
        data = {"name": "Cardamom", "seller": self.dairy.pk, "unit": self.litre.pk, "unit_price": ""}
        data.update(overrides)
        return ProductForm(data)

    def test_a_product_can_be_created_without_a_price(self):
        form = self.form()
        self.assertTrue(form.is_valid(), form.errors)

        self.assertIsNone(form.save().unit_price)

    def test_a_price_is_still_accepted(self):
        form = self.form(unit_price="6.50")
        self.assertTrue(form.is_valid(), form.errors)

        self.assertEqual(form.save().unit_price, Decimal("6.50"))

    def test_zero_is_still_rejected(self):
        """Blank means unknown. Zero claims the item is free, which would
        understate every total it lands in.
        """
        form = self.form(unit_price="0")

        self.assertFalse(form.is_valid())
        self.assertIn("unit_price", form.errors)

    def test_a_negative_price_is_still_rejected(self):
        self.assertFalse(self.form(unit_price="-3").is_valid())

    def test_a_price_can_be_added_later(self):
        form = ProductForm(
            {"name": self.mystery.name, "seller": self.dairy.pk, "unit": self.litre.pk,
             "unit_price": "6.50"},
            instance=self.mystery,
        )
        self.assertTrue(form.is_valid(), form.errors)

        self.assertEqual(form.save().unit_price, Decimal("6.50"))

    def test_a_price_can_be_cleared_again(self):
        form = ProductForm(
            {"name": self.milk.name, "seller": self.dairy.pk, "unit": self.litre.pk, "unit_price": ""},
            instance=self.milk,
        )
        self.assertTrue(form.is_valid(), form.errors)

        self.assertIsNone(form.save().unit_price)

    def test_the_form_no_longer_marks_price_required(self):
        self.assertFalse(ProductForm().fields["unit_price"].required)


class UnpricedOrderItemTests(OptionalPriceTestCase):
    def test_an_unpriced_product_can_still_be_ordered(self):
        form = AddOrderItemForm({"product": self.mystery.pk, "quantity": "3"})
        self.assertTrue(form.is_valid(), form.errors)

        item = form.save(requested_by=self.maria)

        self.assertIsNone(item.unit_price_snapshot)

    def test_line_total_is_none_rather_than_zero(self):
        """Zero would be a number the shop could act on. None cannot be
        mistaken for one.
        """
        item = self.order(self.mystery)

        self.assertIsNone(item.line_total)

    def test_a_priced_item_still_totals(self):
        self.assertEqual(self.order(self.milk, "24").line_total, Decimal("27.60"))

    def test_pricing_the_product_later_does_not_price_what_was_ordered(self):
        """The snapshot rule cuts both ways: filling in a price afterwards must
        not retroactively price an order placed without one.
        """
        item = self.order(self.mystery)
        Product.objects.filter(pk=self.mystery.pk).update(unit_price=Decimal("6.50"))

        item.refresh_from_db()

        self.assertIsNone(item.unit_price_snapshot)
        self.assertIsNone(item.line_total)


class UnpricedTotalsTests(OptionalPriceTestCase):
    def setUp(self):
        self.client.force_login(self.admin)

    def test_a_seller_total_covers_only_the_priced_rows(self):
        self.order(self.milk, "24")      # 27.60
        self.order(self.mystery, "3")    # no price

        group = self.client.get(reverse("dashboard")).context["groups"][0]

        self.assertEqual(group["total"], Decimal("27.60"))
        self.assertEqual(group["unpriced_count"], 1)

    def test_the_screen_says_the_total_is_incomplete(self):
        """A figure that silently omits items reads as authoritative."""
        self.order(self.milk, "24")
        self.order(self.mystery, "3")

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "1 unpriced")

    def test_nothing_is_flagged_when_everything_has_a_price(self):
        self.order(self.milk, "24")

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.context["groups"][0]["unpriced_count"], 0)
        self.assertNotContains(response, "unpriced")

    def test_an_entirely_unpriced_seller_totals_zero_and_says_so(self):
        self.order(self.mystery, "3")

        group = self.client.get(reverse("dashboard")).context["groups"][0]

        self.assertEqual(group["total"], Decimal("0"))
        self.assertEqual(group["unpriced_count"], 1)

    def test_the_grand_total_carries_the_count_too(self):
        self.order(self.milk, "24")
        self.order(self.mystery, "3")

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.context["grand_total"], Decimal("27.60"))
        self.assertEqual(response.context["unpriced_count"], 1)

    def test_history_totals_behave_the_same(self):
        when = timezone.now()
        self.order(self.milk, "24", completed_at=when, completed_by=self.admin)
        self.order(self.mystery, "3", completed_at=when, completed_by=self.admin)

        order = self.client.get(reverse("history")).context["orders"][0]

        self.assertEqual(order["total"], Decimal("27.60"))
        self.assertEqual(order["unpriced_count"], 1)


class UnpricedRenderingTests(OptionalPriceTestCase):
    def setUp(self):
        self.client.force_login(self.admin)

    def test_the_order_list_says_no_price_rather_than_zero(self):
        self.order(self.mystery, "3")

        response = self.client.get(reverse("order_list"))

        self.assertContains(response, "no price")
        self.assertNotContains(response, "&euro;0.00")

    def test_the_dashboard_says_no_price(self):
        self.order(self.mystery, "3")

        self.assertContains(self.client.get(reverse("dashboard")), "no price")

    def test_history_says_no_price(self):
        self.order(self.mystery, "3", completed_at=timezone.now(), completed_by=self.admin)

        self.assertContains(self.client.get(reverse("history")), "no price")

    def test_the_products_page_says_no_price(self):
        self.assertContains(self.client.get(reverse("products")), "no price")

    def test_the_search_dropdown_omits_the_price_rather_than_showing_a_stray_symbol(self):
        response = self.client.get(reverse("product_search"), {"q": "Cinnamon"})

        self.assertContains(response, "Cinnamon syrup")
        self.assertNotContains(response, "&euro;/")
        self.assertNotContains(response, "&euro;0.00")
