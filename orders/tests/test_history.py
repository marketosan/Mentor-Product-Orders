"""Order history: what counts as an order, the period and size filters, paging."""

import json
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from orders.models import OrderItem, Product, Seller, Unit
from orders.views import DEFAULT_HISTORY_PAGE_SIZE, HISTORY_PAGE_SIZES

User = get_user_model()


class HistoryTestCase(TestCase):
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
        cls.oat = Product.objects.create(
            name="Oat milk", seller=cls.dairy, unit=cls.litre, unit_price=Decimal("2.40")
        )
        cls.napkins = Product.objects.create(
            name="Napkins", seller=cls.metro, unit=cls.box, unit_price=Decimal("8.75")
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def completed(self, products, when=None, quantity="1"):
        """One batch: several rows sharing a single completed_at, which is what
        a whole-seller complete writes.
        """
        when = when or timezone.now()
        for product in products:
            OrderItem.objects.create(
                product=product, quantity=Decimal(quantity),
                unit_price_snapshot=product.unit_price, requested_by=self.maria,
                completed_at=when, completed_by=self.admin,
            )
        return when

    def orders(self, **params):
        return self.client.get(reverse("history"), params).context["orders"]


class HistoryAccessTests(HistoryTestCase):
    def test_an_admin_can_open_it(self):
        self.assertEqual(self.client.get(reverse("history")).status_code, 200)

    def test_an_employee_is_refused(self):
        """The spec keeps history admin-only, to stay simple for employees."""
        self.client.force_login(self.maria)

        self.assertEqual(self.client.get(reverse("history")).status_code, 403)

    def test_a_signed_out_visitor_is_sent_to_login(self):
        self.client.logout()

        response = self.client.get(reverse("history"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_it_sits_next_to_the_dashboard_in_the_nav(self):
        markup = self.client.get(reverse("order_list")).content.decode()
        nav = markup[markup.index('<nav aria-label="Main"'):markup.index("</nav>")]

        self.assertLess(nav.index("Dashboard"), nav.index("History"))
        self.assertLess(nav.index("History"), nav.index("Sellers"))


class HistoryGroupingTests(HistoryTestCase):
    def test_a_batch_is_one_order(self):
        """Completing a whole seller writes one completed_at across its rows,
        which is what makes them a single order without a batch table.
        """
        self.completed([self.milk, self.oat])

        orders = self.orders()

        self.assertEqual(len(orders), 1)
        self.assertEqual(len(orders[0]["items"]), 2)

    def test_separate_completions_are_separate_orders(self):
        self.completed([self.milk])
        self.completed([self.oat])

        self.assertEqual(len(self.orders()), 2)

    def test_open_items_never_appear(self):
        OrderItem.objects.create(
            product=self.milk, quantity=Decimal("24"),
            unit_price_snapshot=Decimal("1.15"), requested_by=self.maria,
        )

        self.assertEqual(self.orders(), [])

    def test_newest_orders_come_first(self):
        older = self.completed([self.milk], when=timezone.now() - timedelta(days=2))
        newer = self.completed([self.napkins])

        self.assertEqual([o["completed_at"] for o in self.orders()], [newer, older])

    def test_an_order_carries_its_seller_and_who_marked_it(self):
        self.completed([self.milk, self.oat])

        order = self.orders()[0]

        self.assertEqual(order["seller"], self.dairy)
        self.assertEqual(order["completed_by"], self.admin)

    def test_an_order_totals_the_frozen_prices(self):
        self.completed([self.milk], quantity="24")   # 24 * 1.15

        self.assertEqual(self.orders()[0]["total"], Decimal("27.60"))

    def test_a_later_price_change_does_not_rewrite_history(self):
        """Rule 2 exists for exactly this screen."""
        self.completed([self.milk], quantity="24")
        Product.objects.filter(pk=self.milk.pk).update(unit_price=Decimal("99.00"))

        self.assertEqual(self.orders()[0]["total"], Decimal("27.60"))

    def test_an_empty_history_says_so(self):
        response = self.client.get(reverse("history"))

        self.assertEqual(response.context["orders"], [])
        self.assertContains(response, "Nothing ordered yet")


class HistoryPeriodTests(HistoryTestCase):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.today = self.completed([self.milk], when=now - timedelta(hours=2))
        self.this_week = self.completed([self.oat], when=now - timedelta(days=3))
        self.this_month = self.completed([self.napkins], when=now - timedelta(days=20))
        self.ancient = self.completed([self.milk], when=now - timedelta(days=200))

    def stamps(self, period):
        return [o["completed_at"] for o in self.orders(period=period)]

    def test_the_last_day(self):
        self.assertEqual(self.stamps("day"), [self.today])

    def test_the_last_week(self):
        self.assertEqual(self.stamps("week"), [self.today, self.this_week])

    def test_the_last_month(self):
        self.assertEqual(self.stamps("month"), [self.today, self.this_week, self.this_month])

    def test_all_time_is_the_default(self):
        response = self.client.get(reverse("history"))

        self.assertEqual(response.context["period"], "")
        self.assertEqual(len(response.context["orders"]), 4)

    def test_an_unknown_period_falls_back_to_all_time(self):
        response = self.client.get(reverse("history"), {"period": "decade"})

        self.assertEqual(response.context["period"], "")
        self.assertEqual(len(response.context["orders"]), 4)

    def test_a_period_with_nothing_in_it_explains_itself(self):
        OrderItem.objects.all().delete()
        self.completed([self.milk], when=timezone.now() - timedelta(days=200))

        response = self.client.get(reverse("history"), {"period": "day"})

        self.assertEqual(response.context["orders"], [])
        self.assertContains(response, "Try a wider one")


class HistoryPagingTests(HistoryTestCase):
    def make_orders(self, count):
        now = timezone.now()
        for n in range(count):
            self.completed([self.milk], when=now - timedelta(minutes=n))

    def test_it_shows_twenty_orders_by_default(self):
        self.make_orders(25)

        response = self.client.get(reverse("history"))

        self.assertEqual(response.context["page_size"], DEFAULT_HISTORY_PAGE_SIZE)
        self.assertEqual(len(response.context["orders"]), 20)
        self.assertEqual(response.context["paginator"].num_pages, 2)

    def test_the_page_size_can_be_changed(self):
        self.make_orders(25)

        for size in HISTORY_PAGE_SIZES:
            with self.subTest(size=size):
                response = self.client.get(reverse("history"), {"size": size})

                self.assertEqual(len(response.context["orders"]), min(size, 25))

    def test_an_unoffered_size_falls_back_to_the_default(self):
        """Otherwise ?size=100000 would be a way to load the whole table."""
        self.make_orders(25)

        for size in ("1000", "0", "-5", "twenty"):
            with self.subTest(size=size):
                response = self.client.get(reverse("history"), {"size": size})

                self.assertEqual(response.context["page_size"], DEFAULT_HISTORY_PAGE_SIZE)

    def test_paging_counts_orders_not_items(self):
        """A page is twenty orders. Twenty-five items in five batches is one
        page, not two.
        """
        now = timezone.now()
        for n in range(5):
            self.completed([self.milk, self.oat, self.napkins], when=now - timedelta(minutes=n))

        response = self.client.get(reverse("history"))

        self.assertEqual(response.context["paginator"].count, 5)
        self.assertEqual(response.context["paginator"].num_pages, 1)
        self.assertEqual(sum(len(o["items"]) for o in response.context["orders"]), 15)

    def test_the_second_page_continues_where_the_first_stopped(self):
        self.make_orders(25)

        first = self.orders(size=10, page=1)
        second = self.orders(size=10, page=2)

        self.assertEqual(len(second), 10)
        self.assertTrue(second[0]["completed_at"] < first[-1]["completed_at"])

    def test_pages_do_not_overlap(self):
        self.make_orders(25)

        seen = []
        for number in (1, 2, 3):
            seen += [o["completed_at"] for o in self.orders(size=10, page=number)]

        self.assertEqual(len(seen), 25)
        self.assertEqual(len(set(seen)), 25)

    def test_a_junk_page_number_lands_on_the_first(self):
        self.make_orders(25)

        self.assertEqual(self.client.get(
            reverse("history"), {"page": "nonsense"}
        ).context["page"].number, 1)

    def test_a_page_past_the_end_lands_on_the_last(self):
        """What a stale bookmark deserves, rather than a 404."""
        self.make_orders(25)

        response = self.client.get(reverse("history"), {"page": "99"})

        self.assertEqual(response.context["page"].number, 2)

    def test_the_filters_travel_in_the_pager_links(self):
        """Otherwise paging would quietly widen the window being looked at."""
        self.make_orders(25)

        response = self.client.get(reverse("history"), {"period": "month", "size": 10})

        self.assertContains(response, "period=month&amp;size=10&amp;page=2")

    def test_the_pager_is_hidden_when_everything_fits(self):
        self.make_orders(3)

        self.assertNotContains(self.client.get(reverse("history")), "History pages")

    def test_paging_returns_only_the_body_fragment(self):
        self.make_orders(25)

        response = self.client.get(
            reverse("history"), {"page": 2}, headers={"hx-request": "true"}
        )

        self.assertTemplateUsed(response, "orders/_history_body.html")
        self.assertTemplateNotUsed(response, "orders/history.html")
        self.assertNotContains(response, "<html")


class HistoryScaleTests(HistoryTestCase):
    """This is the one table expected to grow without limit, so the cost of a
    page must not grow with it.
    """

    def make_orders(self, count, items_each=1):
        now = timezone.now()
        products = [self.milk, self.oat, self.napkins][:items_each]
        for n in range(count):
            self.completed(products, when=now - timedelta(minutes=n))

    def queries_for_a_page(self, order_count):
        self.make_orders(order_count)
        with CaptureQueriesContext(connection) as captured:
            self.client.get(reverse("history"))
        return len(captured)

    def test_a_page_costs_the_same_whether_history_is_small_or_large(self):
        """The obvious implementation -- fetch every completed row and group it
        in Python -- would read the whole table on every page view.
        """
        small = self.queries_for_a_page(5)
        OrderItem.objects.all().delete()
        large = self.queries_for_a_page(150)

        # Guards the guard: if capture ever stopped recording, 0 == 0 would
        # make this pass no matter how badly the view behaved.
        self.assertGreater(small, 0)
        self.assertEqual(small, large)

    def test_only_the_current_pages_rows_are_loaded(self):
        self.make_orders(150)

        response = self.client.get(reverse("history"))

        self.assertEqual(response.context["paginator"].count, 150)
        self.assertEqual(len(response.context["orders"]), 20)

    def test_a_deep_page_still_works(self):
        self.make_orders(150)

        response = self.client.get(reverse("history"), {"page": 8})

        self.assertEqual(response.context["page"].number, 8)
        self.assertEqual(len(response.context["orders"]), 10)

    def test_the_last_page_holds_the_remainder(self):
        self.make_orders(150)

        response = self.client.get(reverse("history"), {"size": 50, "page": 3})

        self.assertEqual(response.context["paginator"].num_pages, 3)
        self.assertEqual(len(response.context["orders"]), 50)


class UncompleteItemTests(HistoryTestCase):
    """Rule 4's undo: putting a completed item back on the list."""

    def undo(self, item, **params):
        url = reverse("uncomplete_item", args=[item.pk])
        return self.client.post(f"{url}?{urlencode(params)}" if params else url)

    def completed_item(self, product=None, when=None):
        self.completed([product or self.milk], when=when)
        return OrderItem.objects.completed().latest("completed_at")

    def test_it_clears_the_completion(self):
        item = self.completed_item()

        self.undo(item)

        item.refresh_from_db()
        self.assertIsNone(item.completed_at)
        self.assertIsNone(item.completed_by)

    def test_the_item_returns_to_the_open_list(self):
        item = self.completed_item()

        self.undo(item)

        self.assertIn(item, OrderItem.objects.open())

    def test_it_leaves_the_history_page(self):
        item = self.completed_item()

        response = self.undo(item)

        self.assertEqual(response.context["orders"], [])

    def test_it_confirms_what_happened(self):
        item = self.completed_item()

        response = self.undo(item)

        message = json.loads(response.headers["HX-Trigger"])["toast"]["message"]
        self.assertIn("Whole milk moved back to the list", message)

    def test_the_rest_of_the_batch_stays_completed(self):
        """Undo is per item, so correcting one line does not undo the order."""
        self.completed([self.milk, self.oat])
        item = OrderItem.objects.completed().get(product=self.milk)

        self.undo(item)

        self.assertEqual(OrderItem.objects.completed().count(), 1)
        self.assertEqual(OrderItem.objects.open().count(), 1)

    def test_it_is_refused_when_the_product_is_already_on_the_list(self):
        """Rule 1 -- the shop never lists the same product twice, and what the
        admin wanted is already true.
        """
        item = self.completed_item()
        OrderItem.objects.create(
            product=self.milk, quantity=Decimal("5"),
            unit_price_snapshot=Decimal("1.15"), requested_by=self.maria,
        )

        response = self.undo(item)

        item.refresh_from_db()
        self.assertIsNotNone(item.completed_at)
        message = json.loads(response.headers["HX-Trigger"])["toast"]["message"]
        self.assertIn("already on the list", message)

    def test_a_different_product_being_open_is_no_obstacle(self):
        item = self.completed_item()
        OrderItem.objects.create(
            product=self.oat, quantity=Decimal("5"),
            unit_price_snapshot=Decimal("2.40"), requested_by=self.maria,
        )

        self.undo(item)

        item.refresh_from_db()
        self.assertIsNone(item.completed_at)

    def test_an_open_item_cannot_be_uncompleted(self):
        open_item = OrderItem.objects.create(
            product=self.milk, quantity=Decimal("5"),
            unit_price_snapshot=Decimal("1.15"), requested_by=self.maria,
        )

        self.assertEqual(self.undo(open_item).status_code, 404)

    def test_an_employee_cannot_undo(self):
        item = self.completed_item()
        self.client.force_login(self.maria)

        response = self.undo(item)

        self.assertEqual(response.status_code, 403)
        item.refresh_from_db()
        self.assertIsNotNone(item.completed_at)

    def test_it_refuses_a_get(self):
        item = self.completed_item()

        response = self.client.get(reverse("uncomplete_item", args=[item.pk]))

        self.assertEqual(response.status_code, 405)

    def test_the_filters_and_page_survive_the_undo(self):
        """Otherwise correcting one line would throw the admin back to page 1
        of everything, mid-task.
        """
        now = timezone.now()
        for n in range(30):
            self.completed([self.napkins], when=now - timedelta(minutes=n))
        target = OrderItem.objects.completed().order_by("completed_at").first()

        response = self.undo(target, period="month", size=10, page=3)

        self.assertEqual(response.context["period"], "month")
        self.assertEqual(response.context["page_size"], 10)
        self.assertEqual(response.context["page"].number, 3)

    def test_the_button_says_what_it_does(self):
        """An arrow icon alone does not say whether it reverses the order or
        the page, so the control is spelled out and confirmed.
        """
        self.completed([self.milk])

        response = self.client.get(reverse("history"))

        self.assertContains(response, "Mark as not ordered")
        self.assertContains(response, "hx-confirm")
        self.assertContains(response, "Mark Whole milk as not ordered?")

    def test_it_can_be_completed_again_afterwards(self):
        item = self.completed_item()
        self.undo(item)

        self.client.post(reverse("complete_item", args=[item.pk]))

        item.refresh_from_db()
        self.assertIsNotNone(item.completed_at)
        self.assertEqual(item.completed_by, self.admin)

    def test_every_history_row_offers_it(self):
        self.completed([self.milk, self.oat])

        response = self.client.get(reverse("history"))

        for item in OrderItem.objects.completed():
            with self.subTest(item=item.product.name):
                self.assertContains(response, reverse("uncomplete_item", args=[item.pk]))


class HistoryRenderingTests(HistoryTestCase):
    def test_it_shows_the_order_name_where_there_is_one(self):
        Product.objects.filter(pk=self.napkins.pk).update(order_name="NAP-2PLY-250")
        self.completed([self.napkins])

        self.assertContains(self.client.get(reverse("history")), "NAP-2PLY-250")

    def test_it_credits_whoever_asked_for_each_item(self):
        self.completed([self.milk])

        self.assertContains(self.client.get(reverse("history")), "requested by maria")

    def test_no_template_syntax_leaks_into_the_page(self):
        self.completed([self.milk])

        markup = self.client.get(reverse("history")).content.decode()

        for marker in ("{#", "#}", "{%", "%}"):
            self.assertNotIn(marker, markup)
