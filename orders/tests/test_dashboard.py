"""The admin dashboard: who may see it, and how it groups what needs ordering."""

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from orders.models import OrderItem, Product, Seller, Unit
from orders.views import ORDER_SIGNOFF

User = get_user_model()


class DashboardTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="boss", email="boss@example.com", password="pw",
            role=User.Role.ADMIN,
        )
        cls.maria = User.objects.create_user(
            username="maria", email="maria@example.com", password="pw"
        )

        cls.dairy = Seller.objects.create(
            name="Green Valley Dairy", phone="+30 210 555 0198", email="hello@greenvalley.example"
        )
        cls.metro = Seller.objects.create(name="Metro Wholesale")

        cls.litre = Unit.objects.create(name="l", plural="l")
        cls.box = Unit.objects.create(name="box", plural="boxes")

        cls.milk = Product.objects.create(
            name="Whole milk", seller=cls.dairy, unit=cls.litre, unit_price=Decimal("1.15")
        )
        cls.oat = Product.objects.create(
            name="Oat milk", seller=cls.dairy, unit=cls.litre, unit_price=Decimal("2.40")
        )
        cls.napkins = Product.objects.create(
            name="Napkins", seller=cls.metro, unit=cls.box, unit_price=Decimal("8.75"),
            order_name="NAP-2PLY-250",
        )

    def item(self, product, quantity, urgency=OrderItem.Urgency.LOW):
        return OrderItem.objects.create(
            product=product, quantity=Decimal(quantity), urgency=urgency,
            unit_price_snapshot=product.unit_price, requested_by=self.maria,
        )

    def groups(self, response):
        return response.context["groups"]


class DashboardAccessTests(DashboardTestCase):
    def test_an_admin_can_open_it(self):
        self.client.force_login(self.admin)

        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_an_employee_is_refused_rather_than_bounced_to_login(self):
        """Sending a logged-in employee to a login form would be a lie -- no
        amount of logging in again would grant access.
        """
        self.client.force_login(self.maria)

        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 403)

    def test_a_signed_out_visitor_is_sent_to_login(self):
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_django_staff_alone_does_not_open_it(self):
        """`is_staff` opens /admin; the shop dashboard answers to `role`."""
        staffer = User.objects.create_user(
            username="dev", email="dev@example.com", password="pw", is_staff=True
        )
        self.client.force_login(staffer)

        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 403)

    def test_only_admins_are_offered_the_link(self):
        self.client.force_login(self.maria)
        self.assertNotContains(self.client.get(reverse("order_list")), reverse("dashboard"))

        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("order_list")), reverse("dashboard"))


class DashboardGroupingTests(DashboardTestCase):
    def setUp(self):
        self.client.force_login(self.admin)

    def test_it_groups_items_under_their_seller(self):
        self.item(self.milk, "24")
        self.item(self.napkins, "2")

        groups = self.groups(self.client.get(reverse("dashboard")))

        self.assertEqual([g["seller"] for g in groups], [self.dairy, self.metro])
        self.assertEqual([len(g["items"]) for g in groups], [1, 1])

    def test_sellers_are_listed_alphabetically(self):
        self.item(self.napkins, "2")
        self.item(self.milk, "24")

        groups = self.groups(self.client.get(reverse("dashboard")))

        self.assertEqual([g["seller"].name for g in groups], ["Green Valley Dairy", "Metro Wholesale"])

    def test_urgent_items_come_first_within_a_seller(self):
        self.item(self.milk, "24")
        self.item(self.oat, "12", urgency=OrderItem.Urgency.HIGH)

        groups = self.groups(self.client.get(reverse("dashboard")))

        self.assertEqual([i.product.name for i in groups[0]["items"]], ["Oat milk", "Whole milk"])

    def test_a_seller_carries_its_own_total(self):
        self.item(self.milk, "24")   # 24 * 1.15 = 27.60
        self.item(self.oat, "10")    # 10 * 2.40 = 24.00

        groups = self.groups(self.client.get(reverse("dashboard")))

        self.assertEqual(groups[0]["total"], Decimal("51.60"))

    def test_totals_use_the_frozen_price_not_the_current_one(self):
        """Otherwise a catalog price change would silently restate what the
        shop is about to spend.
        """
        self.item(self.milk, "24")
        Product.objects.filter(pk=self.milk.pk).update(unit_price=Decimal("99.00"))

        groups = self.groups(self.client.get(reverse("dashboard")))

        self.assertEqual(groups[0]["total"], Decimal("27.60"))

    def test_it_counts_urgent_items_per_seller(self):
        self.item(self.milk, "24", urgency=OrderItem.Urgency.HIGH)
        self.item(self.oat, "12")

        groups = self.groups(self.client.get(reverse("dashboard")))

        self.assertEqual(groups[0]["urgent_count"], 1)

    def test_the_summary_spans_every_seller(self):
        self.item(self.milk, "24")   # 27.60
        self.item(self.napkins, "2")  # 17.50

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.context["item_count"], 2)
        self.assertEqual(response.context["grand_total"], Decimal("45.10"))

    def test_completed_items_are_gone_from_the_dashboard(self):
        self.item(self.milk, "24")
        done = self.item(self.napkins, "2")
        OrderItem.objects.filter(pk=done.pk).update(completed_at=timezone.now())

        groups = self.groups(self.client.get(reverse("dashboard")))

        self.assertEqual([g["seller"] for g in groups], [self.dairy])

    def test_a_seller_with_nothing_open_is_not_listed_at_all(self):
        self.item(self.milk, "24")

        groups = self.groups(self.client.get(reverse("dashboard")))

        self.assertNotIn(self.metro, [g["seller"] for g in groups])

    def test_an_empty_dashboard_says_so(self):
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.context["groups"], [])
        self.assertContains(response, "Nothing to order")


class DashboardSellerFilterTests(DashboardTestCase):
    """The filter offers only sellers that have something open, so no choice
    can ever land on an empty page.
    """

    def setUp(self):
        self.client.force_login(self.admin)

    def get(self, **params):
        return self.client.get(reverse("dashboard"), params)

    def test_it_offers_only_sellers_with_open_items(self):
        self.item(self.milk, "24")   # Green Valley Dairy only

        response = self.get()

        self.assertEqual(response.context["sellers"], [self.dairy])
        self.assertContains(response, "Green Valley Dairy")

    def test_a_seller_with_nothing_open_is_not_offered(self):
        self.item(self.milk, "24")
        done = self.item(self.napkins, "2")
        OrderItem.objects.filter(pk=done.pk).update(completed_at=timezone.now())

        self.assertNotIn(self.metro, self.get().context["sellers"])

    def test_choosing_a_seller_narrows_the_page_to_it(self):
        self.item(self.milk, "24")
        self.item(self.napkins, "2")

        response = self.get(seller=self.metro.pk)

        self.assertEqual(response.context["selected_seller"], self.metro)
        self.assertEqual([g["seller"] for g in response.context["groups"]], [self.metro])
        self.assertNotContains(response, "Whole milk")

    def test_the_summary_follows_the_filter(self):
        self.item(self.milk, "24")    # 27.60, dairy
        self.item(self.napkins, "2")  # 17.50, metro

        response = self.get(seller=self.metro.pk)

        self.assertEqual(response.context["item_count"], 1)
        self.assertEqual(response.context["grand_total"], Decimal("17.50"))

    def test_the_full_option_list_survives_being_filtered(self):
        """Otherwise picking a seller would strip every other choice out of
        the dropdown, leaving no way back.
        """
        self.item(self.milk, "24")
        self.item(self.napkins, "2")

        response = self.get(seller=self.metro.pk)

        self.assertEqual(response.context["sellers"], [self.dairy, self.metro])

    def test_no_filter_shows_every_seller(self):
        self.item(self.milk, "24")
        self.item(self.napkins, "2")

        response = self.get()

        self.assertIsNone(response.context["selected_seller"])
        self.assertEqual(len(response.context["groups"]), 2)

    def test_a_blank_seller_value_means_all(self):
        """The "All sellers" option submits an empty string."""
        self.item(self.milk, "24")
        self.item(self.napkins, "2")

        response = self.get(seller="")

        self.assertIsNone(response.context["selected_seller"])
        self.assertEqual(len(response.context["groups"]), 2)

    def test_a_junk_seller_value_falls_back_to_all(self):
        self.item(self.milk, "24")

        for value in ("nonsense", "-1", "999999"):
            with self.subTest(seller=value):
                response = self.get(seller=value)

                self.assertIsNone(response.context["selected_seller"])
                self.assertEqual(len(response.context["groups"]), 1)

    def test_a_stale_link_to_a_finished_seller_shows_everything(self):
        """Their last open item was completed while the link sat in someone's
        history. Showing the whole board beats a dead end.
        """
        self.item(self.milk, "24")
        done = self.item(self.napkins, "2")
        OrderItem.objects.filter(pk=done.pk).update(completed_at=timezone.now())

        response = self.get(seller=self.metro.pk)

        self.assertIsNone(response.context["selected_seller"])
        self.assertEqual([g["seller"] for g in response.context["groups"]], [self.dairy])

    def test_the_chosen_option_comes_back_selected(self):
        self.item(self.milk, "24")
        self.item(self.napkins, "2")

        markup = self.get(seller=self.metro.pk).content.decode()

        self.assertIn(f'value="{self.metro.pk}" selected', markup)

    def test_an_htmx_request_returns_only_the_body(self):
        """The same URL serves the fragment and the full page, so ?seller=
        stays shareable and the back button keeps working.
        """
        self.item(self.milk, "24")

        response = self.client.get(
            reverse("dashboard"), {"seller": self.dairy.pk}, headers={"hx-request": "true"}
        )

        self.assertTemplateUsed(response, "orders/_dashboard_body.html")
        self.assertTemplateNotUsed(response, "orders/dashboard.html")
        self.assertNotContains(response, "<html")

    def test_a_normal_request_returns_the_whole_page(self):
        self.item(self.milk, "24")

        response = self.get()

        self.assertTemplateUsed(response, "orders/dashboard.html")
        self.assertContains(response, "<html")

    def test_the_filter_is_absent_when_nothing_is_open(self):
        response = self.get()

        self.assertNotContains(response, "seller-filter")
        self.assertContains(response, "Nothing to order")


class DashboardRowActionTests(DashboardTestCase):
    """Complete, edit and delete from a dashboard row.

    Edit and delete are shared with the employee panel, so the interesting part
    is that each screen gets its own fragment back. htmx names the element it
    is swapping in HX-Target, which is how the views tell them apart.
    """

    DASHBOARD = {"hx-request": "true", "hx-target": "dashboard-body"}

    def setUp(self):
        self.client.force_login(self.admin)

    def post(self, name, pk, data=None):
        return self.client.post(reverse(name, args=[pk]), data or {}, headers=self.DASHBOARD)

    def test_completing_an_item_records_who_and_when(self):
        item = self.item(self.milk, "24")

        response = self.post("complete_item", item.pk)

        item.refresh_from_db()
        self.assertIsNotNone(item.completed_at)
        self.assertEqual(item.completed_by, self.admin)
        self.assertEqual(response.status_code, 200)

    def test_a_completed_item_leaves_the_dashboard(self):
        item = self.item(self.milk, "24")
        self.item(self.napkins, "2")

        response = self.post("complete_item", item.pk)

        self.assertNotContains(response, "Whole milk")
        self.assertContains(response, "Napkins")

    def test_completing_confirms_with_a_toast(self):
        item = self.item(self.milk, "24")

        response = self.post("complete_item", item.pk)

        message = json.loads(response.headers["HX-Trigger"])["toast"]["message"]
        self.assertIn("Whole milk", message)

    def test_completing_twice_is_a_404_not_a_second_write(self):
        """Two taps on a slow connection must not restate completed_by."""
        item = self.item(self.milk, "24")
        self.post("complete_item", item.pk)
        item.refresh_from_db()
        first_time = item.completed_at

        response = self.post("complete_item", item.pk)

        self.assertEqual(response.status_code, 404)
        item.refresh_from_db()
        self.assertEqual(item.completed_at, first_time)

    def test_an_employee_cannot_complete_an_item(self):
        """Employees flag what is low; an admin decides it was actually bought."""
        item = self.item(self.milk, "24")
        self.client.force_login(self.maria)

        response = self.post("complete_item", item.pk)

        self.assertEqual(response.status_code, 403)
        item.refresh_from_db()
        self.assertIsNone(item.completed_at)

    def test_completing_refuses_a_get(self):
        item = self.item(self.milk, "24")

        response = self.client.get(reverse("complete_item", args=[item.pk]))

        self.assertEqual(response.status_code, 405)

    def test_the_seller_filter_survives_an_action(self):
        """Completing something while filtered must not bounce back to the
        full board -- the admin is working through one supplier.
        """
        self.item(self.milk, "24")
        self.item(self.oat, "12")
        self.item(self.napkins, "2")
        target = OrderItem.objects.get(product=self.oat)

        response = self.post("complete_item", target.pk, {"seller": self.dairy.pk})

        self.assertEqual(response.context["selected_seller"], self.dairy)
        self.assertEqual([g["seller"] for g in response.context["groups"]], [self.dairy])

    def test_deleting_from_the_dashboard_returns_the_dashboard(self):
        item = self.item(self.milk, "24")

        response = self.post("delete_item", item.pk)

        self.assertTemplateUsed(response, "orders/_dashboard_body.html")
        self.assertTemplateNotUsed(response, "orders/_panel.html")
        self.assertFalse(OrderItem.objects.filter(pk=item.pk).exists())

    def test_deleting_from_the_panel_still_returns_the_panel(self):
        """The employee screen must be untouched by the dashboard's arrival."""
        item = self.item(self.milk, "24")

        response = self.client.post(reverse("delete_item", args=[item.pk]))

        self.assertTemplateUsed(response, "orders/_panel.html")
        self.assertTemplateNotUsed(response, "orders/_dashboard_body.html")

    def test_editing_from_the_dashboard_returns_the_dashboard(self):
        item = self.item(self.milk, "24")

        response = self.post("edit_item", item.pk, {"quantity": "30", "urgent": "1"})

        self.assertTemplateUsed(response, "orders/_dashboard_body.html")
        item.refresh_from_db()
        self.assertEqual(item.quantity, Decimal("30"))
        self.assertEqual(item.urgency, OrderItem.Urgency.HIGH)

    def test_an_invalid_dashboard_edit_answers_422_on_the_dashboard(self):
        item = self.item(self.milk, "24")

        response = self.post("edit_item", item.pk, {"quantity": "-5"})

        self.assertEqual(response.status_code, 422)
        self.assertTemplateUsed(response, "orders/_dashboard_body.html")
        self.assertEqual(response.context["editing_id"], item.pk)
        item.refresh_from_db()
        self.assertEqual(item.quantity, Decimal("24"))

    def test_a_row_can_be_opened_for_editing(self):
        item = self.item(self.milk, "24")

        response = self.client.get(reverse("dashboard"), {"editing": item.pk})

        self.assertEqual(response.context["editing_id"], item.pk)
        self.assertContains(response, "Save")

    def test_every_row_offers_all_three_actions(self):
        item = self.item(self.milk, "24")

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, reverse("complete_item", args=[item.pk]))
        self.assertContains(response, reverse("delete_item", args=[item.pk]))
        self.assertContains(response, f"editing={item.pk}")


class CompleteSellerTests(DashboardTestCase):
    """Rule 4's whole-seller batch: the same write as one item, over more rows."""

    DASHBOARD = {"hx-request": "true", "hx-target": "dashboard-body"}

    def setUp(self):
        self.client.force_login(self.admin)

    def complete(self, seller, data=None):
        return self.client.post(
            reverse("complete_seller", args=[seller.pk]), data or {}, headers=self.DASHBOARD
        )

    def test_it_completes_every_open_item_for_that_seller(self):
        self.item(self.milk, "24")
        self.item(self.oat, "12")

        self.complete(self.dairy)

        self.assertEqual(OrderItem.objects.open().count(), 0)
        for item in OrderItem.objects.all():
            self.assertIsNotNone(item.completed_at)
            self.assertEqual(item.completed_by, self.admin)

    def test_it_leaves_other_sellers_alone(self):
        self.item(self.milk, "24")
        untouched = self.item(self.napkins, "2")

        self.complete(self.dairy)

        untouched.refresh_from_db()
        self.assertIsNone(untouched.completed_at)
        self.assertEqual(OrderItem.objects.open().count(), 1)

    def test_one_batch_shares_a_single_timestamp(self):
        """What makes grouping history by timestamp work later."""
        self.item(self.milk, "24")
        self.item(self.oat, "12")

        self.complete(self.dairy)

        stamps = {item.completed_at for item in OrderItem.objects.all()}
        self.assertEqual(len(stamps), 1)

    def test_the_toast_names_the_count_and_the_seller(self):
        self.item(self.milk, "24")
        self.item(self.oat, "12")

        response = self.complete(self.dairy)

        message = json.loads(response.headers["HX-Trigger"])["toast"]["message"]
        self.assertIn("2 items", message)
        self.assertIn("Green Valley Dairy", message)

    def test_a_single_item_is_not_pluralised(self):
        self.item(self.milk, "24")

        response = self.complete(self.dairy)

        message = json.loads(response.headers["HX-Trigger"])["toast"]["message"]
        self.assertIn("1 item from", message)

    def test_an_already_completed_item_keeps_its_original_timestamp(self):
        earlier = self.item(self.milk, "24")
        OrderItem.objects.filter(pk=earlier.pk).update(
            completed_at=timezone.now(), completed_by=self.maria
        )
        earlier.refresh_from_db()
        first_time, first_by = earlier.completed_at, earlier.completed_by
        self.item(self.oat, "12")

        self.complete(self.dairy)

        earlier.refresh_from_db()
        self.assertEqual(earlier.completed_at, first_time)
        self.assertEqual(earlier.completed_by, first_by)

    def test_a_second_tap_refreshes_rather_than_erroring(self):
        """htmx swallows a 404, which would leave the stale board on screen."""
        self.item(self.milk, "24")
        self.complete(self.dairy)

        response = self.complete(self.dairy)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("HX-Trigger", response.headers)

    def test_an_unknown_seller_is_a_404(self):
        response = self.complete_pk(999999)

        self.assertEqual(response.status_code, 404)

    def complete_pk(self, pk):
        return self.client.post(reverse("complete_seller", args=[pk]), headers=self.DASHBOARD)

    def test_an_employee_cannot_complete_a_seller(self):
        self.item(self.milk, "24")
        self.client.force_login(self.maria)

        response = self.complete(self.dairy)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(OrderItem.objects.open().count(), 1)

    def test_it_refuses_a_get(self):
        response = self.client.get(reverse("complete_seller", args=[self.dairy.pk]))

        self.assertEqual(response.status_code, 405)

    def test_clearing_the_filtered_seller_falls_back_to_the_whole_board(self):
        """That supplier is finished, so showing what is left beats an empty
        page filtered to a seller with nothing on it.
        """
        self.item(self.milk, "24")
        self.item(self.napkins, "2")

        response = self.complete(self.dairy, {"seller": self.dairy.pk})

        self.assertIsNone(response.context["selected_seller"])
        self.assertEqual([g["seller"] for g in response.context["groups"]], [self.metro])

    def test_clearing_one_seller_keeps_a_filter_on_another(self):
        self.item(self.milk, "24")
        self.item(self.napkins, "2")

        response = self.complete(self.metro, {"seller": self.dairy.pk})

        self.assertEqual(response.context["selected_seller"], self.dairy)

    def test_every_seller_block_offers_the_button(self):
        self.item(self.milk, "24")
        self.item(self.napkins, "2")

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, reverse("complete_seller", args=[self.dairy.pk]))
        self.assertContains(response, reverse("complete_seller", args=[self.metro.pk]))


class OrderMessageTests(DashboardTestCase):
    """The order written out for sending to the supplier."""

    def setUp(self):
        self.client.force_login(self.admin)

    def message_for(self, seller):
        response = self.client.get(reverse("dashboard"))
        group = next(g for g in response.context["groups"] if g["seller"] == seller)
        return group["message"]

    def test_it_names_the_seller_and_lists_every_item(self):
        self.item(self.milk, "24")
        self.item(self.oat, "12")

        message = self.message_for(self.dairy)

        self.assertIn("• 24 l Whole milk", message)
        self.assertIn("• 12 l Oat milk", message)

    def test_it_opens_with_a_greeting_and_closes_with_a_thank_you(self):
        self.item(self.milk, "24")

        lines = self.message_for(self.dairy).splitlines()

        self.assertIn(lines[0], ("Καλημέρα!", "Καλησπέρα!"))
        self.assertEqual(lines[-1], ORDER_SIGNOFF)

    def test_bullets_read_quantity_then_unit_then_name(self):
        self.item(self.milk, "24")
        self.item(self.oat, "12")

        lines = self.message_for(self.dairy).splitlines()[2:]

        self.assertEqual(lines[0], "• 12 l Oat milk")
        self.assertEqual(lines[1], "• 24 l Whole milk")

    def test_bullet_order_follows_the_order_shown_on_screen(self):
        """Urgent first, so the bullets match what the admin is looking at."""
        self.item(self.milk, "24")
        self.item(self.oat, "12", urgency=OrderItem.Urgency.HIGH)

        lines = self.message_for(self.dairy).splitlines()[2:]

        self.assertTrue(lines[0].startswith("• 12 l Oat milk"))
        self.assertTrue(lines[1].startswith("• 24 l Whole milk"))

    def test_a_single_item_still_gets_a_bullet(self):
        self.item(self.milk, "24")

        self.assertIn("• 24 l Whole milk", self.message_for(self.dairy))

    def test_it_covers_only_that_seller(self):
        self.item(self.milk, "24")
        self.item(self.napkins, "2")

        self.assertNotIn("Napkins", self.message_for(self.dairy))

    def test_it_uses_the_sellers_own_product_name(self):
        """The whole reason order_name exists -- the supplier reads this."""
        self.item(self.napkins, "2")

        message = self.message_for(self.metro)

        self.assertIn("• 2 boxes NAP-2PLY-250", message)
        self.assertNotIn("Napkins", message)

    def test_the_unit_pluralizes_when_more_than_one(self):
        self.item(self.napkins, "2")

        lines = self.message_for(self.metro).splitlines()[2:]

        self.assertEqual(lines[0], "• 2 boxes NAP-2PLY-250")

    def test_the_unit_stays_singular_for_exactly_one(self):
        self.item(self.napkins, "1")

        lines = self.message_for(self.metro).splitlines()[2:]

        self.assertEqual(lines[0], "• 1 box NAP-2PLY-250")

    def test_it_falls_back_to_the_shop_name(self):
        self.item(self.milk, "24")

        self.assertIn("Whole milk", self.message_for(self.dairy))

    def test_urgent_items_say_so(self):
        self.item(self.milk, "24", urgency=OrderItem.Urgency.HIGH)

        self.assertIn("sos", self.message_for(self.dairy))

    def test_ordinary_items_do_not(self):
        self.item(self.milk, "24")

        self.assertNotIn("urgent", self.message_for(self.dairy))

    def test_quantities_lose_their_trailing_zeros(self):
        """The column is DecimalField(3), so 24 arrives as 24.000."""
        self.item(self.milk, "24")
        self.item(self.oat, "1.5")

        message = self.message_for(self.dairy)

        self.assertIn("24 l", message)
        self.assertIn("1.5 l", message)
        self.assertNotIn("24.000", message)
        self.assertNotIn("1.500", message)

    def test_it_leaves_prices_out(self):
        """This says what the shop wants, not what it expects to pay."""
        self.item(self.milk, "24")

        message = self.message_for(self.dairy)

        self.assertNotIn("1.15", message)
        self.assertNotIn("27.60", message)

    def test_completed_items_are_not_reordered(self):
        self.item(self.milk, "24")
        done = self.item(self.oat, "12")
        OrderItem.objects.filter(pk=done.pk).update(completed_at=timezone.now())

        self.assertNotIn("Oat milk", self.message_for(self.dairy))

    def test_the_link_carries_the_message_url_encoded(self):
        self.item(self.milk, "24")

        response = self.client.get(reverse("dashboard"))
        url = response.context["groups"][0]["viber_forward_url"]

        self.assertTrue(url.startswith("viber://forward?text="))
        self.assertIn(quote(ORDER_SIGNOFF, safe=""), url)
        # Newlines have to be escaped or the URL ends at the first one.
        self.assertNotIn("\n", url)
        self.assertIn("%0A", url)

    def test_a_seller_without_a_number_still_gets_a_way_to_send(self):
        """Metro has no phone, so there is no chat to open -- the same button
        falls back to the picker rather than stranding that supplier. Nothing
        is copied there, since there is no chat to paste into.
        """
        self.item(self.napkins, "2")

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "viber://forward?text=")
        self.assertContains(response, "Send order")
        self.assertNotContains(response, "data-order-message=")

    def test_a_seller_without_a_number_offers_no_call_link(self):
        self.item(self.napkins, "2")

        self.assertNotContains(self.client.get(reverse("dashboard")), "tel:")

    def test_every_seller_gets_a_send_button(self):
        self.item(self.milk, "24")
        self.item(self.napkins, "2")

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.content.decode().count("Send order"), 2)

    def test_every_seller_can_send_its_order(self):
        self.item(self.milk, "24")
        self.item(self.napkins, "2")

        markup = self.client.get(reverse("dashboard")).content.decode()

        # Green Valley has a number, so copy-and-chat; Metro has none, so picker.
        self.assertIn(escape(self.dairy.viber_url), markup)
        self.assertIn("viber://forward?text=", markup)

    def local_time(self, hour, weekday=1):
        """Fake `timezone.localtime()` returning just enough to read `.hour`
        and `.weekday()` off -- the greeting looks at nothing else.
        `weekday` defaults to Tuesday, so hour-only tests don't accidentally
        land on the Monday case.
        """
        fake_now = SimpleNamespace(hour=hour, weekday=lambda: weekday)
        return patch("orders.views.timezone.localtime", return_value=fake_now)

    def test_the_greeting_is_morning_right_up_to_one_pm(self):
        self.item(self.milk, "24")

        with self.local_time(12):
            message = self.message_for(self.dairy)

        self.assertTrue(message.startswith("Καλημέρα"))

    def test_the_greeting_switches_to_afternoon_at_one_pm(self):
        self.item(self.milk, "24")

        with self.local_time(13):
            message = self.message_for(self.dairy)

        self.assertTrue(message.startswith("Καλησπέρα"))

    def test_monday_adds_a_good_week_wish(self):
        self.item(self.milk, "24")

        with self.local_time(12, weekday=0):
            message = self.message_for(self.dairy)

        self.assertTrue(message.startswith("Καλημέρα και καλή βδομάδα"))

    def test_the_week_wish_still_follows_the_time_of_day(self):
        self.item(self.milk, "24")

        with self.local_time(13, weekday=0):
            message = self.message_for(self.dairy)

        self.assertTrue(message.startswith("Καλησπέρα και καλή βδομάδα"))

    def test_other_days_get_no_week_wish(self):
        self.item(self.milk, "24")

        with self.local_time(12, weekday=1):
            message = self.message_for(self.dairy)

        self.assertEqual(message.splitlines()[0], "Καλημέρα!")


class DashboardRenderingTests(DashboardTestCase):
    def setUp(self):
        self.client.force_login(self.admin)

    def test_it_shows_the_sellers_own_name_for_a_product(self):
        """The whole reason order_name exists: the admin is about to read this
        out to the seller.
        """
        self.item(self.napkins, "2")

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "NAP-2PLY-250")

    def test_a_product_without_one_shows_no_empty_label(self):
        self.item(self.milk, "24")

        response = self.client.get(reverse("dashboard"))

        self.assertNotContains(response, "order as")

    def test_each_row_shows_the_price_per_unit(self):
        self.item(self.milk, "24")

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "&euro;1.15/l")

    def test_the_unit_price_shown_is_the_frozen_one(self):
        """The line total is quantity times this number, so showing the live
        catalog price instead would make the row's arithmetic look wrong.
        """
        self.item(self.milk, "24")
        Product.objects.filter(pk=self.milk.pk).update(unit_price=Decimal("99.00"))

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "&euro;1.15/l")
        self.assertContains(response, "&euro;27.60")
        self.assertNotContains(response, "&euro;99.00")

    def test_the_number_dials(self):
        """Tapping the number calls the seller. Sending the order is its own
        button -- the two are separate jobs.
        """
        self.item(self.milk, "24")

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "tel:+30 210 555 0198")
        self.assertContains(response, "mailto:hello@greenvalley.example")

    def test_the_send_button_copies_the_order_and_opens_the_chat(self):
        """The href is the chat, which is also what happens if the script never
        loads; the order travels by clipboard because no Viber link carries
        both a recipient and text.
        """
        self.item(self.milk, "24")

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "Send order")
        self.assertContains(response, "viber://chat?number=%2B302105550198")
        self.assertContains(response, "data-order-message=")

    def test_a_seller_with_a_number_does_not_fall_back_to_the_picker(self):
        """viber://forward would ask which chat, which is the thing the
        clipboard route exists to avoid.
        """
        self.item(self.milk, "24")

        self.assertNotContains(self.client.get(reverse("dashboard")), "viber://forward")

    def test_the_copied_text_is_the_order_itself(self):
        self.item(self.milk, "24")

        markup = self.client.get(reverse("dashboard")).content.decode()

        self.assertIn(escape(ORDER_SIGNOFF), markup)
        self.assertIn(escape("• 24 l Whole milk"), markup)

    def test_the_page_loads_the_script_that_does_the_copying(self):
        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "js/order-message.js")

    def test_the_number_is_still_readable_next_to_the_link(self):
        """The admin may need to dial it by hand if the seller is not on Viber."""
        self.item(self.milk, "24")

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "+30 210 555 0198")

    def test_a_seller_without_contact_details_renders_no_dead_links(self):
        """Metro has neither phone nor email, so the header must omit both
        rather than render an empty tel: or mailto: link.
        """
        self.item(self.napkins, "2")

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "Metro Wholesale")
        self.assertNotContains(response, "tel:")
        self.assertNotContains(response, "mailto:")

    def test_no_template_syntax_leaks_into_the_page(self):
        self.item(self.napkins, "2")

        markup = self.client.get(reverse("dashboard")).content.decode()

        for marker in ("{#", "#}", "{%", "%}"):
            self.assertNotIn(marker, markup)
