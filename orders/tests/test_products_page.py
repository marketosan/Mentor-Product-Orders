"""The catalog page: searching it, and editing from it."""

import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from orders.models import OrderItem, Product, Seller, Unit

User = get_user_model()


class ProductsPageTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="boss", email="boss@example.com", password="pw", role=User.Role.ADMIN
        )
        cls.maria = User.objects.create_user(
            username="maria", email="maria@example.com", password="pw"
        )
        cls.dairy = Seller.objects.create(name="Green Valley Dairy")
        cls.metro = Seller.objects.create(name="Metro Wholesale")
        cls.litre = Unit.objects.create(name="l", plural="l")
        cls.box = Unit.objects.create(name="box", plural="boxes")

        cls.milk = Product.objects.create(
            name="Whole milk", seller=cls.dairy, unit=cls.litre, unit_price=Decimal("1.15")
        )
        cls.napkins = Product.objects.create(
            name="Napkins", seller=cls.metro, unit=cls.box, unit_price=Decimal("8.75"),
            order_name="NAP-2PLY-250",
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def names(self, response):
        return [p.name for p in response.context["products"]]


class ProductsPageAccessTests(ProductsPageTestCase):
    def test_an_admin_can_open_it(self):
        self.assertEqual(self.client.get(reverse("products")).status_code, 200)

    def test_an_employee_is_refused(self):
        self.client.force_login(self.maria)

        self.assertEqual(self.client.get(reverse("products")).status_code, 403)

    def test_a_signed_out_visitor_is_sent_to_login(self):
        self.client.logout()

        response = self.client.get(reverse("products"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def nav(self):
        """Just the header nav.

        The whole page is no good for these: "/products/" is a prefix of
        /products/search/ and /products/new/, and "Products" also appears in
        the page title and heading.
        """
        markup = self.client.get(reverse("order_list")).content.decode()
        start = markup.index('<nav aria-label="Main"')
        return markup[start:markup.index("</nav>", start)]

    def test_the_nav_offers_it_to_admins_only(self):
        self.assertIn(f'href="{reverse("products")}"', self.nav())

        self.client.force_login(self.maria)
        self.assertNotIn(f'href="{reverse("products")}"', self.nav())

    def test_it_sits_between_sellers_and_users_in_the_nav(self):
        nav = self.nav()

        self.assertLess(nav.index("Sellers"), nav.index("Products"))
        self.assertLess(nav.index("Products"), nav.index("Users"))


class ProductSearchPageTests(ProductsPageTestCase):
    def search(self, q):
        return self.client.get(reverse("products"), {"q": q})

    def test_it_lists_the_whole_catalog_by_default(self):
        self.assertEqual(self.names(self.search("")), ["Napkins", "Whole milk"])

    def test_it_matches_part_of_a_name(self):
        self.assertEqual(self.names(self.search("milk")), ["Whole milk"])

    def test_matching_ignores_case(self):
        self.assertEqual(self.names(self.search("NAPK")), ["Napkins"])

    def test_it_matches_the_sellers_own_order_name(self):
        """Searching by the supplier's code is exactly why order_name exists."""
        self.assertEqual(self.names(self.search("NAP-2PLY")), ["Napkins"])

    def test_it_matches_the_seller(self):
        self.assertEqual(self.names(self.search("Metro")), ["Napkins"])

    def test_matching_is_predictable_rather_than_fuzzy(self):
        """Unlike the quick-add box, which forgives typos to help someone
        half-remember a product mid-order.
        """
        self.assertEqual(self.names(self.search("mikl")), [])

    def test_inactive_products_can_still_be_found(self):
        """Hidden from ordering by the default filter, but findable here with
        the Inactive tickbox on -- this is where they are managed."""
        Product.objects.filter(pk=self.milk.pk).update(is_active=False)

        response = self.client.get(
            reverse("products"),
            {"q": "milk", "filtered": "1", "active": "1", "inactive": "1"},
        )

        self.assertEqual(self.names(response), ["Whole milk"])
        self.assertContains(response, "inactive")

    def test_a_miss_says_so_and_names_the_query(self):
        response = self.search("nothing")

        self.assertEqual(self.names(response), [])
        self.assertContains(response, "No product matches")
        self.assertContains(response, "nothing")

    def test_searching_returns_only_the_list_fragment(self):
        response = self.client.get(
            reverse("products"), {"q": "milk"}, headers={"hx-request": "true"}
        )

        self.assertTemplateUsed(response, "orders/_product_list.html")
        self.assertTemplateNotUsed(response, "orders/products.html")
        self.assertNotContains(response, "<html")

    def test_the_search_box_keeps_what_was_typed(self):
        self.assertContains(self.search("milk"), 'value="milk"')


class ProductActiveFilterTests(ProductsPageTestCase):
    """The Active/Inactive tickboxes: active-only is the default, and a
    hidden `filtered` marker (always present once the tickboxes are on the
    page) is what tells "both unticked, on purpose" apart from "the filter
    UI was never submitted at all", since an unticked checkbox otherwise
    vanishes from the request just like any HTML form."""

    def filter(self, **params):
        return self.client.get(reverse("products"), {"filtered": "1", **params})

    def setUp(self):
        super().setUp()
        Product.objects.filter(pk=self.milk.pk).update(is_active=False)

    def test_only_active_products_show_by_default(self):
        """No filter params at all -- the very first, plain page load."""
        response = self.client.get(reverse("products"))

        self.assertEqual(self.names(response), ["Napkins"])

    def test_ticking_inactive_alongside_active_shows_both(self):
        response = self.filter(active="1", inactive="1")

        self.assertEqual(self.names(response), ["Napkins", "Whole milk"])

    def test_inactive_only_hides_active_products(self):
        response = self.filter(inactive="1")

        self.assertEqual(self.names(response), ["Whole milk"])

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


class ProductsPageRenderingTests(ProductsPageTestCase):
    def test_it_shows_the_price_the_seller_and_the_order_name(self):
        response = self.client.get(reverse("products"))

        self.assertContains(response, "&euro;8.75/box")
        self.assertContains(response, "Metro Wholesale")
        self.assertContains(response, "NAP-2PLY-250")

    def test_it_flags_products_currently_on_the_order_list(self):
        OrderItem.objects.create(
            product=self.milk, quantity=Decimal("24"),
            unit_price_snapshot=Decimal("1.15"), requested_by=self.maria,
        )

        response = self.client.get(reverse("products"))

        self.assertContains(response, "on the list")

    def test_a_completed_item_does_not_count_as_on_the_list(self):
        from django.utils import timezone

        OrderItem.objects.create(
            product=self.milk, quantity=Decimal("24"),
            unit_price_snapshot=Decimal("1.15"), requested_by=self.maria,
            completed_at=timezone.now(),
        )

        self.assertNotContains(self.client.get(reverse("products")), "on the list")

    def test_every_row_offers_an_edit_button(self):
        response = self.client.get(reverse("products"))

        for product in (self.milk, self.napkins):
            with self.subTest(product=product.name):
                self.assertContains(
                    response, f"{reverse('edit_product', args=[product.pk])}?origin=products"
                )

    def test_it_has_a_dialog_to_edit_into(self):
        response = self.client.get(reverse("products"))

        self.assertContains(response, 'id="modal"')
        self.assertContains(response, 'id="modal-body"')

    def test_no_template_syntax_leaks_into_the_page(self):
        markup = self.client.get(reverse("products")).content.decode()

        for marker in ("{#", "#}", "{%", "%}"):
            self.assertNotIn(marker, markup)


class AddFromProductsPageTests(ProductsPageTestCase):
    """Creating a product here, rather than mid-order from the order list.

    Same form, different landing: there is no quick-add form on this page to
    hand the new product back to, so success just refreshes the list.
    """

    def create(self, **overrides):
        data = {
            "name": "Cinnamon syrup", "order_name": "", "seller": self.dairy.pk,
            "unit": self.litre.pk, "unit_price": "6.50", "origin": "products",
        }
        data.update(overrides)
        return self.client.post(reverse("new_product"), data)

    def test_the_page_offers_an_add_button(self):
        response = self.client.get(reverse("products"))

        self.assertContains(response, f"{reverse('new_product')}?origin=products")
        self.assertContains(response, "Add product")

    def test_it_creates_the_product_and_credits_the_author(self):
        self.create()

        product = Product.objects.get(name="Cinnamon syrup")
        self.assertEqual(product.created_by, self.admin)
        self.assertEqual(product.seller, self.dairy)

    def test_success_refreshes_the_product_list_not_the_order_panel(self):
        """The order list's success path calls selectProduct(), which only
        exists on that page -- running it here would throw.
        """
        response = self.create()

        self.assertTemplateUsed(response, "orders/_product_list.html")
        self.assertEqual(response.headers["HX-Retarget"], "#product-list")
        self.assertNotContains(response, "selectProduct(")

    def test_success_shuts_the_dialog_and_confirms(self):
        response = self.create()

        fired = json.loads(response.headers["HX-Trigger"])
        self.assertTrue(fired["closeModal"])
        self.assertIn("Cinnamon syrup added to the catalog", fired["toast"]["message"])

    def test_adding_from_the_order_list_still_returns_to_the_quick_add_form(self):
        """The other origin must keep working -- that flow interrupts an order
        being typed and has to resume it.
        """
        response = self.client.post(reverse("new_product"), {
            "name": "Cardamom", "order_name": "", "seller": self.dairy.pk,
            "unit": self.litre.pk, "unit_price": "9.00",
        })

        self.assertContains(response, "selectProduct(")
        self.assertNotIn("HX-Retarget", response.headers)

    def test_a_price_is_not_required(self):
        self.create(unit_price="")

        self.assertIsNone(Product.objects.get(name="Cinnamon syrup").unit_price)

    def test_the_search_prefills_the_name(self):
        """Searching for something missing and then adding it is how you get
        here.
        """
        response = self.client.get(reverse("new_product"), {"origin": "products", "q": "Cardamom"})

        self.assertEqual(response.context["form"].initial["name"], "Cardamom")

    def test_the_search_survives_the_add(self):
        response = self.create(name="Oat milk", q="milk")

        self.assertEqual(
            sorted(p.name for p in response.context["products"]),
            ["Oat milk", "Whole milk"],
        )

    def test_a_rejected_add_keeps_the_products_origin(self):
        response = self.create(unit_price="0")

        self.assertEqual(response.status_code, 422)
        self.assertContains(response, 'value="products"', status_code=422)
        self.assertFalse(Product.objects.filter(name="Cinnamon syrup").exists())

    def test_a_duplicate_name_is_still_caught(self):
        response = self.create(name="whole milk")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(Product.objects.filter(name__iexact="whole milk").count(), 1)

    def test_an_employee_cannot_reach_the_products_page_to_add_from_it(self):
        """The page is admin-only, though new_product itself stays open to
        employees -- they add products mid-order from the order list.
        """
        self.client.force_login(self.maria)

        self.assertEqual(self.client.get(reverse("products")).status_code, 403)


class EditFromProductsPageTests(ProductsPageTestCase):
    def edit(self, product, **overrides):
        data = {
            "name": product.name, "order_name": product.order_name,
            "seller": product.seller_id, "unit": product.unit_id,
            "unit_price": product.unit_price, "origin": "products",
        }
        data.update(overrides)
        return self.client.post(reverse("edit_product", args=[product.pk]), data)

    def test_saving_refreshes_the_product_list(self):
        response = self.edit(self.milk, unit_price="1.40")

        self.assertTemplateUsed(response, "orders/_product_list.html")
        self.assertEqual(response.headers["HX-Retarget"], "#product-list")
        self.milk.refresh_from_db()
        self.assertEqual(self.milk.unit_price, Decimal("1.40"))

    def test_the_search_survives_a_save(self):
        """Otherwise correcting one product would throw the admin back to the
        whole catalog mid-task.
        """
        response = self.edit(self.milk, q="milk", unit_price="1.40")

        self.assertEqual([p.name for p in response.context["products"]], ["Whole milk"])

    def test_the_form_carries_the_search_so_it_can_survive(self):
        response = self.client.get(
            reverse("edit_product", args=[self.milk.pk]), {"origin": "products", "q": "milk"}
        )

        self.assertContains(response, 'name="q"')
        self.assertContains(response, 'value="milk"')

    def test_order_name_is_editable_here(self):
        self.edit(self.milk, order_name="MILK-1L")

        self.milk.refresh_from_db()
        self.assertEqual(self.milk.order_name, "MILK-1L")

    def test_a_rejected_save_keeps_the_products_origin(self):
        response = self.edit(self.milk, unit_price="0")

        self.assertEqual(response.status_code, 422)
        self.assertContains(response, 'value="products"', status_code=422)
