# Fuel Route Planner API

A Django 5.2 LTS API that takes a start and finish inside the USA, returns the driving route as map-ready GeoJSON, picks the cheapest fuel stops along the way for a 500-mile-range vehicle at 10 MPG, and returns the total fuel cost.

- **Routing provider:** public OSRM demo server (free, no key). OpenRouteService is supported as an alternative via `ORS_API_KEY`.
- **Routing calls per request:** exactly 1 (0 on a cache hit).
- **Fuel prices:** `routing/data/fuel-prices.csv` (the provided file), joined offline with coordinates.
- **Measured here:** about 0.7 s cold for Chicago to Denver (almost all of it the OSRM call), about 50 ms when the route is cached. Seattle to Miami (3,300 miles) took about 1 s.

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate   # on Debian/Ubuntu: sudo apt install python3-venv
pip install -r requirements.txt
cp .env.example .env                                  # defaults work as-is, no keys needed
python manage.py runserver 127.0.0.1:8765
```

There is no database, so there is no `migrate` step. The fuel stop data is already built and committed.

Open http://127.0.0.1:8765/ for a small Leaflet map UI (loads map tiles and Leaflet from public CDNs), or use the API directly.

Run the tests (no network needed):

```bash
python manage.py test routing
```

## API

`GET` or `POST /api/route/`

| Parameter | Required | Default | Notes |
|---|---|---|---|
| `start` | yes | | `City, ST`, `City, State Name`, a street address, or `lat,lon` |
| `finish` | yes | | same formats |
| `vehicle_range` | no | 500 | miles |
| `mpg` | no | 10 | |
| `full_geometry` | no | false | true returns every route vertex instead of about 1,500 |

```bash
curl "http://127.0.0.1:8765/api/route/?start=Chicago,%20IL&finish=Denver,%20CO"

curl -X POST http://127.0.0.1:8765/api/route/ \
  -H "Content-Type: application/json" \
  -d '{"start": "Seattle, WA", "finish": "Miami, FL"}'

curl "http://127.0.0.1:8765/api/route/?start=41.88,-87.63&finish=39.74,-104.99"
```

Postman: create a POST to `http://127.0.0.1:8765/api/route/`, body type raw JSON, with the body from the second example.

Response fields (abridged):

```json
{
  "total_distance_miles": 1002.7,
  "total_duration_hours": 17.79,
  "total_fuel_cost": 141.43,
  "fuel_stops": [
    {
      "name": "KUM & GO #0370",
      "address": "I-80, EXIT 439 & SR-370",
      "city": "Gretna", "state": "NE",
      "price_per_gallon": 2.921, "gallons": 5.95, "cost": 17.37,
      "route_mile": 482.9, "miles_off_route": 0.2,
      "location": {"latitude": 41.12792, "longitude": -96.19686, "precision": "city_centroid"}
    }
  ],
  "map": {
    "geojson": {"type": "FeatureCollection", "features": ["route LineString", "one Point per stop"]},
    "bounds": [[min_lat, min_lon], [max_lat, max_lon]]
  },
  "assumptions": {"vehicle_range_miles": 500.0, "mpg": 10.0, "...": "..."},
  "routing": {"provider": "osrm", "cached": false},
  "start": {"query": "Chicago, IL", "latitude": 41.837, "longitude": -87.6849},
  "finish": {"query": "Denver, CO", "latitude": 39.7619, "longitude": -104.8811}
}
```

The `map.geojson` collection can be pasted into https://geojson.io or drawn with any map library. The `/` page does exactly that with Leaflet.

Errors are `{"error": {"code": ..., "message": ...}}`:

| Status | code | When |
|---|---|---|
| 400 | `invalid_request` | missing or out-of-range parameters |
| 400 | `invalid_location` | not found, or outside the USA (fails before any routing call) |
| 422 | `unroutable` | the router found no drivable route |
| 422 | `no_feasible_fuel_plan` | a stretch longer than the vehicle range has no candidate stops |
| 502 | `routing_unavailable` | the routing provider failed or timed out |

## Environment variables

All optional. See `.env.example`. Never commit `.env`.

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | dev-only key when `DEBUG=True` | required when `DEBUG=False` |
| `DEBUG` | `True` | |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | comma separated |
| `ROUTING_PROVIDER` | `osrm` | `osrm` or `ors` |
| `OSRM_URL` | `https://router.project-osrm.org` | point at a self-hosted OSRM if you have one |
| `ORS_API_KEY` | empty | only for `ROUTING_PROVIDER=ors` (free key at openrouteservice.org) |
| `FUEL_CORRIDOR_MILES` | `10` | how far from the route a stop may be |
| `ROUTE_CACHE_SECONDS` | `3600` | in-process route cache |
| `MAP_TILE_URL`, `MAP_TILE_ATTRIBUTION` | Esri World Street Map | basemap for the `/` demo page only. OSM's own tile server and CARTO's free tiles refused requests from my test browser, so I defaulted to Esri. Swap in any tile URL you are licensed to use. |

The OpenRouteService path is implemented but I did not run it, since it needs a key. The OSRM path is what I exercised.

## Architecture

```
request -> resolve start/finish -> ONE routing call -> index route -> filter stops -> optimize -> JSON
              (offline if "City, ST")     (OSRM)        (grid)        (corridor)      (greedy)
```

### Routing call count: one

1. **Start and finish** are resolved without the network when given as `lat,lon` or `City, ST` (a 32,000-place US Census index is committed in `routing/data/places.json`). Only free-form street addresses fall back to one Nominatim geocoding call each. That is a geocoding call, not a routing call.
2. **One OSRM call** (`overview=full&geometries=geojson`) returns the whole route geometry and distance.
3. **Everything else is offline.** No per-stop routing, no distance matrix. Detours are approximated geometrically.

Repeated requests for the same pair hit an in-process cache and make zero calls.

### Locating the fuel stops (the CSV has no coordinates)

The addresses are interstate exits ("I-44, EXIT 283 & US-69"), which public geocoders resolve poorly, and geocoding thousands of them at one request per second would take hours and still be unreliable. Every row does have a city and state, so `python manage.py geocode_fuel_stops` joins each row to the Census Gazetteer place centroid (with Nominatim for the roughly 250 cities the gazetteer misses, cached in `routing/data/nominatim_cache.json`). The result, `routing/data/fuel_stops.json`, is committed, so nothing is geocoded at request time.

The CSV has 8,151 rows. The build step drops 25 stops it could not locate, skips Canadian rows (the CSV includes provinces such as ON and BC), and collapses duplicate rows for the same station and address, keeping the lowest price. That leaves 6,601 located stops.

**Precision trade-off:** a stop's coordinates are its city centroid, not the exit. A stop can be a few miles from where the pin sits. Each stop reports `"precision": "city_centroid"` and `miles_off_route`. A 10 mile corridor absorbs most of that error. Swapping in exit-level coordinates later only means replacing `fuel_stops.json`.

### Matching stops to the route

`routing/geometry.py` densifies the route to segments of 1.5 miles or less, puts the vertices in a 0.25 degree grid, and for each stop looks only at nearby cells. That gives each stop's distance to the route and its mile marker along the route. The first version of this project compared every stop against every route vertex in Python and took minutes, so this index is what keeps requests fast. Route distances are rescaled to the router's own distance so mile markers agree with `total_distance_miles`.

### Fuel optimization

`routing/fuel_optimizer.py` is pure Python with no Django or network. It solves the classic gas station problem with a greedy rule that is provably optimal for this model:

- At a station, if a cheaper station is reachable on a full tank, buy only enough to get there.
- Otherwise, if the destination is reachable, buy only enough to finish.
- Otherwise fill the tank and drive to the cheapest reachable station.

Cost is gallons actually purchased times that station's price, with partial fills. The unit tests include a randomized comparison against an exact dynamic program over 200 instances.

### Assumptions and known limits

- **The starting tank is full and not billed.** `total_fuel_cost` is the cost of fuel bought at the listed stops. For a trip under 500 miles it is 0 with no stops. Total fuel burned on the trip is `total_distance_miles / mpg`.
- The plan minimizes fuel price only. It does not charge for detour miles, which stay within the corridor.
- When prices fall steadily along a route, the optimal plan can include small top-ups (a gallon or two). A real driver might skip those. A minimum purchase size would be a simple extension but would give up strict optimality.
- Latitude/longitude input is checked against rough US bounding boxes, so a point just across the Canadian or Mexican border can pass that check. Named places go through US-only lookups.
- The public OSRM demo is a shared fair-use server with no uptime guarantee. If it is flaky, set `ROUTING_PROVIDER=ors` with a key, or self-host OSRM and set `OSRM_URL`.

## Project layout

```
manage.py
requirements.txt
.env.example
fuel_route_api/            settings, urls
routing/
  views.py                 HTTP layer and error mapping
  routing_client.py        OSRM / ORS client plus cache (the one routing call)
  locations.py             offline-first start/finish resolution, USA check
  geometry.py              route index: densify, grid, project stops
  fuel_optimizer.py        pure fueling algorithm
  planner.py               glue, response and GeoJSON assembly
  templates/routing/map.html   Leaflet demo page
  management/commands/geocode_fuel_stops.py   offline build of the stop data
  data/                    fuel-prices.csv, fuel_stops.json, places.json, nominatim_cache.json
  tests/                   optimizer, geometry, locations, API smoke tests
```

## Tests

`python manage.py test routing` runs 33 tests: optimizer cases worked out by hand, the randomized DP comparison, geometry, location parsing, and endpoint tests with the router mocked, so no network or paid API is used. A live end-to-end request against OSRM was run by hand and is not part of the automated suite.
