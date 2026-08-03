"""Form validation, including the rules that live nowhere else.

The urgent tick box and the case-insensitive duplicate check are both form-only
behaviour, so a form test is the only place they get covered.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from orders.forms import AddOrderItemForm, EditOrderItemForm, ProductForm
from orders.models import OrderItem, Product, Seller

User = get_user_model()


class AddOrderItemFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.maria = User.objects.create_user(
            username="maria", email="maria@example.com", password="x"
        )
        cls.dairy = Seller.objects.create(name="Green Valley Dairy")
        cls.milk = Product.objects.create(
            name="Whole milk", seller=cls.dairy, unit="l", unit_price="1.15"
        )

    def test_it_freezes_the_price_and_records_who_asked(self):
        form = AddOrderItemForm({"product": self.milk.pk, "quantity": "24"})
        self.assertTrue(form.is_valid(), form.errors)

        item = form.save(requested_by=self.maria)

        self.assertEqual(item.unit_price_snapshot, Decimal("1.15"))
        self.assertEqual(item.requested_by, self.maria)

    def test_an_unticked_box_means_low_urgency(self):
        """An unticked checkbox submits nothing at all, which is exactly why
        urgency cannot be the model field itself.
        """
        form = AddOrderItemForm({"product": self.milk.pk, "quantity": "24"})
        self.assertTrue(form.is_valid(), form.errors)

        self.assertEqual(form.save(requested_by=self.maria).urgency, OrderItem.Urgency.LOW)

    def test_a_ticked_box_means_high_urgency(self):
        form = AddOrderItemForm({"product": self.milk.pk, "quantity": "24", "urgent": "1"})
        self.assertTrue(form.is_valid(), form.errors)

        self.assertEqual(form.save(requested_by=self.maria).urgency, OrderItem.Urgency.HIGH)

    def test_zero_and_negative_quantities_are_rejected(self):
        for quantity in ("0", "-1"):
            with self.subTest(quantity=quantity):
                form = AddOrderItemForm({"product": self.milk.pk, "quantity": quantity})

                self.assertFalse(form.is_valid())
                self.assertIn("quantity", form.errors)

    def test_a_missing_product_explains_how_to_pick_one(self):
        form = AddOrderItemForm({"quantity": "24"})

        self.assertFalse(form.is_valid())
        self.assertIn("Search for a product", str(form.errors["product"]))

    def test_inactive_products_cannot_be_ordered(self):
        Product.objects.filter(pk=self.milk.pk).update(is_active=False)
        form = AddOrderItemForm({"product": self.milk.pk, "quantity": "24"})

        self.assertFalse(form.is_valid())

    def test_products_from_an_inactive_seller_cannot_be_ordered(self):
        Seller.objects.filter(pk=self.dairy.pk).update(is_active=False)
        form = AddOrderItemForm({"product": self.milk.pk, "quantity": "24"})

        self.assertFalse(form.is_valid())


class EditOrderItemFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.maria = User.objects.create_user(
            username="maria", email="maria@example.com", password="x"
        )
        seller = Seller.objects.create(name="Green Valley Dairy")
        cls.milk = Product.objects.create(
            name="Whole milk", seller=seller, unit="l", unit_price="1.15"
        )

    def _item(self, urgency=OrderItem.Urgency.LOW):
        # Decimal rather than str, so the instance matches what a fetch returns.
        return OrderItem.objects.create(
            product=self.milk, quantity=Decimal("24"), urgency=urgency,
            unit_price_snapshot=Decimal("1.15"), requested_by=self.maria,
        )

    def test_the_box_starts_ticked_for_an_urgent_item(self):
        form = EditOrderItemForm(instance=self._item(OrderItem.Urgency.HIGH))

        self.assertTrue(form.fields["urgent"].initial)

    def test_the_box_starts_unticked_for_a_normal_item(self):
        form = EditOrderItemForm(instance=self._item())

        self.assertFalse(form.fields["urgent"].initial)

    def test_it_can_clear_urgency_as_well_as_set_it(self):
        item = self._item(OrderItem.Urgency.HIGH)
        form = EditOrderItemForm({"quantity": "30"}, instance=item)
        self.assertTrue(form.is_valid(), form.errors)

        saved = form.save()

        self.assertEqual(saved.urgency, OrderItem.Urgency.LOW)
        self.assertEqual(saved.quantity, Decimal("30"))

    def test_the_price_snapshot_survives_an_edit(self):
        item = self._item()
        self.milk.unit_price = Decimal("9.99")
        self.milk.save()

        form = EditOrderItemForm({"quantity": "30"}, instance=item)
        self.assertTrue(form.is_valid(), form.errors)

        self.assertEqual(form.save().unit_price_snapshot, Decimal("1.15"))


class ProductFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dairy = Seller.objects.create(name="Green Valley Dairy")
        cls.metro = Seller.objects.create(name="Metro Wholesale")

    def test_it_creates_a_product(self):
        form = ProductForm({
            "name": "Oat milk", "seller": self.dairy.pk, "unit": "l", "unit_price": "2.40",
        })
        self.assertTrue(form.is_valid(), form.errors)

        self.assertEqual(form.save().seller, self.dairy)

    def test_a_free_product_is_rejected(self):
        form = ProductForm({
            "name": "Oat milk", "seller": self.dairy.pk, "unit": "l", "unit_price": "0",
        })

        self.assertFalse(form.is_valid())
        self.assertIn("unit_price", form.errors)

    def test_a_duplicate_name_is_caught_regardless_of_case(self):
        """The database constraint is case-sensitive; to a shop "Oat milk" and
        "oat milk" from one seller are the same thing, so the form is stricter.
        """
        Product.objects.create(name="Oat milk", seller=self.dairy, unit="l", unit_price="2.40")
        form = ProductForm({
            "name": "OAT MILK", "seller": self.dairy.pk, "unit": "l", "unit_price": "2.40",
        })

        self.assertFalse(form.is_valid())
        self.assertIn("Oat milk", str(form.non_field_errors()))

    def test_the_same_name_is_fine_under_a_different_seller(self):
        Product.objects.create(name="Oat milk", seller=self.dairy, unit="l", unit_price="2.40")
        form = ProductForm({
            "name": "Oat milk", "seller": self.metro.pk, "unit": "l", "unit_price": "2.10",
        })

        self.assertTrue(form.is_valid(), form.errors)

    def test_inactive_sellers_are_not_offered(self):
        Seller.objects.filter(pk=self.metro.pk).update(is_active=False)
        form = ProductForm()

        self.assertNotIn(self.metro, form.fields["seller"].queryset)

    def test_order_name_is_not_an_employee_field(self):
        """It is admin-only, so it must never appear in the modal employees use."""
        self.assertNotIn("order_name", ProductForm().fields)
