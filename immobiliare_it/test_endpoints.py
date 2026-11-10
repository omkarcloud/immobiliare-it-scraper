"""Live endpoint smoke tests: one call per /immobiliare-it/* route against a
running service, with example values proven to return data (2026-11-07).
The listing tooling reads the FIRST call per route as its working example.

Skipped unless IMMOBILIARE_IT_BASE points at a running service:

    ONLY_SCRAPER=immobiliare-it SCRAPERS_PORT=6047 python run.py --dev
    IMMOBILIARE_IT_BASE=http://127.0.0.1:6047 python -m pytest immobiliare_it/test_endpoints.py -q
"""
import os

import pytest

BASE = os.environ.get("IMMOBILIARE_IT_BASE", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE, reason="set IMMOBILIARE_IT_BASE to run live endpoint tests")


def call(path, status=200, **params):
    from curl_cffi import requests
    resp = requests.get(BASE + path, params=params, timeout=300)
    assert resp.status_code == status, f"{path} {params} -> {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body, f"{path} returned an empty body"
    return body


# ---- properties ----------------------------------------------------------------------

def test_property_details():
    # a clifftop villa in Positano on the Amalfi Coast (virtual tour, video, floor plan)
    body = call("/immobiliare-it/properties/details", property="132732166")
    assert body["id"] == 132732166 and body["link"].endswith("/annunci/132732166/")
    assert body["price"]["amount"] and body["price"]["currency"] == "EUR"
    assert body["location"]["city"] == "Positano" and body["location"]["latitude"]
    assert body["photos"] and body["agency"]["name"] and body["description"]
    by_link = call("/immobiliare-it/properties/details", property="https://www.immobiliare.it/annunci/132732166/")
    assert by_link["id"] == 132732166
    call("/immobiliare-it/properties/details", status=404, property="99999999")


def test_properties_search():
    body = call("/immobiliare-it/properties/search", location="Rome")
    assert body["count"] > 1000 and body["total_pages"] == 80 and len(body["results"]) == 25 and body["next"]
    assert body["location"]["key"] == "city:6737"
    first = body["results"][0]
    assert first["id"] and first["link"] and first["price"]["currency"] == "EUR"
    rentals = call("/immobiliare-it/properties/search", location="Milan", contract="rent", min_rooms=2, sort="price_asc")
    prices = [r["price"]["amount"] for r in rentals["results"] if r["price"]["amount"]]
    assert prices == sorted(prices) and all(r["contract"] == "rent" for r in rentals["results"])
    zone = call("/immobiliare-it/properties/search", location="city:8042/macrozone:10046", property_type="apartment")
    assert zone["count"] and zone["location"]["key"] == "city:8042/macrozone:10046"
    link = call("/immobiliare-it/properties/search",
                location="https://www.immobiliare.it/vendita-case/milano/centro/?prezzoMassimo=500000")
    assert link["count"] and all((r["price"]["amount"] or 0) <= 500000 for r in link["results"])
    call("/immobiliare-it/properties/search", status=404, location="zzzzqqqqxxx")
    call("/immobiliare-it/properties/search", status=400, location="Rome", page=81)


def test_properties_search_by_area():
    # around the Colosseum, Rome
    body = call("/immobiliare-it/properties/search_by_area", area="41.8902,12.4922")
    assert body["count"] and body["area"]["type"] == "radius" and body["area"]["radius_m"] == 1000 and body["results"]
    polygon = call("/immobiliare-it/properties/search_by_area", area="45.47,9.17;45.49,9.17;45.49,9.20;45.47,9.20")
    assert polygon["count"] and polygon["area"]["type"] == "polygon"
    call("/immobiliare-it/properties/search_by_area", status=400)
    call("/immobiliare-it/properties/search_by_area", status=400, area="41.8902,12.4922;41.89,12.49")


# ---- places ---------------------------------------------------------------------------

def test_locations_autocomplete():
    body = call("/immobiliare-it/locations/autocomplete", query="Venice")
    assert body["results"][0]["key"] == "city:12370" and body["results"][0]["zones"]
    call("/immobiliare-it/locations/autocomplete", status=400)


def test_locations_zones():
    body = call("/immobiliare-it/locations/zones", location="Rome")
    assert body["place"]["key"] == "city:6737" and body["zones_count"] > 20 and body["metro_lines"]
    call("/immobiliare-it/locations/zones", status=404, location="99999999")


# ---- agencies -------------------------------------------------------------------------

def test_agencies_search():
    body = call("/immobiliare-it/agencies/search", location="Rome")
    assert body["count"] > 1000 and len(body["results"]) == 25 and body["results"][0]["phones"]
    call("/immobiliare-it/agencies/search", status=404, location="zzzzqqqqxxx")


def test_agency_details():
    # Italy Sotheby's International Realty - Naples
    body = call("/immobiliare-it/agencies/details", agency="421127")
    assert body["id"] == 421127 and body["name"] and body["phones"] and body["listings_count"]
    call("/immobiliare-it/agencies/details", status=404, agency="1")


def test_agency_listings():
    body = call("/immobiliare-it/agencies/listings", agency="421127")
    assert body["count"] and len(body["results"]) == 25 and body["agency"]["id"] == 421127
    call("/immobiliare-it/agencies/listings", status=404, agency="1")


# ---- market ---------------------------------------------------------------------------

def test_market_prices():
    body = call("/immobiliare-it/market/prices", location="Florence")
    assert body["place"]["key"] == "city:11609" and body["prices"]["sale"]["average_per_m2"] and body["breakdown"]
    call("/immobiliare-it/market/prices", status=404, location="99999999")


def test_market_price_history():
    body = call("/immobiliare-it/market/price_history", location="Rome")
    assert body["count"] >= 90 and body["series"][-1]["average_per_m2"]
    rent = call("/immobiliare-it/market/price_history", location="Rome", contract="rent")
    assert rent["series"][-1]["average_per_m2"] < body["series"][-1]["average_per_m2"]
