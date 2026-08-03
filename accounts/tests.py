"""The custom user model: role handling and the login behaviour the spec asks for."""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class UserRoleTests(TestCase):
    def test_new_users_are_employees(self):
        """The safe default: admin powers are granted, never assumed."""
        user = User.objects.create_user(
            username="maria", email="maria@example.com", password="pw"
        )

        self.assertEqual(user.role, User.Role.EMPLOYEE)
        self.assertFalse(user.is_shop_admin)

    def test_the_admin_role_is_what_gates_the_extras(self):
        user = User.objects.create_user(
            username="boss", email="boss@example.com", password="pw",
            role=User.Role.ADMIN,
        )

        self.assertTrue(user.is_shop_admin)

    def test_shop_admin_is_separate_from_django_staff(self):
        """`is_staff` opens /admin; `role` decides what the shop app allows.
        Conflating them would hand Django's admin to every shop admin.
        """
        user = User.objects.create_user(
            username="boss", email="boss@example.com", password="pw",
            role=User.Role.ADMIN,
        )

        self.assertTrue(user.is_shop_admin)
        self.assertFalse(user.is_staff)

    def test_two_users_cannot_share_an_email(self):
        User.objects.create_user(username="maria", email="shared@example.com", password="pw")

        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(username="nikos", email="shared@example.com", password="pw")


class LoginTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.maria = User.objects.create_user(
            username="maria", email="maria@example.com", password="mentor123"
        )

    def test_a_good_login_lands_on_the_order_list(self):
        response = self.client.post(
            reverse("login"), {"username": "maria", "password": "mentor123"}
        )

        self.assertRedirects(response, reverse("order_list"))

    def test_a_bad_password_is_rejected(self):
        response = self.client.post(
            reverse("login"), {"username": "maria", "password": "wrong"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_an_inactive_user_cannot_log_in(self):
        User.objects.filter(pk=self.maria.pk).update(is_active=False)

        self.client.post(reverse("login"), {"username": "maria", "password": "mentor123"})

        self.assertNotIn("_auth_user_id", self.client.session)

    def test_the_session_outlives_the_browser(self):
        """The spec asks employees to stay logged in across sessions."""
        self.client.force_login(self.maria)

        self.assertFalse(self.client.session.get_expire_at_browser_close())
