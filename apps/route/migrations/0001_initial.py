import django.contrib.gis.db.models.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="FuelStation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "opis_id",
                    models.IntegerField(
                        help_text="OPIS Truckstop ID from the fuel price dataset.",
                        unique=True,
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                (
                    "address",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                ("city", models.CharField(max_length=100)),
                ("state", models.CharField(db_index=True, max_length=2)),
                (
                    "rack_id",
                    models.IntegerField(
                        blank=True,
                        help_text="Rack ID from the fuel price dataset.",
                        null=True,
                    ),
                ),
                (
                    "retail_price",
                    models.DecimalField(
                        decimal_places=4,
                        help_text="Retail fuel price in USD per gallon.",
                        max_digits=6,
                    ),
                ),
                (
                    "location",
                    django.contrib.gis.db.models.fields.PointField(
                        geography=True,
                        help_text="Geographic coordinates (lon, lat) of the station.",
                        srid=4326,
                    ),
                ),
            ],
            options={
                "ordering": ["retail_price"],
            },
        ),
        migrations.AddIndex(
            model_name="fuelstation",
            index=models.Index(fields=["state"], name="route_fuelst_state_b80e4b_idx"),
        ),
        migrations.AddIndex(
            model_name="fuelstation",
            index=models.Index(
                fields=["retail_price"], name="route_fuelst_retail__86b780_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="fuelstation",
            index=models.Index(
                fields=["city", "state"], name="route_fuelst_city_bc18cc_idx"
            ),
        ),
    ]
