"""The user admin page: search, add, edit, deactivate, and the two rules that
stop an admin locking the shop out of its own app.
"""

import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class UserAdminTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boss = User.objects.create_user(
            username="boss", email="boss@example.com", password="pw", role=User.Role.ADMIN
        )
        cls.second_admin = User.objects.create_user(
            username="nikos", email="nikos@example.com", password="pw", role=User.Role.ADMIN
        )
        cls.maria = User.objects.create_user(
            username="maria", email="maria@example.com", password="pw"
        )

    def setUp(self):
        self.client.force_login(self.boss)

    def usernames(self, response):
        return [u.username for u in response.context["users"]]


class AccessTests(UserAdminTestCase):
    def test_an_admin_can_open_it(self):
        self.assertEqual(self.client.get(reverse("users")).status_code, 200)

    def test_an_employee_is_refused(self):
        self.client.force_login(self.maria)

        self.assertEqual(self.client.get(reverse("users")).status_code, 403)

    def test_a_signed_out_visitor_is_sent_to_login(self):
        self.client.logout()

        response = self.client.get(reverse("users"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_an_employee_cannot_reach_any_of_the_actions(self):
        self.client.force_login(self.maria)

        for name, args in [
            ("new_user", []), ("edit_user", [self.boss.pk]), ("toggle_user", [self.boss.pk]),
        ]:
            with self.subTest(view=name):
                url = reverse(name, args=args)
                method = self.client.post if name == "toggle_user" else self.client.get

                self.assertEqual(method(url).status_code, 403)

    def test_the_nav_offers_it_to_admins_only(self):
        self.assertContains(self.client.get(reverse("order_list")), reverse("users"))

        self.client.force_login(self.maria)
        self.assertNotContains(self.client.get(reverse("order_list")), reverse("users"))


class UserSearchTests(UserAdminTestCase):
    def search(self, q):
        return self.client.get(reverse("users"), {"q": q})

    def test_it_matches_part_of_a_username(self):
        self.assertEqual(self.usernames(self.search("mar")), ["maria"])

    def test_it_matches_an_email(self):
        self.assertEqual(self.usernames(self.search("nikos@")), ["nikos"])

    def test_a_blank_search_lists_everyone(self):
        self.assertEqual(self.usernames(self.search("  ")), ["boss", "maria", "nikos"])

    def test_a_miss_says_so(self):
        response = self.search("nobody")

        self.assertEqual(self.usernames(response), [])
        self.assertContains(response, "No user matches")

    def test_searching_returns_only_the_list_fragment(self):
        response = self.client.get(reverse("users"), {"q": "mar"}, headers={"hx-request": "true"})

        self.assertTemplateUsed(response, "accounts/_user_list.html")
        self.assertNotContains(response, "<html")


class NewUserTests(UserAdminTestCase):
    def create(self, **overrides):
        data = {
            "username": "eleni", "email": "eleni@example.com", "role": User.Role.EMPLOYEE,
            "password1": "shopfloor-2026", "password2": "shopfloor-2026",
        }
        data.update(overrides)
        return self.client.post(reverse("new_user"), data)

    def test_it_creates_a_working_account(self):
        self.create()

        created = User.objects.get(username="eleni")
        self.assertTrue(created.is_active)
        self.assertEqual(created.role, User.Role.EMPLOYEE)
        self.assertTrue(created.check_password("shopfloor-2026"))

    def test_the_new_account_can_actually_log_in(self):
        """The one thing a hashing mistake would silently break."""
        self.create()
        self.client.logout()

        self.assertTrue(self.client.login(username="eleni", password="shopfloor-2026"))

    def test_the_password_is_never_stored_as_typed(self):
        self.create()

        self.assertNotEqual(User.objects.get(username="eleni").password, "shopfloor-2026")

    def test_mismatched_passwords_are_rejected(self):
        response = self.create(password2="something-else")

        self.assertEqual(response.status_code, 422)
        self.assertFalse(User.objects.filter(username="eleni").exists())

    def test_a_weak_password_is_rejected(self):
        """settings already configures Django's validators; this checks they
        are actually reached.
        """
        response = self.create(password1="123", password2="123")

        self.assertEqual(response.status_code, 422)
        self.assertFalse(User.objects.filter(username="eleni").exists())

    def test_a_missing_password_is_rejected(self):
        response = self.create(password1="", password2="")

        self.assertEqual(response.status_code, 422)
        self.assertFalse(User.objects.filter(username="eleni").exists())

    def test_a_duplicate_email_is_caught_regardless_of_case(self):
        response = self.create(email="MARIA@example.com")

        self.assertEqual(response.status_code, 422)
        self.assertFalse(User.objects.filter(username="eleni").exists())

    def test_a_duplicate_username_is_rejected(self):
        response = self.create(username="maria", email="other@example.com")

        self.assertEqual(response.status_code, 422)

    def test_an_admin_can_be_created(self):
        self.create(username="olga", email="olga@example.com", role=User.Role.ADMIN)

        self.assertTrue(User.objects.get(username="olga").is_shop_admin)

    def test_success_refreshes_the_list_and_shuts_the_dialog(self):
        response = self.create()

        self.assertEqual(response.headers["HX-Retarget"], "#user-list")
        fired = json.loads(response.headers["HX-Trigger"])
        self.assertTrue(fired["closeModal"])
        self.assertIn("eleni added", fired["toast"]["message"])


class EditUserTests(UserAdminTestCase):
    def edit(self, account, **overrides):
        data = {
            "username": account.username, "email": account.email, "role": account.role,
            "password1": "", "password2": "",
        }
        data.update(overrides)
        return self.client.post(reverse("edit_user", args=[account.pk]), data)

    def test_it_opens_prefilled(self):
        response = self.client.get(reverse("edit_user", args=[self.maria.pk]))

        self.assertContains(response, "maria")
        self.assertContains(response, "maria@example.com")

    def test_it_saves_changes(self):
        self.edit(self.maria, username="maria-k", email="maria.k@example.com")

        self.maria.refresh_from_db()
        self.assertEqual(self.maria.username, "maria-k")
        self.assertEqual(self.maria.email, "maria.k@example.com")

    def test_a_blank_password_leaves_the_old_one_working(self):
        """Editing an email must not silently lock somebody out."""
        self.edit(self.maria, email="new@example.com")

        self.maria.refresh_from_db()
        self.assertTrue(self.maria.check_password("pw"))

    def test_a_filled_password_replaces_it(self):
        self.edit(self.maria, password1="brand-new-secret", password2="brand-new-secret")

        self.maria.refresh_from_db()
        self.assertTrue(self.maria.check_password("brand-new-secret"))

    def test_a_weak_replacement_password_is_rejected(self):
        response = self.edit(self.maria, password1="123", password2="123")

        self.assertEqual(response.status_code, 422)
        self.maria.refresh_from_db()
        self.assertTrue(self.maria.check_password("pw"))

    def test_an_employee_can_be_promoted(self):
        self.edit(self.maria, role=User.Role.ADMIN)

        self.maria.refresh_from_db()
        self.assertTrue(self.maria.is_shop_admin)

    def test_another_admin_can_be_demoted_while_others_remain(self):
        self.edit(self.second_admin, role=User.Role.EMPLOYEE)

        self.second_admin.refresh_from_db()
        self.assertFalse(self.second_admin.is_shop_admin)

    def test_you_cannot_demote_yourself(self):
        """Nothing else can grant the role back, so this would be a one-way
        door out of the admin pages.
        """
        response = self.edit(self.boss, role=User.Role.EMPLOYEE)

        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "your own admin role", status_code=422)
        self.boss.refresh_from_db()
        self.assertTrue(self.boss.is_shop_admin)

    def test_the_last_admin_cannot_be_demoted(self):
        User.objects.filter(pk=self.boss.pk).update(role=User.Role.EMPLOYEE)
        self.client.force_login(self.second_admin)

        response = self.edit(self.second_admin, role=User.Role.EMPLOYEE)

        self.assertEqual(response.status_code, 422)
        self.second_admin.refresh_from_db()
        self.assertTrue(self.second_admin.is_shop_admin)

    def test_a_renamed_account_keeps_its_own_email(self):
        """The case-insensitive email check must not catch the account being
        edited against itself.
        """
        response = self.edit(self.maria, email="MARIA@example.com")

        self.assertEqual(response.status_code, 200)

    def test_an_unknown_user_is_a_404(self):
        self.assertEqual(self.client.get(reverse("edit_user", args=[999999])).status_code, 404)


class ToggleUserTests(UserAdminTestCase):
    def toggle(self, account, data=None):
        return self.client.post(reverse("toggle_user", args=[account.pk]), data or {})

    def test_deactivating_keeps_the_row(self):
        self.toggle(self.maria)

        self.maria.refresh_from_db()
        self.assertFalse(self.maria.is_active)
        self.assertTrue(User.objects.filter(pk=self.maria.pk).exists())

    def test_a_deactivated_user_cannot_log_in(self):
        """What "remove this person" actually has to mean."""
        self.toggle(self.maria)
        self.client.logout()

        self.assertFalse(self.client.login(username="maria", password="pw"))

    def test_it_toggles_back(self):
        self.toggle(self.maria)
        self.toggle(self.maria)

        self.maria.refresh_from_db()
        self.assertTrue(self.maria.is_active)

    def test_you_cannot_deactivate_yourself(self):
        response = self.toggle(self.boss)

        self.boss.refresh_from_db()
        self.assertTrue(self.boss.is_active)
        message = json.loads(response.headers["HX-Trigger"])["toast"]["message"]
        self.assertIn("your own account", message)

    def test_the_shop_can_never_be_left_without_an_admin(self):
        """The invariant, exercised the only way it can actually be attacked.

        Whoever is clicking is an active admin, so the target is never the last
        one -- deactivating everybody else eventually leaves only yourself, and
        that click is refused.
        """
        self.toggle(self.second_admin)   # allowed: boss is still an admin
        self.toggle(self.boss)           # refused: that is you

        self.assertTrue(User.objects.filter(role=User.Role.ADMIN, is_active=True).exists())

    def test_an_admin_can_be_deactivated_while_another_remains(self):
        self.toggle(self.second_admin)

        self.second_admin.refresh_from_db()
        self.assertFalse(self.second_admin.is_active)

    def test_it_keeps_the_current_search(self):
        response = self.toggle(self.maria, {"q": "mar"})

        self.assertEqual([u.username for u in response.context["users"]], ["maria"])

    def test_it_refuses_a_get(self):
        self.assertEqual(
            self.client.get(reverse("toggle_user", args=[self.maria.pk])).status_code, 405
        )


class LastAdminTests(UserAdminTestCase):
    """`is_last_admin` guards the edit form directly, so it is worth testing on
    its own rather than only through a view.
    """

    def test_one_of_several_admins_is_not_the_last(self):
        self.assertFalse(self.boss.is_last_admin())

    def test_the_only_active_admin_is_the_last(self):
        User.objects.filter(pk=self.second_admin.pk).update(is_active=False)
        self.boss.refresh_from_db()

        self.assertTrue(self.boss.is_last_admin())

    def test_a_deactivated_admin_does_not_count_as_cover(self):
        """Someone who cannot log in is not a way back into the app."""
        User.objects.filter(pk=self.second_admin.pk).update(is_active=False)

        self.assertNotIn(self.second_admin, User.other_active_admins(self.boss.pk))

    def test_an_employee_is_never_the_last_admin(self):
        self.assertFalse(self.maria.is_last_admin())


class UserListRenderingTests(UserAdminTestCase):
    def test_it_marks_your_own_row(self):
        self.assertContains(self.client.get(reverse("users")), ">you<")

    def test_it_shows_how_much_each_person_has_requested(self):
        self.assertContains(self.client.get(reverse("users")), "0 items requested")

    def test_no_template_syntax_leaks_into_the_page(self):
        markup = self.client.get(reverse("users")).content.decode()

        for marker in ("{#", "#}", "{%", "%}"):
            self.assertNotIn(marker, markup)
