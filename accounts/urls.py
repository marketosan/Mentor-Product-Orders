from django.urls import path

from . import views

urlpatterns = [
    path("", views.users, name="users"),
    path("new/", views.new_user, name="new_user"),
    path("<int:pk>/edit/", views.edit_user, name="edit_user"),
    path("<int:pk>/toggle/", views.toggle_user, name="toggle_user"),
]
