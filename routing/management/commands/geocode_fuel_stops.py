"""
Build routing/data/fuel_stops.json: the CSV rows plus city-level coordinates.

The CSV has no lat/lon and its addresses are interstate exits, which public
geocoders resolve poorly. Every row does have a city and state, so we join
those against the free US Census Gazetteer (place centroids). Cities that
the gazetteer cannot match are resolved once through Nominatim (one request
per unique city, rate limited). This runs offline, once; the API never
geocodes stops at request time.
"""
import csv
import io
import json
import re
import time
import urllib.request
import zipfile
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from routing.textnorm import normalize

GAZETTEER_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "2024_Gazetteer/2024_Gaz_place_national.zip"
)
US_STATES = set(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT "
    "NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()
)


def load_gazetteer():
    with urllib.request.urlopen(GAZETTEER_URL, timeout=120) as resp:
        payload = resp.read()
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        member = zf.namelist()[0]
        text = zf.read(member).decode("utf-8", errors="replace")
    places = {}
    reader = csv.reader(io.StringIO(text), delimiter="\t")
    next(reader)
    for row in reader:
        state, name = row[0].strip(), row[3]
        lat, lon = float(row[10]), float(row[11])
        places.setdefault((state, normalize(name)), (lat, lon))
    return places


def nominatim(city: str, state: str):
    resp = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"city": city, "state": state, "country": "US", "format": "json", "limit": 1},
        headers={"User-Agent": "fuel-route-api-offline-build/1.0"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if data:
        return float(data[0]["lat"]), float(data[0]["lon"])
    return None


class Command(BaseCommand):
    help = "Join the fuel price CSV with city centroids and write routing/data/fuel_stops.json"

    def add_arguments(self, parser):
        parser.add_argument("--no-nominatim", action="store_true",
                            help="Skip the Nominatim fallback for unmatched cities")

    def handle(self, *args, **options):
        base = Path(settings.BASE_DIR)
        csv_path = base / "routing" / "data" / "fuel-prices.csv"
        out_path = base / "routing" / "data" / "fuel_stops.json"
        places_path = base / "routing" / "data" / "places.json"
        cache_path = base / "routing" / "data" / "nominatim_cache.json"

        self.stdout.write("Downloading Census gazetteer...")
        places = load_gazetteer()
        places_path.write_text(json.dumps(
            {f"{n}|{st}": [round(la, 4), round(lo, 4)]
             for (st, n), (la, lo) in places.items()},
            indent=2), encoding="utf-8")
        self.stdout.write(f"Wrote {len(places)} places to {places_path}")

        rows = {}
        with open(csv_path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row["State"].strip() not in US_STATES:
                    continue
                key = (row["OPIS Truckstop ID"].strip(), row["Address"].strip())
                price = float(row["Retail Price"])
                if key not in rows or price < rows[key]["price"]:
                    rows[key] = {
                        "id": row["OPIS Truckstop ID"].strip(),
                        "name": row["Truckstop Name"].strip(),
                        "address": re.sub(r"\s+", " ", row["Address"]).strip(),
                        "city": row["City"].strip(),
                        "state": row["State"].strip(),
                        "price": price,
                    }

        cache = {}
        unmatched = set()
        for stop in rows.values():
            k = (stop["state"], normalize(stop["city"]))
            if k in places:
                cache[(stop["city"], stop["state"])] = places[k]
            else:
                unmatched.add((stop["city"], stop["state"]))
        unmatched -= set(cache)
        self.stdout.write(f"{len(rows)} unique stops; {len(unmatched)} cities not in gazetteer")

        if unmatched and not options["no_nominatim"]:
            saved = json.loads(cache_path.read_text()) if cache_path.exists() else {}
            for city, state in sorted(unmatched):
                key = f"{city}|{state}"
                if key not in saved:
                    try:
                        hit = nominatim(city, state)
                    except requests.RequestException as exc:
                        self.stdout.write(self.style.WARNING(f"  {city}, {state}: {exc}"))
                        continue
                    saved[key] = hit
                    cache_path.write_text(json.dumps(saved), encoding="utf-8")
                    time.sleep(1.1)
                if saved[key]:
                    cache[(city, state)] = tuple(saved[key])

        stops = []
        dropped = 0
        for stop in rows.values():
            hit = cache.get((stop["city"], stop["state"]))
            if not hit:
                dropped += 1
                continue
            stop["latitude"], stop["longitude"] = round(hit[0], 5), round(hit[1], 5)
            stops.append(stop)

        out_path.write_text(json.dumps(stops, indent=2), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(
            f"Wrote {len(stops)} stops to {out_path} ({dropped} dropped, no coordinates)"
        ))
