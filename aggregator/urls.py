from django.urls import path

from . import views

urlpatterns = [
    path("", views.search, name="search"),
    path("cards/<int:card_id>/", views.card_detail, name="card_detail"),
    path("wanted/", views.wanted_list, name="wanted_list"),
    path("status/", views.status, name="status"),
    path("healthz", views.healthz, name="healthz"),
    path("login", views.login_view, name="login"),
]

