from django.urls import path

from . import views

app_name = "simulation_api"

urlpatterns = [
    path("runs/", views.list_runs, name="list-runs"),
    path("runs/<str:run_id>/restaurants/", views.list_restaurants, name="list-restaurants"),
    path(
        "runs/<str:run_id>/restaurants/<str:restaurant_id>/",
        views.restaurant_snapshot,
        name="restaurant-snapshot",
    ),
    path(
        "runs/<str:run_id>/restaurants/<str:restaurant_id>/rounds/<int:round_number>/visits/",
        views.round_visits,
        name="round-visits",
    ),
    path(
        "runs/<str:run_id>/restaurants/<str:restaurant_id>/events/",
        views.restaurant_events,
        name="restaurant-events",
    ),
]
