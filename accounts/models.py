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

    def __str__(self) -> str:
        return self.username
