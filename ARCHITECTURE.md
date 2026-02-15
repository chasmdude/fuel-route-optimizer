# Architecture

## Overview

This document covers the design decisions, trade-offs, and assumptions behind the Fuel Route Optimizer API. It's intended for developers joining the project or reviewers evaluating the codebase.

## System Architecture

```
┌──────────┐       ┌───────┐       ┌──────────┐       ┌────────────────┐
│  Client  │──────▶│ Nginx │──────▶│ Gunicorn │──────▶│  Django + DRF  │
└──────────┘       └───────┘       └──────────┘       └───────┬────────┘
                                                              │
                          ┌───────────────────────────────────┤
                          │                                   │
                 ┌────────▼─────────┐               ┌────────▼────────┐
                 │  Service Layer   │               │   Redis Cache   │
                 │                  │               └─────────────────┘
                 │  ┌─────────────┐ │
                 │  │ ORSClient   │─┼──────▶ OpenRouteService API
                 │  └─────────────┘ │         (geocoding + directions)
                 │  ┌─────────────┐ │
                 │  │ FuelOptim.  │─┼──┐
                 │  └─────────────┘ │  │
                 │  ┌─────────────┐ │  │    ┌──────────────────┐
                 │  │ MapURLBuild.│ │  └───▶│ PostgreSQL       │
                 │  └─────────────┘ │       │ + PostGIS        │
                 └──────────────────┘       │ (FuelStation DB) │
                                            └──────────────────┘
```

## Request Flow

1. Client sends `POST /api/v1/route/` with `start` and `finish` location strings
2. **View** validates input via DRF serializer
3. **ORSClient.geocode()** resolves each location string to coordinates (2 calls, cached in Redis)
4. **ORSClient.get_directions()** fetches the driving route as GeoJSON (1 call, cached in Redis)
5. **RouteDecoder** processes the GeoJSON into a coordinate list with cumulative mile distances
6. **StationRepository.find_along_corridor()** queries PostGIS for all fuel stations within N miles of the route (single DB query using `ST_DWithin`)
7. **FuelOptimizer.optimize()** runs the min-heap retroactive refueling algorithm to select cost-optimal stops
8. **MapURLBuilder.build_url()** constructs a clickable ORS map URL with start, end, and fuel stop waypoints
9. **View** serializes the response and returns JSON

**Total external API calls per request**: 3 (2 geocode + 1 directions), all cached after first hit.

---

## Design Decisions

### 1. PostgreSQL + PostGIS over SQLite

**Decision**: Use PostGIS for spatial queries instead of SQLite with Haversine calculations in Python.

**Why**:
- `ST_DWithin` on a GiST-indexed geography column runs in ~1ms for 8K stations. Doing the same in Python with Haversine on every station for every route point would be O(n*m) and seconds-slow.
- PostGIS handles Earth curvature natively via geography types. No manual Haversine math.
- Concurrent request safety. SQLite locks on writes; PostgreSQL handles concurrent readers/writers.
- This is how every production geospatial app works. Using SQLite with manual distance math would be a red flag in a code review.

**Trade-off**: Requires Docker (or local PostgreSQL + PostGIS install). Heavier than SQLite for local dev. Mitigated by Docker Compose making it a single command.

### 2. OpenRouteService (Single External Provider)

**Decision**: Use ORS for both geocoding and routing instead of mixing providers (e.g., Nominatim + OSRM).

**Why**:
- One API key, one client class, one set of rate limits to manage.
- ORS geocoding is Pelias-based, good quality for US locations.
- ORS directions return full GeoJSON geometry in one call.
- Free tier (2,000 directions/day, 40/min) is more than sufficient.

**Trade-off**: Single point of failure. If ORS goes down, the entire API is unavailable. In a real production system, you'd add a fallback provider (Nominatim + OSRM). For this project scope, single provider is the right call -- adding fallback routing would be over-engineering.

### 3. Service Layer + Repository Pattern

**Decision**: Business logic lives in service classes, not in views or models. Database queries are encapsulated in a repository.

**Why**:
- **Testability**: Services can be unit-tested by injecting mock dependencies. The optimizer doesn't need a real database or real ORS API to test its algorithm.
- **Changeability**: Swapping ORS for Google Maps means changing `ors_client.py`, not touching views, optimizer, or models.
- **Readability**: The view is ~15 lines. It validates input, calls services, returns output. A new developer reads the view and immediately understands the flow.

**What we don't do**: We don't use a full hexagonal/ports-and-adapters architecture. The service layer is flat -- no nested abstractions. The codebase has ~10 files of business logic. Hexagonal architecture is for 50+ service codebases, not this.

### 4. Strategy Pattern for Optimization (Single Implementation)

**Decision**: The optimizer accepts an optimization strategy via Python's Protocol (structural typing). We ship two strategies:

- `MinCostStrategy` (default) -- globally optimal cost minimisation using the *retroactive refueling* algorithm (min-heap / priority queue). O(n log n) time. Provably optimal for the bounded-tank minimum-cost gas station problem. Key insight: walk the route forward, and whenever fuel goes negative, retroactively buy from the cheapest station we already passed that had spare tank capacity.
- `MinStopsStrategy` -- minimises number of stops (fills to full each time, prefers far-half of reachable range).

**Why the pattern**: The fuel optimization algorithm is the most likely thing to change. A PM might say "optimize for fewest stops" or "optimize for time." The strategy pattern means adding a new algorithm is a new class, not an if-else branch in existing code.

### Alternative Route Evaluation

**Decision**: We request up to 3 alternative routes from ORS in the *same single API call* (`alternative_routes: {target_count: 3}`). The view evaluates each route with the optimizer and picks the one with the lowest total fuel cost.

**Why**: The cheapest fuel cost depends on which stations are along the corridor. A slightly longer route through states with cheaper fuel may be overall cheaper. By evaluating multiple alternatives, we explore a wider search space without additional API calls.

**ORS free tier constraints**: `target_count` is capped at 3 by ORS, and alternative routes are only supported for routes under ~100 km (62 miles). For longer routes, the client automatically falls back to a single route. This means most real-world cross-country trips evaluate 1 route, while shorter regional trips may benefit from up to 3 alternatives.

**API call accounting**: 3 total calls (2 geocodes + 1 directions). The 2 geocode calls exist only because our API accepts text locations (e.g., "Seattle, WA"). If coordinates are supplied directly, only 1 ORS call is needed.

### 5. Map URL in Response (Not Server-Side Rendering)

**Decision**: Return a clickable URL to `maps.openrouteservice.org` with the route coordinates baked in, rather than rendering a map image server-side or building a frontend.

**Why**:
- This is a backend API. Rendering maps is a frontend concern.
- The URL opens a fully interactive map (zoom, pan, directions) -- better UX than a static image.
- Zero frontend dependencies. No JS build step, no Leaflet, no template rendering.
- Any consuming frontend or mobile app can ignore the URL and use the GeoJSON geometry directly.

**URL format**: `https://maps.openrouteservice.org/directions?a={lat1},{lon1},{lat2},{lon2},...&b=0&c=0&k1=en-US&k2=mi`

### 6. Redis Caching for External API Responses

**Decision**: Cache ORS geocoding and directions responses in Redis with TTL.

**Why**:
- ORS has rate limits (40 req/min). Caching avoids burning quota on repeated queries.
- Same start/finish pair produces identical results. Cache hit = ~1ms vs ~500ms API call.
- Geocoding results for city names are effectively permanent. Directions change rarely.

**Cache strategy**:
- Geocoding: cache key = normalized location string, TTL = 24 hours
- Directions: cache key = hash of start + end coordinates, TTL = 1 hour
- Cache is a performance optimization, not a correctness requirement. Cache miss = fresh API call.

### 7. Split Settings (base/development/production)

**Decision**: Three settings files instead of one with `if DEBUG` blocks.

**Why**:
- `base.py` has everything shared: INSTALLED_APPS, MIDDLEWARE, DRF config.
- `development.py` adds DEBUG=True, console email backend, verbose SQL logging.
- `production.py` adds SECURE_SSL_REDIRECT, HSTS, whitenoise, Sentry DSN.
- Selected via `DJANGO_SETTINGS_MODULE` env var. No runtime branching.

**Trade-off**: Three files to maintain instead of one. Worth it because a single settings file with conditional blocks becomes unreadable at ~200 lines and is a common source of "works in dev, breaks in prod" bugs.

---

## Trade-offs

### Accepted Trade-offs

| Trade-off | What we gave up | What we gained |
|-----------|----------------|----------------|
| PostGIS requirement | Can't run without PostgreSQL | Sub-millisecond spatial queries, production-ready concurrency |
| Single ORS provider | No fallback if ORS is down | Simpler client code, single API key, consistent behavior |
| Approximate truck stop geocoding | Station locations are city-level, not street-level | Zero API calls during import, deterministic/reproducible, fast |
| Min-heap retroactive refueling algorithm | More complex than a simple greedy | Provably optimal fuel cost, no micro-fills, handles partial fills naturally |
| Docker required | Can't just `pip install && runserver` | Reproducible environment, one-command setup, mirrors production |
| ORS alternative routes limited to ~100 km | Cross-country trips evaluate 1 route only | Short regional trips benefit from up to 3 alternatives; no extra API calls |

---

## Assumptions

### Business Assumptions

1. **Vehicle starts with a full tank** (configurable via `INITIAL_FUEL_FRACTION`). The problem doesn't specify initial fuel level. Full tank is the default assumption. The fraction is configurable (e.g., 0.5 for half tank) via Django settings.

2. **Optimal partial fills**. The min-heap algorithm determines exactly how many gallons to buy at each station to minimize total cost. It retroactively buys fuel from the cheapest stations passed, bounded by available tank capacity at each point.

3. **Fuel price data is static**. Prices from the Excel file are loaded once and treated as fixed. In production, you'd have a periodic import job updating prices. The architecture supports this (re-run `import_fuel_data` command).

4. **US-only routes**. The dataset includes some Canadian truck stops (AB, BC, ON, etc.) but we filter to US states only during import since the requirement specifies "both within the USA."

5. **Truck stops are accessible from the route**. We assume any station within the corridor buffer (default 25 miles from route centerline) can be reached without significant detour. In reality, some stations may require exiting the highway and driving several miles. The ORS route doesn't account for these detour distances.

### Technical Assumptions

6. **City-level geocoding is sufficient for station lookup**. The Excel data has city + state but no coordinates. We geocode using a bundled US cities dataset (matching city name + state to known lat/lon). This puts stations at city center, not their actual street address. Since our corridor search uses a 25-mile buffer, city-level accuracy (~5-10 mile error) is acceptable.

7. **ORS public API availability**. We depend on the public ORS API being available. No self-hosted fallback. For a production system handling real traffic, you'd either self-host ORS or use a paid provider with an SLA.

8. **Sequential fuel stops**. The optimizer assumes fuel stops are visited in order along the route. No backtracking.

9. **Flat terrain / constant MPG**. The 10 mpg figure is treated as constant regardless of terrain, speed, or load. In reality, mountain passes reduce efficiency. This matches the problem specification.

10. **Duplicate stations in the dataset**. The Excel file has 8,151 rows but only 6,738 unique truck stop IDs. Some stations appear multiple times (possibly different fuel types or price sources). During import, we deduplicate by OPIS Truckstop ID, keeping the lowest price -- giving the customer the best deal.

---

## Data Flow for Import

```
Excel File (8,151 rows)
    │
    ▼
Parse with openpyxl
    │
    ▼
Filter: US states only, remove Canadian provinces (AB, BC, MB, ON, QC, SK, NS, NB, YT)
    │
    ▼
Deduplicate: by OPIS Truckstop ID, keep lowest retail price
    │
    ▼
Geocode: match city+state against bundled US cities lat/lon dataset
    │
    ▼
Fallback: unmatched cities → state centroid coordinates
    │
    ▼
Bulk insert into PostgreSQL/PostGIS (FuelStation model with PointField)
    │
    ▼
GiST spatial index created on location field
```

---

## Security Notes

- ORS API key is stored in `.env`, never committed to git
- `.env.example` is committed as a template with placeholder values
- Django SECRET_KEY is generated per environment via `.env`
- Production settings enforce HTTPS redirect, HSTS, secure cookies
- No authentication on the API (assessment scope). In production, you'd add API key auth or OAuth.
- Rate limiting not implemented (assessment scope). In production, use django-ratelimit or Nginx rate limiting.

---

## Future Improvements (Not Built)

These are things a production system would need that are out of scope for this assessment:

- **Periodic price updates**: Scheduled task to re-import fuel prices from a data provider
- **Fallback routing provider**: OSRM or Google Maps if ORS is unavailable
- **Self-hosted ORS**: Eliminate the 100 km alternative routes limit and rate limits
- **Detour distance calculation**: Route to each candidate station and back to assess real detour cost
- **User authentication + rate limiting**: API key management, usage quotas
- **Async processing**: For very long routes, queue the computation and return a job ID
- **Monitoring**: Prometheus metrics, health check endpoint, ORS API latency tracking
