# Fuel Route Optimizer

A production-grade Django REST API that calculates optimal fuel stops along driving routes in the USA. Given a start and finish location, it returns the driving route, cost-effective fuel-up locations, a clickable map URL, and total fuel cost.

## Problem

- A vehicle needs to drive between two US locations
- Maximum vehicle range: **500 miles** per tank
- Fuel efficiency: **10 miles per gallon**
- Fuel prices vary by station (8,000+ truck stops with known prices)
- **Goal**: Minimize total fuel cost by choosing the cheapest stations along the route

## Solution

A Django API that:

1. **Geocodes** start/finish location strings to coordinates (via OpenRouteService)
2. **Fetches the driving route** as a GeoJSON LineString (single ORS API call)
3. **Finds fuel stations** within a corridor of the route (PostGIS spatial query)
4. **Evaluates up to 3 alternative routes** from ORS (single API call) and picks the cheapest
5. **Optimizes fuel stops** using a min-heap retroactive refueling algorithm (provably optimal for minimum fuel cost)
6. **Returns** the route geometry, fuel stops with costs, a clickable map URL, and total trip fuel cost

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/)
- An [OpenRouteService API key](https://openrouteservice.org/dev/#/signup) (free tier is sufficient)

### Setup

```bash
# Clone the repository
git clone <repo-url>
cd fuel-route-optimizer

# Copy environment template and set your ORS API key
cp .env.example .env
# Edit .env and set ORS_API_KEY=your_key_here

# Build and start all services (Django, PostgreSQL/PostGIS, Redis, Nginx)
make build
make up

# Import fuel price data (one-time)
make import-data

# Verify the stack is running
curl http://localhost:8000/api/v1/health/
```

### Run Tests

```bash
make test
```

## API Usage

### `POST /api/v1/route/`

Calculate optimal fuel stops for a route.

**Request:**

```bash
curl -X POST http://localhost:8000/api/v1/route/ \
  -H "Content-Type: application/json" \
  -d '{
    "start": "New York, NY",
    "finish": "Los Angeles, CA"
  }'
```

**Response:**

```json
{
    "route": {
        "distance_miles": 2790.5,
        "duration_hours": 40.2,
        "map_url": "https://maps.openrouteservice.org/directions?a=40.7128,-74.006,34.0522,-118.2437&b=0&c=0&k1=en-US&k2=mi",
        "geometry": {
            "type": "LineString",
            "coordinates": [[-74.006, 40.7128], "..."]
        }
    },
    "fuel_stops": [
        {
            "name": "PILOT TRAVEL CENTER #1243",
            "address": "I-80, EXIT 45 & US-15",
            "city": "Clearfield",
            "state": "PA",
            "latitude": 41.02,
            "longitude": -78.43,
            "price_per_gallon": 2.89,
            "gallons_filled": 50.0,
            "cost": 144.50,
            "distance_from_start_miles": 280.0
        }
    ],
    "summary": {
        "total_fuel_cost": 892.35,
        "total_gallons": 279.05,
        "number_of_stops": 5,
        "routes_evaluated": 1,
        "mpg": 10,
        "vehicle_range_miles": 500
    }
}
```

The `map_url` field is a clickable link that opens an interactive map with the driving route rendered on OpenRouteService Maps.

**Error Response (400):**

```json
{
    "error": {
        "code": "GEOCODING_FAILED",
        "message": "Could not geocode location: 'Faketown, XX'",
        "details": {}
    }
}
```

## Project Structure

```
fuel-route-optimizer/
├── config/                         # Django project configuration
│   ├── settings/
│   │   ├── base.py                 # Shared settings
│   │   ├── development.py          # Dev overrides (DEBUG, verbose logging)
│   │   └── production.py           # Prod hardening (security headers, HTTPS)
│   ├── urls.py                     # Root URL configuration
│   ├── wsgi.py
│   └── asgi.py
├── apps/
│   └── route/                      # Main application
│       ├── models.py               # FuelStation model (PostGIS PointField)
│       ├── repositories.py         # StationRepository (spatial queries)
│       ├── serializers.py          # DRF input/output serializers
│       ├── views.py                # Thin API view (orchestrates services)
│       ├── dataclasses.py          # Domain objects (Coordinates, RouteResult, FuelPlan)
│       ├── exceptions.py           # Domain exceptions
│       ├── services/
│       │   ├── ors_client.py       # OpenRouteService HTTP client
│       │   ├── route_decoder.py    # GeoJSON processing + distance calculations
│       │   ├── fuel_optimizer.py   # Core optimization algorithm
│       │   └── map_url_builder.py  # Constructs shareable map URLs
│       ├── management/commands/
│       │   └── import_fuel_data.py # Data import command
│       └── tests/                  # Test suite
├── data/
│   └── fuel_prices.xlsx            # Source fuel price data
├── requirements/
│   ├── base.txt                    # Core dependencies
│   ├── dev.txt                     # Dev/test dependencies
│   └── prod.txt                    # Production dependencies
├── nginx/
│   └── default.conf                # Nginx reverse proxy config
├── docker-compose.yml              # Full service stack
├── Dockerfile                      # Multi-stage production build
├── Makefile                        # Common operations
├── .env.example                    # Environment variable template
└── ARCHITECTURE.md                 # Design decisions and trade-offs
```

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Framework | Django 6.0 + DRF | API framework |
| Database | PostgreSQL 16 + PostGIS 3.4 | Spatial queries for station lookup |
| Cache | Redis 7 | ORS response caching |
| App Server | Gunicorn | Multi-worker WSGI server |
| Reverse Proxy | Nginx | Static files, request buffering |
| Containerization | Docker Compose | Single-command deployment |
| Routing/Geocoding | OpenRouteService API | Directions + address resolution |

## Make Commands

```bash
make build          # Build Docker images
make up             # Start all services
make down           # Stop all services
make test           # Run test suite
make import-data    # Import fuel price data from Excel
make migrate        # Run database migrations
make shell          # Django shell inside container
make logs           # Tail service logs
```

## Testing with Postman

Import [postman_collection.json](postman_collection.json) into Postman for a full test suite:

- **Health Check** -- verify API and database are running
- **Short Route** (NY → Philadelphia) -- validates 0-stop response
- **Medium Route** (NY → Columbus) -- validates fuel stop structure and cost
- **Long Route** (Seattle → Miami) -- validates multi-stop cross-country, stop ordering, cost math
- **Alternative Routes** (Princeton → Trenton) -- validates `routes_evaluated > 1`
- **Error Cases** -- missing fields, empty body, invalid locations

All requests include Postman test scripts that auto-validate response structure and business logic.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for design decisions, trade-offs, assumptions, and service layer documentation.

## License

Private -- assessment project.
