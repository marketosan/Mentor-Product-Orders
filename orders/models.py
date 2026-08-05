import re
from urllib.parse import quote

from django.conf import settings
from django.db import models


class Seller(models.Model):
    """A supplier the shop buys from. Only admins can create these."""

    name = models.CharField(max_length=200, unique=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def viber_url(self) -> str:
        """Deep link opening a Viber chat with this seller, or "" if no phone.

        Numbers are stored the way a person writes them -- "+30 210 555 0198"
        -- but the link needs them bare, so everything except digits and a
        leading + comes out, and the + is percent-encoded.

        The link only does anything on a device with Viber installed, and only
        reaches sellers who are actually Viber users.
        """
        if not self.phone:
            return ""

        cleaned = re.sub(r"[^\d+]", "", self.phone)
        # A + is only meaningful as the international prefix.
        cleaned = "+" + cleaned.replace("+", "") if cleaned.startswith("+") else cleaned.replace("+", "")
        if not cleaned.strip("+"):
            return ""

        return f"viber://chat?number={quote(cleaned, safe='')}"


class Product(models.Model):
    """A catalog item, always tied to the seller it is bought from.

    Names are unique per seller, so the same item can be stocked from two
    different suppliers without renaming it.
    """

    class Unit(models.TextChoices):
        KG = "kg", "kg"
        G = "g", "g"
        L = "l", "l"
        ML = "ml", "ml"
        PIECE = "piece", "piece"
        PACK = "pack", "pack"
        BOX = "box", "box"

    name = models.CharField(max_length=200)
    # What the seller calls this item on their own order sheet, when that
    # differs from the shop's name for it. Admin-only: it never appears in the
    # employee UI, and search still matches on `name`.
    order_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Optional. The seller's own name for this product, for use when ordering.",
    )
    unit = models.CharField(max_length=10, choices=Unit.choices)
    # Optional: a product can be added mid-order by someone who does not know
    # what it costs. Null means "not known", which is deliberately different
    # from 0.00 -- a zero here would quietly understate every order total.
    unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Current price in euros. Leave empty if not known.",
    )
    seller = models.ForeignKey(Seller, on_delete=models.PROTECT, related_name="products")
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["seller", "name"], name="unique_product_name_per_seller"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.seller.name})"


class OrderItemQuerySet(models.QuerySet):
    def open(self):
        return self.filter(completed_at__isnull=True)

    def completed(self):
        return self.filter(completed_at__isnull=False)


class OrderItem(models.Model):
    """A request to reorder a product. Open until an admin completes it.

    `unit_price_snapshot` freezes the price at request time so later catalog
    price changes never rewrite history.
    """

    class Urgency(models.TextChoices):
        LOW = "low", "Low"
        HIGH = "high", "High"

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_items")
    quantity = models.DecimalField(max_digits=10, decimal_places=3)
    urgency = models.CharField(max_length=10, choices=Urgency.choices, default=Urgency.LOW)
    # Null when the product had no price at the time. Still a snapshot: pricing
    # the product later must not retroactively price what was already ordered.
    unit_price_snapshot = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="order_items_requested",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_items_completed",
    )

    objects = OrderItemQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["completed_at", "product"])]

    def __str__(self) -> str:
        return f"{self.quantity} {self.product.unit} {self.product.name}"

    @property
    def is_open(self) -> bool:
        return self.completed_at is None

    @property
    def line_total(self):
        """What this row costs, at the price frozen when it was requested.

        None when the product had no price. Callers must not treat that as
        zero: unknown is not free, and summing it as 0 would report a total the
        shop will not actually be charged.
        """
        if self.unit_price_snapshot is None:
            return None
        return self.quantity * self.unit_price_snapshot
