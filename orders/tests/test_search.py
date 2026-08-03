from django.test import TestCase

from orders.models import Product, Seller
from orders.search import search_products


class ProductSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.roaster = Seller.objects.create(name="Bertoli Coffee Roasters")
        cls.dairy = Seller.objects.create(name="Green Valley Dairy")
        cls.metro = Seller.objects.create(name="Metro Wholesale")

        for name, seller in [
            ("Whole milk", cls.dairy),
            ("Oat milk", cls.dairy),
            ("Espresso beans - house blend", cls.roaster),
            ("Decaf beans", cls.roaster),
            ("Napkins", cls.metro),
        ]:
            Product.objects.create(
                name=name, seller=seller, unit=Product.Unit.KG, unit_price="1.00"
            )

    def names(self, query):
        return [product.name for product in search_products(query)]

    def test_matches_the_start_of_any_word(self):
        self.assertIn("Whole milk", self.names("mil"))
        self.assertIn("Espresso beans - house blend", self.names("hou"))

    def test_ignores_matches_inside_a_word(self):
        """The old behaviour: 'ilk' matched 'milk'. It should not."""
        self.assertEqual(self.names("ilk"), [])

    def test_ranks_products_whose_name_starts_with_the_query_first(self):
        self.assertEqual(self.names("oat")[0], "Oat milk")

    def test_tolerates_a_typo(self):
        self.assertIn("Napkins", self.names("nakpins"))
        self.assertIn("Whole milk", self.names("mikl"))

    def test_every_token_must_match(self):
        self.assertEqual(self.names("espresso beans"), ["Espresso beans - house blend"])
        self.assertEqual(self.names("espresso napkins"), [])

    def test_falls_back_to_the_seller_name(self):
        self.assertEqual(
            sorted(self.names("bertoli")),
            ["Decaf beans", "Espresso beans - house blend"],
        )

    def test_product_name_matches_outrank_seller_matches(self):
        Product.objects.create(
            name="Metro branded sugar", seller=self.roaster,
            unit=Product.Unit.KG, unit_price="1.00",
        )
        self.assertEqual(self.names("metro")[0], "Metro branded sugar")

    def test_inactive_products_and_sellers_are_hidden(self):
        Product.objects.filter(name="Napkins").update(is_active=False)
        self.assertEqual(self.names("napkins"), [])

        Seller.objects.filter(pk=self.dairy.pk).update(is_active=False)
        self.assertEqual(self.names("milk"), [])

    def test_blank_query_returns_nothing(self):
        self.assertEqual(self.names(""), [])
        self.assertEqual(self.names("   "), [])
