"""
Management command to import fuel price data from Excel.

Reads the provided fuel prices spreadsheet, geocodes each station
using a bundled US cities dataset (zero API calls), deduplicates by
OPIS ID (keeping cheapest price), and bulk-upserts into PostGIS.

Usage:
    python manage.py import_fuel_data
    python manage.py import_fuel_data --excel-path /custom/path.xlsx
"""

import csv
import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand

from apps.route.models import FuelStation

logger = logging.getLogger(__name__)

# US state abbreviations (exclude Canadian provinces in dataset)
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
}

# Approximate state centroids as fallback when city is not found
STATE_CENTROIDS = {
    "AL": (32.806671, -86.791130), "AK": (61.370716, -152.404419),
    "AZ": (33.729759, -111.431221), "AR": (34.969704, -92.373123),
    "CA": (36.116203, -119.681564), "CO": (39.059811, -105.311104),
    "CT": (41.597782, -72.755371), "DE": (39.318523, -75.507141),
    "FL": (27.766279, -81.686783), "GA": (33.040619, -83.643074),
    "HI": (21.094318, -157.498337), "ID": (44.240459, -114.478773),
    "IL": (40.349457, -88.986137), "IN": (39.849426, -86.258278),
    "IA": (42.011539, -93.210526), "KS": (38.526600, -96.726486),
    "KY": (37.668140, -84.670067), "LA": (31.169546, -91.867805),
    "ME": (44.693947, -69.381927), "MD": (39.063946, -76.802101),
    "MA": (42.230171, -71.530106), "MI": (43.326618, -84.536095),
    "MN": (45.694454, -93.900192), "MS": (32.741646, -89.678696),
    "MO": (38.456085, -92.288368), "MT": (46.921925, -110.454353),
    "NE": (41.125370, -98.268082), "NV": (38.313515, -117.055374),
    "NH": (43.452492, -71.563896), "NJ": (40.298904, -74.521011),
    "NM": (34.840515, -106.248482), "NY": (42.165726, -74.948051),
    "NC": (35.630066, -79.806419), "ND": (47.528912, -99.784012),
    "OH": (40.388783, -82.764915), "OK": (35.565342, -96.928917),
    "OR": (44.572021, -122.070938), "PA": (40.590752, -77.209755),
    "RI": (41.680893, -71.511780), "SC": (33.856892, -80.945007),
    "SD": (44.299782, -99.438828), "TN": (35.747845, -86.692345),
    "TX": (31.054487, -97.563461), "UT": (40.150032, -111.862434),
    "VT": (44.045876, -72.710686), "VA": (37.769337, -78.169968),
    "WA": (47.400902, -121.490494), "WV": (38.491226, -80.954456),
    "WI": (44.268543, -89.616508), "WY": (42.755966, -107.302490),
    "DC": (38.897438, -77.026817),
}

DATA_DIR = Path(settings.BASE_DIR) / "data"
DEFAULT_EXCEL = DATA_DIR / "fuel_prices.xlsx"
CITIES_CSV = DATA_DIR / "uscities.csv"


class Command(BaseCommand):
    help = "Import fuel station data from Excel and geocode using US cities dataset."

    def add_arguments(self, parser):
        parser.add_argument(
            "--excel-path",
            type=str,
            default=str(DEFAULT_EXCEL),
            help="Path to the fuel prices Excel file.",
        )

    def handle(self, *args, **options):
        excel_path = Path(options["excel_path"])
        if not excel_path.exists():
            self.stderr.write(self.style.ERROR(f"Excel file not found: {excel_path}"))
            return

        self.stdout.write("Loading US cities geocoding data...")
        city_coords = self._load_city_coords()
        self.stdout.write(f"  Loaded {len(city_coords)} city coordinates.")

        self.stdout.write(f"Reading Excel file: {excel_path}")
        raw_stations = self._parse_excel(excel_path)
        self.stdout.write(f"  Parsed {len(raw_stations)} rows from Excel.")

        self.stdout.write("Filtering to US states and deduplicating...")
        stations = self._filter_and_deduplicate(raw_stations)
        self.stdout.write(f"  {len(stations)} unique US stations after dedup.")

        self.stdout.write("Geocoding stations...")
        geocoded, fallback_count, skipped = self._geocode_stations(stations, city_coords)
        self.stdout.write(
            f"  Geocoded: {len(geocoded)} "
            f"(city match: {len(geocoded) - fallback_count}, "
            f"state fallback: {fallback_count}, "
            f"skipped: {skipped})"
        )

        self.stdout.write("Upserting into database...")
        created, updated = self._upsert_stations(geocoded)
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Created: {created}, Updated: {updated}, "
                f"Total in DB: {FuelStation.objects.count()}"
            )
        )

    def _load_city_coords(self) -> dict[tuple[str, str], tuple[float, float]]:
        """Load city name + state -> (lat, lon) lookup from CSV."""
        coords = {}
        with open(CITIES_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                city = row["city_ascii"].strip().lower()
                state = row["state_id"].strip().upper()
                try:
                    lat = float(row["lat"])
                    lng = float(row["lng"])
                    # Keep the first (most populous) entry per city+state
                    if (city, state) not in coords:
                        coords[(city, state)] = (lat, lng)
                except (ValueError, KeyError):
                    continue
        return coords

    def _parse_excel(self, path: Path) -> list[dict]:
        """Parse the fuel prices Excel file into a list of dicts."""
        import openpyxl

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()

        if not rows:
            return []

        # First row is headers
        headers = rows[0]
        stations = []
        for row in rows[1:]:
            if len(row) < 7:
                continue
            try:
                station = {
                    "opis_id": int(row[0]) if row[0] is not None else None,
                    "name": str(row[1] or "").strip(),
                    "address": str(row[2] or "").strip(),
                    "city": str(row[3] or "").strip(),
                    "state": str(row[4] or "").strip().upper(),
                    "rack_id": int(row[5]) if row[5] is not None else None,
                    "retail_price": Decimal(str(row[6])) if row[6] is not None else None,
                }
                if station["opis_id"] is not None and station["retail_price"] is not None:
                    stations.append(station)
            except (ValueError, InvalidOperation, TypeError) as e:
                logger.debug(f"Skipping row {row}: {e}")
                continue

        return stations

    def _filter_and_deduplicate(self, stations: list[dict]) -> dict[int, dict]:
        """Filter to US states, deduplicate by OPIS ID keeping lowest price."""
        deduped: dict[int, dict] = {}
        for s in stations:
            if s["state"] not in US_STATES:
                continue
            opis_id = s["opis_id"]
            if opis_id not in deduped or s["retail_price"] < deduped[opis_id]["retail_price"]:
                deduped[opis_id] = s
        return deduped

    def _geocode_stations(
        self,
        stations: dict[int, dict],
        city_coords: dict[tuple[str, str], tuple[float, float]],
    ) -> tuple[list[dict], int, int]:
        """Match stations to city coordinates. Returns (geocoded, fallback_count, skipped)."""
        geocoded = []
        fallback_count = 0
        skipped = 0

        for opis_id, station in stations.items():
            city_key = (station["city"].lower(), station["state"])
            coords = city_coords.get(city_key)

            if coords:
                station["lat"] = coords[0]
                station["lon"] = coords[1]
            elif station["state"] in STATE_CENTROIDS:
                station["lat"] = STATE_CENTROIDS[station["state"]][0]
                station["lon"] = STATE_CENTROIDS[station["state"]][1]
                fallback_count += 1
            else:
                skipped += 1
                continue

            geocoded.append(station)

        return geocoded, fallback_count, skipped

    def _upsert_stations(self, stations: list[dict]) -> tuple[int, int]:
        """Bulk upsert stations into the database. Returns (created, updated)."""
        created = 0
        updated = 0

        # Process in batches to avoid memory issues
        batch_size = 500
        for i in range(0, len(stations), batch_size):
            batch = stations[i : i + batch_size]
            for s in batch:
                point = Point(s["lon"], s["lat"], srid=4326)
                _, was_created = FuelStation.objects.update_or_create(
                    opis_id=s["opis_id"],
                    defaults={
                        "name": s["name"],
                        "address": s["address"],
                        "city": s["city"],
                        "state": s["state"],
                        "rack_id": s.get("rack_id"),
                        "retail_price": s["retail_price"],
                        "location": point,
                    },
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

        return created, updated
