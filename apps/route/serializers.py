"""
DRF serializers for request validation and response formatting.

Input serializer validates and sanitizes user input.
Output serializers structure the response without leaking
internal implementation details.
"""

from rest_framework import serializers


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------
class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(
        max_length=200,
        help_text="Starting location (e.g., 'New York, NY').",
    )
    finish = serializers.CharField(
        max_length=200,
        help_text="Destination location (e.g., 'Los Angeles, CA').",
    )


# ---------------------------------------------------------------------------
# Response -- nested serializers
# ---------------------------------------------------------------------------
class RouteDetailSerializer(serializers.Serializer):
    distance_miles = serializers.FloatField()
    duration_hours = serializers.FloatField()
    map_url = serializers.URLField()
    geometry = serializers.DictField()


class FuelStopSerializer(serializers.Serializer):
    name = serializers.CharField()
    address = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    price_per_gallon = serializers.FloatField()
    gallons_filled = serializers.FloatField()
    cost = serializers.FloatField()
    distance_from_start_miles = serializers.FloatField()


class SummarySerializer(serializers.Serializer):
    total_fuel_cost = serializers.FloatField()
    total_gallons = serializers.FloatField()
    number_of_stops = serializers.IntegerField()
    routes_evaluated = serializers.IntegerField(
        help_text="Number of alternative routes evaluated (1-3).",
    )
    mpg = serializers.IntegerField()
    vehicle_range_miles = serializers.IntegerField()


class RouteResponseSerializer(serializers.Serializer):
    route = RouteDetailSerializer()
    fuel_stops = FuelStopSerializer(many=True)
    summary = SummarySerializer()
