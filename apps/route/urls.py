from django.urls import path

from apps.route.views import HealthView, RouteView

app_name = "route"

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("route/", RouteView.as_view(), name="route"),
]
