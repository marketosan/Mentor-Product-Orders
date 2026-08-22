from django.urls import path

from . import views

urlpatterns = [
    path("", views.order_list, name="order_list"),
    # Not "admin/" -- Django's own admin already owns that.
    path("dashboard/", views.dashboard, name="dashboard"),
    path("history/", views.history, name="history"),
    path("panel/", views.panel, name="panel"),
    path("items/add/", views.add_item, name="add_item"),
    path("items/<int:pk>/edit/", views.edit_item, name="edit_item"),
    path("items/<int:pk>/delete/", views.delete_item, name="delete_item"),
    path("items/<int:pk>/complete/", views.complete_item, name="complete_item"),
    path("items/<int:pk>/uncomplete/", views.uncomplete_item, name="uncomplete_item"),
    path("sellers/", views.sellers, name="sellers"),
    path("sellers/new/", views.new_seller, name="new_seller"),
    path("sellers/<int:pk>/edit/", views.edit_seller, name="edit_seller"),
    path("sellers/<int:pk>/toggle/", views.toggle_seller, name="toggle_seller"),
    path("sellers/<int:pk>/delete/", views.delete_seller, name="delete_seller"),
    path("sellers/<int:pk>/complete/", views.complete_seller, name="complete_seller"),
    path("products/", views.products, name="products"),
    path("products/search/", views.product_search, name="product_search"),
    path("products/new/", views.new_product, name="new_product"),
    path("products/<int:pk>/edit/", views.edit_product, name="edit_product"),
    path("products/<int:pk>/toggle/", views.toggle_product, name="toggle_product"),
    path("products/<int:pk>/delete/", views.delete_product, name="delete_product"),
    path("products/delete-all/", views.delete_all_products, name="delete_all_products"),
]
