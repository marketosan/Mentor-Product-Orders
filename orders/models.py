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
    unit = models.CharField(max_length=10, choices=Unit.choices)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Current price in euros.")
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
    unit_price_snapshot = models.DecimalField(max_digits=10, decimal_places=2)
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
        return self.quantity * self.unit_price_snapshot
