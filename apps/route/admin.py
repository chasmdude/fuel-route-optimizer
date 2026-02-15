from django.contrib import admin

from apps.route.models import FuelStation


@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "state", "retail_price", "opis_id")
    list_filter = ("state",)
    search_fields = ("name", "city", "opis_id")
    ordering = ("state", "retail_price")
    readonly_fields = ("latitude", "longitude")
