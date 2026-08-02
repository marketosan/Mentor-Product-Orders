from django.urls import path

from . import views

urlpatterns = [
    path("", views.order_list, name="order_list"),
    path("panel/", views.panel, name="panel"),
    path("items/add/", views.add_item, name="add_item"),
    path("items/<int:pk>/edit/", views.edit_item, name="edit_item"),
    path("items/<int:pk>/delete/", views.delete_item, name="delete_item"),
    path("products/search/", views.product_search, name="product_search"),
]
