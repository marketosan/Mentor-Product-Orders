from django.contrib import admin

from .models import OrderItem, Product, Seller


@admin.register(Seller)
class SellerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "email", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "order_name", "seller", "unit", "unit_price", "is_active")
    list_filter = ("is_active", "seller", "unit")
    # Searchable here so an admin can find a product by whatever the seller
    # calls it, which is what they are holding when they place the order.
    search_fields = ("name", "order_name")
    autocomplete_fields = ("seller",)


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("product", "quantity", "urgency", "requested_by", "created_at", "completed_at")
    list_filter = ("urgency", "completed_at")
    search_fields = ("product__name",)
    autocomplete_fields = ("product",)
