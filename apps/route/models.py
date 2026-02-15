from django.contrib.gis.db import models


class FuelStation(models.Model):
    """
    A truck stop / fuel station with known retail fuel price.

    Location is stored as a PostGIS geography point (SRID 4326) for
    efficient spatial queries like corridor search via ST_DWithin.
    """

    opis_id = models.IntegerField(
        unique=True,
        help_text="OPIS Truckstop ID from the fuel price dataset.",
    )
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255, blank=True, default="")
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2, db_index=True)
    rack_id = models.IntegerField(
        null=True,
        blank=True,
        help_text="Rack ID from the fuel price dataset.",
    )
    retail_price = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        help_text="Retail fuel price in USD per gallon.",
    )
    location = models.PointField(
        geography=True,
        srid=4326,
        spatial_index=True,
        help_text="Geographic coordinates (lon, lat) of the station.",
    )

    class Meta:
        ordering = ["retail_price"]
        indexes = [
            models.Index(fields=["state"]),
            models.Index(fields=["retail_price"]),
            models.Index(fields=["city", "state"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.city}, {self.state}) - ${self.retail_price}"

    @property
    def latitude(self):
        return self.location.y if self.location else None

    @property
    def longitude(self):
        return self.location.x if self.location else None
