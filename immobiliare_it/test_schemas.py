"""Offline tests for the /immobiliare-it/* request schemas and the filter
-> site query mapping.

    python -m pytest immobiliare_it/test_schemas.py -q
"""
import os
import sys

import pytest
from marshmallow import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from immobiliare_it import api, refs, schemas  # noqa: E402


def _errors(schema, data):
    with pytest.raises(ValidationError) as info:
        schema().load(data)
    return info.value.messages


def test_locations_autocomplete_schema():
    loaded = schemas.LocationsAutocompleteSchema().load({"query": " Mila "})
    assert loaded == {"query": "Mila", "limit": 10, "language": "en"}
    assert schemas.LocationsAutocompleteSchema().load({"query": "x", "limit": "20", "language": "DE"})["language"] == "de"
    assert "query" in _errors(schemas.LocationsAutocompleteSchema, {})
    assert "limit" in _errors(schemas.LocationsAutocompleteSchema, {"query": "x", "limit": "21"})
    assert "language" in _errors(schemas.LocationsAutocompleteSchema, {"query": "x", "language": "it"})


def test_locations_zones_schema():
    assert schemas.LocationsZonesSchema().load({"location": "8042"})["location"] == "8042"
    assert schemas.LocationsZonesSchema().load({"location": "Milano"})["location"] == "Milano"
    assert "location" in _errors(schemas.LocationsZonesSchema, {"location": ""})


def test_properties_search_accepts_name_key_and_link():
    for value in ("Milano", "Navigli, Milano", "8042", "city:8042", "city:8042/macrozone:10046", "region:lom/province:MI",
                  "https://www.immobiliare.it/vendita-case/milano/centro/?prezzoMassimo=500000&pag=2",
                  "https://www.immobiliare.it/en/search-list/?idComune=8042&idContratto=1"):
        loaded = schemas.PropertiesSearchSchema().load({"location": value})
        assert loaded["location"] == value and loaded["page"] == 1 and loaded["contract"] == "sale"
        assert loaded["category"] == "residential" and loaded["language"] == "en"


def test_properties_search_filters_map_to_the_site():
    loaded = schemas.PropertiesSearchSchema().load({
        "location": "Milano", "contract": "Rent", "category": "residential", "property_type": "apartment, penthouse",
        "min_price": "800", "max_price": "1500", "min_size": "50", "max_size": "120", "min_rooms": "2", "max_rooms": "4",
        "min_bedrooms": "1", "bathrooms": "2", "condition": "excellent", "energy_rating": "high", "floor": "top,intermediate",
        "garage": "single_garage", "heating": "autonomous", "outdoor": "terrace", "garden": "private", "ownership": "full",
        "lift": "true", "cellar": "1", "pool": "no", "furnished": "yes", "luxury": "false", "virtual_tour": "true",
        "exclude_auctions": "true", "private_only": "true", "investment": "true", "students": "true", "pets": "true",
        "keyword": "terrazzo", "sort": "price_asc", "page": "3", "language": "fr"})
    assert loaded["property_type"] == ["apartment", "penthouse"] and loaded["floor"] == ["top", "intermediate"]
    assert loaded["lift"] is True and loaded["pool"] is False and loaded["page"] == 3 and loaded["language"] == "fr"
    query = api._filter_params(loaded)
    assert query == {
        "idTipologia[]": ["4", "5"], "prezzoMinimo": "800", "prezzoMassimo": "1500", "superficieMinima": "50",
        "superficieMassima": "120", "localiMinimo": "2", "localiMassimo": "4", "camereDaLettoMinimo": "1", "bagni": "2",
        "stato": "6", "classeEnergetica": "2", "fasciaPiano[]": ["30", "20"], "boxAuto[]": ["1"], "riscaldamenti[]": ["1"],
        "balconeOterrazzo[]": ["terrazzo"], "giardino[]": ["10"], "tipoProprieta[]": ["1"], "ascensore": "1", "cantina": "1",
        "arredato": "1", "virtualTour": "1", "noAste": "1", "noAgenzie": "1", "aReddito": "1", "perStudenti": "1",
        "animali": "1", "keyword[]": ["terrazzo"], "criterio": "prezzo", "ordine": "asc",
    }
    assert api._filter_params({}) == {}
    assert api._filter_params({"sort": "relevance"}) == {}


def test_properties_search_rejections():
    assert "location" in _errors(schemas.PropertiesSearchSchema, {})
    assert "location" in _errors(schemas.PropertiesSearchSchema, {"location": "https://example.com/x"})
    assert "page" in _errors(schemas.PropertiesSearchSchema, {"location": "Milano", "page": str(refs.MAX_PAGES + 1)})
    assert "page" in _errors(schemas.PropertiesSearchSchema, {"location": "Milano", "page": "0"})
    assert "contract" in _errors(schemas.PropertiesSearchSchema, {"location": "Milano", "contract": "lease"})
    assert "category" in _errors(schemas.PropertiesSearchSchema, {"location": "Milano", "category": "castles"})
    assert "property_type" in _errors(schemas.PropertiesSearchSchema, {"location": "Milano", "property_type": "igloo"})
    assert "max_price" in _errors(schemas.PropertiesSearchSchema, {"location": "Milano", "min_price": "9", "max_price": "1"})
    assert "max_rooms" in _errors(schemas.PropertiesSearchSchema, {"location": "Milano", "min_rooms": "5", "max_rooms": "2"})
    assert "bathrooms" in _errors(schemas.PropertiesSearchSchema, {"location": "Milano", "bathrooms": "9"})
    assert "sort" in _errors(schemas.PropertiesSearchSchema, {"location": "Milano", "sort": "cheapest"})
    assert "lift" in _errors(schemas.PropertiesSearchSchema, {"location": "Milano", "lift": "maybe"})
    assert "keyword" in _errors(schemas.PropertiesSearchSchema, {"location": "Milano", "keyword": "x" * 61})
    messages = _errors(schemas.PropertiesSearchSchema, {"location": "Milano", "url": "x"})
    assert messages == {"url": ["Unknown field."]}


def test_properties_search_by_area_schema():
    polygon = schemas.PropertiesSearchByAreaSchema().load({"area": "45.47,9.17; 45.49,9.17 ;45.49,9.20"})
    assert polygon["area"] == {"type": "polygon", "points": [[45.47, 9.17], [45.49, 9.17], [45.49, 9.2]]}
    assert polygon["radius_m"] is None and polygon["page"] == 1
    radius = schemas.PropertiesSearchByAreaSchema().load({"area": " 41.8902 , 12.4922 ", "radius_m": "800", "contract": "rent"})
    assert radius["area"] == {"type": "radius", "lat": 41.8902, "lng": 12.4922}
    assert radius["radius_m"] == 800 and radius["contract"] == "rent"
    assert _errors(schemas.PropertiesSearchByAreaSchema, {}) == {"area": ["Missing data for required field."]}
    assert "area" in _errors(schemas.PropertiesSearchByAreaSchema, {"area": ""})
    assert _errors(schemas.PropertiesSearchByAreaSchema, {"area": "45,9;45.1,9.1"}) == {"area": [
        "Give one point 'lat,lng' (a radius search around it) or at least 3 points 'lat,lng;lat,lng;lat,lng' (a polygon)."]}
    assert "area" in _errors(schemas.PropertiesSearchByAreaSchema, {"area": "95,9"})
    assert "area" in _errors(schemas.PropertiesSearchByAreaSchema, {"area": "Rome"})
    assert "radius_m" in _errors(schemas.PropertiesSearchByAreaSchema, {"area": "45,9", "radius_m": "99999"})
    assert _errors(schemas.PropertiesSearchByAreaSchema, {"area": "45,9;45,9.1;45.1,9", "radius_m": "500"}) == {
        "radius_m": ["radius_m applies to a one-point area 'lat,lng', not to a polygon."]}
    assert _errors(schemas.PropertiesSearchByAreaSchema, {"area": "45,9", "lat": "45"}) == {"lat": ["Unknown field."]}


def test_area_maps_to_the_site(monkeypatch):
    seen = {}

    def fake_fetch(params):
        seen.update(params)
        return {"count": 0, "results": [], "maxPages": 0}

    monkeypatch.setattr(api, "fetch_search", fake_fetch)
    radius = api._properties_search_by_area({"type": "radius", "lat": 41.8902, "lng": 12.4922}, "sale", "residential", 1, "en")
    assert seen["centro"] == "41.8902,12.4922" and seen["raggio"] == "1000" and "vrt" not in seen
    assert radius["area"] == {"type": "radius", "lat": 41.8902, "lng": 12.4922, "radius_m": 1000}
    seen.clear()
    polygon = api._properties_search_by_area({"type": "polygon", "points": [[45.47, 9.17], [45.49, 9.17], [45.49, 9.2]]},
                                             "rent", "residential", 2, "en", lift=True)
    assert seen["vrt"] == "45.47,9.17;45.49,9.17;45.49,9.2" and seen["idContratto"] == "2" and seen["ascensore"] == "1"
    assert seen["pag"] == 2 and "centro" not in seen
    assert polygon["area"]["points"][0] == {"lat": 45.47, "lng": 9.17}


def test_property_details_schema():
    for value in ("128951952", "https://www.immobiliare.it/annunci/128951952/", "https://www.immobiliare.it/fr/annunci/128951952/?x=1"):
        assert schemas.PropertyDetailsSchema().load({"property": value})["property"] == 128951952
    assert _errors(schemas.PropertyDetailsSchema, {"property": "abc"}) == {
        "property": ["Must be an immobiliare.it listing id (128951952) or a listing link."]}
    assert "property" in _errors(schemas.PropertyDetailsSchema, {"property": "https://www.immobiliare.it/vendita-case/milano/"})
    assert "property" in _errors(schemas.PropertyDetailsSchema, {})


def test_agencies_search_schema():
    for value in ("Milano", "Roma provincia", "8042", "city:8042", "region:lom/province:MI",
                  "https://www.immobiliare.it/agenzie-immobiliari/milano/?pag=3"):
        assert schemas.AgenciesSearchSchema().load({"location": value})["location"] == value
    assert "page" in _errors(schemas.AgenciesSearchSchema, {"location": "Milano", "page": str(refs.AGENCIES_MAX_PAGES + 1)})
    assert "location" in _errors(schemas.AgenciesSearchSchema, {})


def test_agency_schemas():
    for value in ("385732", "https://www.immobiliare.it/agenzie-immobiliari/385732/formula-pomezia-roma/",
                  "https://www.immobiliare.it/en/imprese-edili/385732/"):
        assert schemas.AgencyDetailsSchema().load({"agency": value})["agency"] == 385732
        assert schemas.AgencyListingsSchema().load({"agency": value})["agency"] == 385732
    assert _errors(schemas.AgencyDetailsSchema, {"agency": "https://www.immobiliare.it/agenzie-immobiliari/milano/"}) == {
        "agency": ["Not an immobiliare.it agency link (expected …/agenzie-immobiliari/<id>/…)."]}
    loaded = schemas.AgencyListingsSchema().load({"agency": "385732", "sort": "Newest", "page": "2"})
    assert loaded["sort"] == "newest" and loaded["page"] == 2
    assert "sort" in _errors(schemas.AgencyListingsSchema, {"agency": "385732", "sort": "size_asc"})


def test_market_schemas():
    for value in ("Italia", "country:IT", "region:lom", "region:lom/province:MI", "8042", "city:8042/macrozone:10046",
                  "https://www.immobiliare.it/mercato-immobiliare/lombardia/milano/in-via-san-calimero/"):
        assert schemas.MarketPricesSchema().load({"location": value})["location"] == value
        assert schemas.MarketPriceHistorySchema().load({"location": value})["contract"] == "sale"
    assert schemas.MarketPriceHistorySchema().load({"location": "8042", "contract": "RENT"})["contract"] == "rent"
    assert "contract" in _errors(schemas.MarketPriceHistorySchema, {"location": "8042", "contract": "auction"})
    assert "language" in _errors(schemas.MarketPricesSchema, {"location": "8042", "language": "it"})


def test_pick_place_prefers_an_exact_town():
    import json
    fx = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
    with open(os.path.join(fx, "autocomplete_milano.json"), encoding="utf-8") as f:
        from immobiliare_it import parsers
        milano = parsers.parse_autocomplete(json.load(f))
    assert api.pick_place(milano, "Milano")["key"] == "city:8042"      # slug match (label is "Milan")
    assert api.pick_place(milano, "milan")["key"] == "city:8042"
    assert api.pick_place(milano, "Centro")["type"] == "macrozone"     # exact zone name

    def place(type_, id_, name, slug, parents=()):
        return {"type": type_, "id": id_, "name": name, "slug": slug,
                "parents": [{"type": t, "id": i, "name": n, "slug": s} for t, i, n, s in parents]}

    rome_results = [
        place("macrozone", "34154", "Rometta Marea", "rometta-marea", [("city", "11046", "Rometta", "Rometta")]),
        place("macrozone", "1", "Rome", "roma", [("city", "2", "Borgo Mantovano", "Borgo_Mantovano")]),
        place("city", "6737", "Rome", "Roma", [("province", "RM", "Rome", "Roma"), ("region", "laz", "Lazio", "Lazio")]),
    ]
    assert api.pick_place(rome_results, "Rome")["id"] == "6737"         # town before a same-name zone
    assert api.pick_place(rome_results, "ROMA")["id"] == "6737"
    assert api.pick_place(rome_results, "Rometta")["id"] == "34154"     # no exact match: the site's first
    trastevere = [
        place("region", "emr", "Emilia Romagna", "Emilia_Romagna"),
        place("microzone", "11", "Trastevere", "trastevere", [("macrozone", "10", "Testaccio, Trastevere", "testaccio-trastevere"),
                                                               ("city", "6737", "Rome", "Roma")]),
    ]
    assert api.pick_place(trastevere, "Trastevere, Roma")["id"] == "11"  # zone + its town
    cortina = [place("city", "12025", "Cortina d'Ampezzo", "Cortina_d_Ampezzo")]
    assert api.pick_place(cortina, "cortina d’ampezzo")["id"] == "12025"
    assert api.pick_place([place("metro_station", "1", "Duomo", "duomo")], "Duomo") is None
    assert api.pick_place([], "x") is None


def test_pagination_block():
    assert api._pagination(19268, 1, 25, 80) == {"page": 1, "items_per_page": 25, "total_pages": 80, "total_count": 19268}
    assert api._pagination(53, 2, 25, 80) == {"page": 2, "items_per_page": 25, "total_pages": 3, "total_count": 53}
    assert api._pagination(0, 1, 25, 80)["total_pages"] == 0
    assert api._pagination(None, 9, 25, 80) == {"page": 9, "items_per_page": 25, "has_next": False, "total_pages": None,
                                                 "total_count": None}
    assert api._pagination(2328, 94, 25) == {"page": 94, "items_per_page": 25, "total_pages": 94, "total_count": 2328}
