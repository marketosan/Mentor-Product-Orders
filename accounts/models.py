from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """A shop user. Employees and admins share most pages; `role` gates the
    admin-only extras (adding sellers, marking items completed, order history).

    AbstractUser already provides username, password, is_active and date_joined,
    so only email uniqueness and the role field are added here.
    """

    class Role(models.TextChoices):
        EMPLOYEE = "employee", "Employee"
        ADMIN = "admin", "Admin"

    email = models.EmailField(unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.EMPLOYEE)

    @property
    def is_shop_admin(self) -> bool:
        return self.role == self.Role.ADMIN

    @classmethod
    def other_active_admins(cls, exclude_pk):
        """Admins who could still run the shop if this account went away.

        Nothing else can create users, so demoting or deactivating the last one
        would leave the shop with no way back in short of the command line.
        """
        return cls.objects.filter(role=cls.Role.ADMIN, is_active=True).exclude(pk=exclude_pk)

    def is_last_admin(self) -> bool:
        return self.is_shop_admin and self.is_active and not self.other_active_admins(self.pk).exists()

    def __str__(self) -> str:
        return self.username
