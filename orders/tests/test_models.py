"""Model-level rules: the ones the database and the history depend on."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone

from orders.models import OrderItem, Product, Seller

User = get_user_model()


class ProductConstraintTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dairy = Seller.objects.create(name="Green Valley Dairy")
        cls.metro = Seller.objects.create(name="Metro Wholesale")

    def test_the_same_name_is_allowed_for_two_different_sellers(self):
        """The shop's reason for per-seller uniqueness: buying one item from
        two suppliers must not force a rename.
        """
        Product.objects.create(name="Whole milk", seller=self.dairy, unit="l", unit_price="1.15")
        Product.objects.create(name="Whole milk", seller=self.metro, unit="l", unit_price="1.30")

        self.assertEqual(Product.objects.filter(name="Whole milk").count(), 2)

    def test_the_same_name_twice_for_one_seller_is_rejected(self):
        Product.objects.create(name="Whole milk", seller=self.dairy, unit="l", unit_price="1.15")

        with self.assertRaises(IntegrityError), transaction.atomic():
            Product.objects.create(name="Whole milk", seller=self.dairy, unit="l", unit_price="1.15")

    def test_a_seller_with_products_cannot_be_deleted(self):
        """Order history points at products, which point at sellers, so the
        chain is PROTECTed rather than cascading history away.
        """
        Product.objects.create(name="Whole milk", seller=self.dairy, unit="l", unit_price="1.15")

        with self.assertRaises(ProtectedError):
            self.dairy.delete()


class OrderItemTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.maria = User.objects.create_user(
            username="maria", email="maria@example.com", password="x"
        )
        cls.dairy = Seller.objects.create(name="Green Valley Dairy")
        cls.milk = Product.objects.create(
            name="Whole milk", seller=cls.dairy, unit="l", unit_price=Decimal("1.15")
        )

    def _item(self, **kwargs):
        """Decimal, not str: the database hands these back as Decimal, and
        `line_total` is arithmetic, so a str fixture would not be lifelike.
        """
        return OrderItem.objects.create(
            product=kwargs.pop("product", self.milk),
            quantity=Decimal(kwargs.pop("quantity", "24")),
            unit_price_snapshot=Decimal(kwargs.pop("unit_price_snapshot", "1.15")),
            requested_by=self.maria,
            **kwargs,
        )

    def test_line_total_multiplies_quantity_by_the_frozen_price(self):
        item = self._item(quantity="24", unit_price_snapshot="1.15")

        self.assertEqual(item.line_total, Decimal("27.60"))

    def test_a_later_catalog_price_change_does_not_rewrite_history(self):
        """Business rule 2: the snapshot is the whole point of the field."""
        item = self._item(unit_price_snapshot="1.15")

        self.milk.unit_price = Decimal("1.80")
        self.milk.save()
        item.refresh_from_db()

        self.assertEqual(item.unit_price_snapshot, Decimal("1.15"))
        self.assertEqual(item.line_total, Decimal("27.60"))

    def test_open_and_completed_split_on_completed_at(self):
        open_item = self._item()
        done = self._item(completed_at=timezone.now(), completed_by=self.maria)

        self.assertEqual(list(OrderItem.objects.open()), [open_item])
        self.assertEqual(list(OrderItem.objects.completed()), [done])

    def test_is_open_follows_completed_at(self):
        self.assertTrue(self._item().is_open)
        self.assertFalse(self._item(completed_at=timezone.now()).is_open)

    def test_a_product_with_order_items_cannot_be_deleted(self):
        self._item()

        with self.assertRaises(ProtectedError):
            self.milk.delete()

    def test_newest_items_come_first(self):
        first = self._item()
        second = self._item(quantity="5")

        self.assertEqual(list(OrderItem.objects.open()), [second, first])


class SellerViberLinkTests(TestCase):
    """Numbers are stored the way a person writes them; the link needs them bare."""

    def url_for(self, phone):
        return Seller.objects.create(name=f"Seller {phone!r}", phone=phone).viber_url

    def test_spaces_and_punctuation_come_out(self):
        self.assertEqual(
            self.url_for("+30 210 555 0198"), "viber://chat?number=%2B302105550198"
        )
        self.assertEqual(
            self.url_for("(0030) 210-555.0198"), "viber://chat?number=00302105550198"
        )

    def test_the_plus_is_percent_encoded(self):
        """A bare + in a query string means a space, so it has to be escaped."""
        url = self.url_for("+306912345678")

        self.assertIn("%2B", url)
        self.assertNotIn("+", url)

    def test_a_number_without_a_country_code_is_left_alone(self):
        self.assertEqual(self.url_for("2105550198"), "viber://chat?number=2105550198")

    def test_a_seller_with_no_phone_has_no_link(self):
        self.assertEqual(self.url_for(""), "")

    def test_a_phone_field_holding_only_punctuation_has_no_link(self):
        """Otherwise the header would render a link to viber://chat?number=."""
        self.assertEqual(self.url_for("n/a"), "")
        self.assertEqual(self.url_for("+"), "")


class ProductOrderNameTests(TestCase):
    """`order_name` is admin-only, so the guarantee worth testing is that it
    stays optional and never becomes required for the employee flow.
    """

    def test_it_defaults_to_empty_rather_than_null(self):
        seller = Seller.objects.create(name="Metro Wholesale")
        product = Product.objects.create(
            name="Napkins", seller=seller, unit="box", unit_price="8.75"
        )

        self.assertEqual(product.order_name, "")

    def test_it_holds_the_sellers_own_name_for_the_item(self):
        seller = Seller.objects.create(name="Metro Wholesale")
        product = Product.objects.create(
            name="Napkins", seller=seller, unit="box", unit_price="8.75",
            order_name="NAP-2PLY-250",
        )
        product.full_clean()  # optional field, so this must not raise

        self.assertEqual(Product.objects.get(pk=product.pk).order_name, "NAP-2PLY-250")
