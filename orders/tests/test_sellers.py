"""Managing suppliers: search, add, edit, deactivate."""

import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from orders.models import OrderItem, Product, Seller, Unit

User = get_user_model()


class SellerAdminTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="boss", email="boss@example.com", password="pw", role=User.Role.ADMIN
        )
        cls.maria = User.objects.create_user(
            username="maria", email="maria@example.com", password="pw"
        )
        cls.dairy = Seller.objects.create(
            name="Green Valley Dairy", phone="+30 210 555 0198", email="hello@greenvalley.example"
        )
        cls.metro = Seller.objects.create(name="Metro Wholesale", email="sales@metro.example")

    def setUp(self):
        self.client.force_login(self.admin)

    def names(self, response):
        return [seller.name for seller in response.context["sellers"]]


class SellerSearchTests(SellerAdminTestCase):
    def search(self, q):
        return self.client.get(reverse("sellers"), {"q": q})

    def test_it_matches_part_of_a_name(self):
        self.assertEqual(self.names(self.search("valley")), ["Green Valley Dairy"])

    def test_matching_ignores_case(self):
        self.assertEqual(self.names(self.search("METRO")), ["Metro Wholesale"])

    def test_it_matches_a_phone_number(self):
        self.assertEqual(self.names(self.search("0198")), ["Green Valley Dairy"])

    def test_it_matches_an_email(self):
        self.assertEqual(self.names(self.search("sales@")), ["Metro Wholesale"])

    def test_a_blank_search_shows_everyone(self):
        self.assertEqual(len(self.names(self.search("   "))), 2)

    def test_inactive_sellers_still_appear(self):
        """This is the only page that can bring one back, so hiding them here
        would strand them -- findable with the Inactive tickbox on.
        """
        Seller.objects.filter(pk=self.metro.pk).update(is_active=False)

        response = self.client.get(
            reverse("sellers"), {"q": "metro", "filtered": "1", "active": "1", "inactive": "1"}
        )

        self.assertIn("Metro Wholesale", self.names(response))

    def test_a_miss_says_so_and_names_the_query(self):
        response = self.search("nobody")

        self.assertEqual(self.names(response), [])
        self.assertContains(response, "No seller matches")
        self.assertContains(response, "nobody")

    def test_searching_returns_only_the_list_fragment(self):
        response = self.client.get(
            reverse("sellers"), {"q": "valley"}, headers={"hx-request": "true"}
        )

        self.assertTemplateUsed(response, "orders/_seller_list.html")
        self.assertTemplateNotUsed(response, "orders/sellers.html")
        self.assertNotContains(response, "<html")

    def test_the_search_box_keeps_what_was_typed(self):
        self.assertContains(self.search("valley"), 'value="valley"')


class SellerActiveFilterTests(SellerAdminTestCase):
    """The Active/Inactive tickboxes: active-only is the default. Mirrors
    ProductActiveFilterTests -- same `filtered` marker, same reasoning."""

    def filter(self, **params):
        return self.client.get(reverse("sellers"), {"filtered": "1", **params})

    def setUp(self):
        super().setUp()
        Seller.objects.filter(pk=self.metro.pk).update(is_active=False)

    def test_only_active_sellers_show_by_default(self):
        """No filter params at all -- the very first, plain page load."""
        response = self.client.get(reverse("sellers"))

        self.assertEqual(self.names(response), ["Green Valley Dairy"])

    def test_ticking_inactive_alongside_active_shows_both(self):
        response = self.filter(active="1", inactive="1")

        self.assertEqual(self.names(response), ["Green Valley Dairy", "Metro Wholesale"])

    def test_inactive_only_hides_active_sellers(self):
        response = self.filter(inactive="1")

        self.assertEqual(self.names(response), ["Metro Wholesale"])

    def test_unticking_both_shows_nothing(self):
        response = self.filter()

        self.assertEqual(self.names(response), [])
        self.assertContains(response, "Tick Active or Inactive")

    def test_the_tickboxes_reflect_the_current_filter(self):
        response = self.filter(inactive="1")

        self.assertNotIn(
            'name="active" value="1" checked', response.content.decode()
        )
        self.assertIn('name="inactive" value="1" checked', response.content.decode())


class NewSellerTests(SellerAdminTestCase):
    def test_it_opens_a_blank_form(self):
        response = self.client.get(reverse("new_seller"))

        self.assertTemplateUsed(response, "orders/_seller_form.html")
        self.assertContains(response, "New seller")

    def test_it_creates_a_seller(self):
        response = self.client.post(reverse("new_seller"), {
            "name": "Bertoli Coffee Roasters",
            "phone": "+30 210 555 0142",
            "email": "orders@bertoli.example",
            "notes": "Delivers Tuesdays.",
        })

        seller = Seller.objects.get(name="Bertoli Coffee Roasters")
        self.assertTrue(seller.is_active)
        self.assertEqual(seller.notes, "Delivers Tuesdays.")
        self.assertEqual(response.status_code, 200)

    def test_only_the_name_is_required(self):
        self.client.post(reverse("new_seller"), {"name": "Corner Shop"})

        self.assertTrue(Seller.objects.filter(name="Corner Shop").exists())

    def test_a_nameless_seller_is_rejected(self):
        response = self.client.post(reverse("new_seller"), {"name": ""})

        self.assertEqual(response.status_code, 422)
        self.assertEqual(Seller.objects.count(), 2)

    def test_a_duplicate_name_is_caught_regardless_of_case(self):
        """The database constraint is case-sensitive; to a shop "Metro" and
        "metro" are the same supplier.
        """
        response = self.client.post(reverse("new_seller"), {"name": "metro wholesale"})

        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "already a seller", status_code=422)
        self.assertEqual(Seller.objects.count(), 2)

    def test_success_refreshes_the_list_and_shuts_the_dialog(self):
        """The form posts from inside the dialog, so the fresh list has to be
        aimed at the page behind it and the dialog told to close.
        """
        response = self.client.post(reverse("new_seller"), {"name": "Corner Shop"})

        self.assertEqual(response.headers["HX-Retarget"], "#seller-list")
        self.assertEqual(response.headers["HX-Reswap"], "outerHTML")
        fired = json.loads(response.headers["HX-Trigger"])
        self.assertTrue(fired["closeModal"])
        self.assertIn("Corner Shop added", fired["toast"]["message"])

    def test_an_employee_cannot_add_a_seller(self):
        self.client.force_login(self.maria)

        response = self.client.post(reverse("new_seller"), {"name": "Corner Shop"})

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Seller.objects.filter(name="Corner Shop").exists())


class EditSellerTests(SellerAdminTestCase):
    def test_it_opens_prefilled(self):
        response = self.client.get(reverse("edit_seller", args=[self.dairy.pk]))

        self.assertContains(response, "Edit seller")
        self.assertContains(response, "Green Valley Dairy")
        self.assertContains(response, "+30 210 555 0198")

    def test_it_saves_changes(self):
        self.client.post(reverse("edit_seller", args=[self.dairy.pk]), {
            "name": "Green Valley Dairy Ltd",
            "phone": "+30 210 555 0000",
            "email": "hello@greenvalley.example",
            "notes": "",
        })

        self.dairy.refresh_from_db()
        self.assertEqual(self.dairy.name, "Green Valley Dairy Ltd")
        self.assertEqual(self.dairy.phone, "+30 210 555 0000")

    def test_renaming_only_the_capitalisation_is_allowed(self):
        """The case-insensitive duplicate check must not catch the seller
        being edited against itself.
        """
        response = self.client.post(reverse("edit_seller", args=[self.metro.pk]), {
            "name": "METRO WHOLESALE", "phone": "", "email": "", "notes": "",
        })

        self.assertEqual(response.status_code, 200)
        self.metro.refresh_from_db()
        self.assertEqual(self.metro.name, "METRO WHOLESALE")

    def test_taking_another_sellers_name_is_rejected(self):
        response = self.client.post(reverse("edit_seller", args=[self.metro.pk]), {
            "name": "Green Valley Dairy", "phone": "", "email": "", "notes": "",
        })

        self.assertEqual(response.status_code, 422)
        self.metro.refresh_from_db()
        self.assertEqual(self.metro.name, "Metro Wholesale")

    def test_an_unknown_seller_is_a_404(self):
        self.assertEqual(self.client.get(reverse("edit_seller", args=[999999])).status_code, 404)

    def test_an_employee_cannot_edit_a_seller(self):
        self.client.force_login(self.maria)

        response = self.client.get(reverse("edit_seller", args=[self.dairy.pk]))

        self.assertEqual(response.status_code, 403)


class ToggleSellerTests(SellerAdminTestCase):
    def toggle(self, seller, data=None):
        return self.client.post(reverse("toggle_seller", args=[seller.pk]), data or {})

    def test_deactivating_keeps_the_row(self):
        """Rule 3: sellers are never hard-deleted, because order history
        reaches them through their products.
        """
        self.toggle(self.dairy)

        self.dairy.refresh_from_db()
        self.assertFalse(self.dairy.is_active)
        self.assertTrue(Seller.objects.filter(pk=self.dairy.pk).exists())

    def test_it_toggles_back(self):
        Seller.objects.filter(pk=self.dairy.pk).update(is_active=False)

        self.toggle(self.dairy)

        self.dairy.refresh_from_db()
        self.assertTrue(self.dairy.is_active)

    def test_the_toast_says_which_way_it_went(self):
        deactivated = json.loads(self.toggle(self.dairy).headers["HX-Trigger"])
        reactivated = json.loads(self.toggle(self.dairy).headers["HX-Trigger"])

        self.assertIn("deactivated", deactivated["toast"]["message"])
        self.assertIn("reactivated", reactivated["toast"]["message"])

    def test_a_deactivated_seller_leaves_product_search(self):
        litre = Unit.objects.create(name="l", plural="l")
        Product.objects.create(name="Whole milk", seller=self.dairy, unit=litre, unit_price="1.15")

        self.toggle(self.dairy)

        from orders.search import search_products
        self.assertEqual(search_products("milk"), [])

    def test_deactivating_does_not_touch_order_history(self):
        litre = Unit.objects.create(name="l", plural="l")
        product = Product.objects.create(
            name="Whole milk", seller=self.dairy, unit=litre, unit_price="1.15"
        )
        item = OrderItem.objects.create(
            product=product, quantity="24", unit_price_snapshot="1.15", requested_by=self.maria
        )

        self.toggle(self.dairy)

        item.refresh_from_db()
        self.assertEqual(item.product.seller, self.dairy)

    def test_it_keeps_the_current_search(self):
        response = self.client.post(
            reverse("toggle_seller", args=[self.dairy.pk]),
            # Both tickboxes on: toggling flips the dairy to inactive, and the
            # default (active-only) filter would otherwise hide the very row
            # this test is checking the search kept.
            {"q": "valley", "filtered": "1", "active": "1", "inactive": "1"},
        )

        self.assertEqual([s.name for s in response.context["sellers"]], ["Green Valley Dairy"])

    def test_it_refuses_a_get(self):
        self.assertEqual(
            self.client.get(reverse("toggle_seller", args=[self.dairy.pk])).status_code, 405
        )

    def test_an_employee_cannot_deactivate_a_seller(self):
        self.client.force_login(self.maria)

        response = self.toggle(self.dairy)

        self.assertEqual(response.status_code, 403)
        self.dairy.refresh_from_db()
        self.assertTrue(self.dairy.is_active)
