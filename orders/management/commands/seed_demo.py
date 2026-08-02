"""Populate the database with a small, realistic set of demo data.

Safe to run repeatedly: everything is created with get_or_create.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from orders.models import OrderItem, Product, Seller

User = get_user_model()

SELLERS = [
    ("Bertoli Coffee Roasters", "+30 210 555 0142", "orders@bertoli.example"),
    ("Green Valley Dairy", "+30 210 555 0198", "hello@greenvalley.example"),
    ("Metro Wholesale", "+30 210 555 0177", ""),
]

PRODUCTS = [
    # (name, seller, unit, price)
    ("Espresso beans - house blend", "Bertoli Coffee Roasters", "kg", "18.50"),
    ("Decaf beans", "Bertoli Coffee Roasters", "kg", "21.00"),
    ("Whole milk", "Green Valley Dairy", "l", "1.15"),
    ("Oat milk", "Green Valley Dairy", "l", "2.40"),
    ("Paper cups 8oz", "Metro Wholesale", "pack", "12.00"),
    ("Napkins", "Metro Wholesale", "box", "8.75"),
]

ORDER_ITEMS = [
    # (product, quantity, urgency)
    ("Espresso beans - house blend", "6", "high"),
    ("Whole milk", "24", "high"),
    ("Oat milk", "12", "low"),
    ("Paper cups 8oz", "4", "low"),
]


class Command(BaseCommand):
    help = "Create demo sellers, products and open order items."

    def handle(self, *args, **options):
        admin, created = User.objects.get_or_create(
            username="admin",
            defaults={"email": "admin@example.com", "role": User.Role.ADMIN,
                      "is_staff": True, "is_superuser": True},
        )
        if created:
            admin.set_password("admin")
            admin.save()

        maria, created = User.objects.get_or_create(
            username="maria",
            defaults={"email": "maria@example.com", "role": User.Role.EMPLOYEE},
        )
        if created:
            maria.set_password("mentor123")
            maria.save()

        sellers = {}
        for name, phone, email in SELLERS:
            sellers[name], _ = Seller.objects.get_or_create(
                name=name, defaults={"phone": phone, "email": email}
            )

        products = {}
        for name, seller_name, unit, price in PRODUCTS:
            products[name], _ = Product.objects.get_or_create(
                name=name,
                seller=sellers[seller_name],
                defaults={"unit": unit, "unit_price": price, "created_by": admin},
            )

        for product_name, quantity, urgency in ORDER_ITEMS:
            product = products[product_name]
            OrderItem.objects.get_or_create(
                product=product,
                completed_at=None,
                defaults={
                    "quantity": quantity,
                    "urgency": urgency,
                    "unit_price_snapshot": product.unit_price,
                    "requested_by": maria,
                },
            )

        self.stdout.write(self.style.SUCCESS(
            f"Demo data ready: {Seller.objects.count()} sellers, "
            f"{Product.objects.count()} products, "
            f"{OrderItem.objects.open().count()} open items."
        ))
        self.stdout.write("Log in as  admin / admin  or  maria / mentor123")
