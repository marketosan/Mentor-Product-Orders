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

    # null (not just blank) so a second blank email doesn't collide with the
    # first under the unique constraint -- SQLite's unique index ignores NULLs
    # but treats "" as a real, colliding value.
    email = models.EmailField(unique=True, blank=True, null=True)
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

    def clean(self):
        """`AbstractUser.clean()` runs the email through `normalize_email`,
        which turns None into "" -- undoing the None a blank email is stored
        as, and reintroducing a false clash with every other blank account.
        """
        super().clean()
        self.email = self.email or None

    def __str__(self) -> str:
        return self.username
