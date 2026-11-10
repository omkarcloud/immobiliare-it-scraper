"""Offline tests for the immobiliare.it parsers, reference resolvers and
value helpers.

    python -m pytest immobiliare_it/test_parsers.py -q

Fixtures are real www.immobiliare.it answers captured 2026-11-07
(immobiliare_it/fixtures/, see parsers.py's docstring). No network.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from immobiliare_it import parsers as P, refs  # noqa: E402
from immobiliare_it import fetch as F  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return json.load(f) if name.endswith(".json") else f.read()


@pytest.fixture(scope="module")
def milano():
    return P.parse_search(fixture("search_sale_milano_p1.json"), "en")


@pytest.fixture(scope="module")
def apartment():
    return P.parse_detail(P.next_data(fixture("detail_apartment_128951952.html")), "en")


# ---- value helpers -----------------------------------------------------------------------

def test_number_in():
    assert P._number_in("85 m²") == 85
    assert P._number_in("€ 300,000") == 300000
    assert P._number_in("3,529 €/m²") == 3529
    assert P._number_in("22,52 €/m²") == 22.52
    assert P._number_in("€ 195,000.00") == 195000
    assert P._number_in("€ 1.351.500") == 1351500
    assert P._number_in("€ 250/month") == 250
    assert P._number_in(None) is None and P._number_in("n/a") is None
    assert P._number_in(42) == 42


def test_dates():
    assert P._iso_date(1778324554) == "2026-05-09"
    assert P._iso_datetime(1778324554) == "2026-05-09T11:02:34Z"
    assert P._us_date("12/15/2026, 9:00 AM") == "2026-12-15"
    assert P._us_date(None) is None and P._iso_date(None) is None


def test_phones():
    phones = P._phones([{"type": "vtel", "value": "06 8587 1955", "formattedValues": "+390685871955", "isVirtual": True},
                        {"type": "cell", "value": "338 775 7664", "formattedValues": "3387757664", "isVirtual": False},
                        {"type": "vTel1", "value": "02 8126 6404"}, {"type": "tel1", "value": ""}])
    assert phones == [
        {"number": "06 8587 1955", "international": "+390685871955", "type": "virtual", "is_virtual": True},
        {"number": "338 775 7664", "international": "3387757664", "type": "mobile", "is_virtual": False},
        {"number": "02 8126 6404", "international": None, "type": "virtual", "is_virtual": True},
    ]


# ---- search JSON ---------------------------------------------------------------------------

def test_search_milano(milano):
    assert milano["total"] == 19268 and milano["max_pages"] == 771 and milano["page"] == 1
    assert milano["title"] == "Houses for sale in Milan"
    assert milano["link"] == "https://www.immobiliare.it/en/vendita-case/milano/"
    assert milano["place"]["city"]["name"] == "Milan"
    assert len(milano["zones"]) == 32 and milano["zones"][0]["name"] == "Abbiategrasso, Chiesa Rossa"
    assert len(milano["results"]) == 25 and not milano["past_end"]


def test_search_card(milano):
    card = next(c for c in milano["results"] if c["id"] == 128951952)
    assert card["link"] == "https://www.immobiliare.it/en/annunci/128951952/"
    assert card["title"].startswith("3-room flat via Giuseppe Avezzana")
    assert card["contract"] == "sale" and card["listing_type"] == "ad" and card["is_project"] is False
    assert card["price"] == {"amount": 300000, "currency": "EUR", "formatted": "€ 300,000", "is_visible": True,
                             "range": "200.001 - 300.000 €"}
    assert card["surface_m2"] == 85 and card["rooms"] == "3" and card["bedrooms"] == 2 and card["bathrooms"] == 1
    assert card["floor"] == {"label": "2°, with lift", "number": 2} and card["has_lift"] is True
    assert card["location"]["latitude"] == 45.4392 and card["location"]["macrozone"] == "Corvetto, Rogoredo"
    assert card["location"]["city"] == "Milan" and card["location"]["country_code"] == "IT"
    assert card["photo"].endswith("/1981597222/xxl.jpg") and card["photos_count"] == 26
    assert card["agency"]["id"] == 106554 and card["agency"]["phones"][0]["number"] == "02 8126 6404"
    assert card["agent"]["name"] == "Fabio De Paola"
    assert "cantina" in card["features"]
    assert {f["type"] for f in card["main_features"]} >= {"rooms", "surface", "bathrooms"}


def test_search_project_card(milano):
    card = next(c for c in milano["results"] if c["is_project"])
    assert card["listing_type"] == "project" and card["units_count"] == 23 and len(card["units"]) == 23
    assert card["price"]["min_amount"] == 368500 and card["price"]["max_amount"] == 1351500
    unit = card["units"][0]
    assert unit["property_type"] == "2-room flat" and unit["price"]["amount"] == 368500 and unit["surface_m2"] == 63


def test_search_other_verticals():
    rent = P.parse_search(fixture("search_rent_roma_p1.json"), "en")
    assert rent["total"] == 5997 and rent["results"][0]["contract"] == "rent"
    assert rent["results"][0]["price"]["period"] == "month"
    auction = P.parse_search(fixture("search_auction_milano.json"), "en")
    assert auction["results"][0]["contract"] == "auction" and auction["results"][0]["listing_type"] == "auction"
    rooms = P.parse_search(fixture("search_rooms_milano.json"), "en")
    assert rooms["results"][0]["category"] == "Room"
    offices = P.parse_search(fixture("search_offices_milano.json"), "en")
    assert offices["results"][0]["category"].startswith("Offices")
    polygon = P.parse_search(fixture("search_polygon_milano.json"), "en")
    assert polygon["total"] == 1189 and polygon["max_pages"] == 48
    italian = P.parse_search(fixture("search_sale_milano_p1_it.json"), "it")
    assert italian["title"] == "Case in vendita a Milano"


def test_search_sparse_pages():
    zero = P.parse_search(fixture("search_zero_results.json"), "en")
    assert zero["total"] == 0 and zero["results"] == [] and zero["max_pages"] == 0
    past = P.parse_search({"results": [], "count": None, "maxPages": None, "pastEnd": True}, "en")
    assert past["total"] is None and past["past_end"] is True and past["results"] == []
    assert P.parse_search(None)["results"] == []


def test_search_page_resolves_a_link():
    page = P.parse_search_page(fixture("list_page_en_centro_filtered.html"))
    assert page["params"] == {"fkRegione": "lom", "idProvincia": "MI", "idComune": "8042", "idMZona": ["10046"],
                              "idContratto": "1", "idCategoria": "1", "prezzoMassimo": "500000", "criterio": "prezzo",
                              "ordine": "desc"}
    assert page["page"] == 1 and page["payload"]["count"] == 53
    page2 = P.parse_search_page(fixture("list_page_en_milano_p2.html"))
    assert page2["page"] == 2 and page2["params"]["idComune"] == "8042"
    assert P.parse_search_page(fixture("list_page_en_not_found.html")) is None
    assert P.parse_search_page(fixture("agency_page_385732.html")) is None


# ---- detail pages ---------------------------------------------------------------------------

def test_detail_apartment(apartment):
    d = apartment
    assert d["id"] == 128951952 and d["property_type"] == "Apartment" and d["status"] == "active"
    assert d["created_at"] == "2026-05-09T11:02:34Z" and d["updated_at"] == "2026-10-29T12:21:13Z"
    assert d["reference"] == "trilo320viaavezzana" and d["build_year"] == 1960 and d["building_floors"] == 6
    assert d["price"]["per_m2"] == 3529 and d["kitchen"] == "Kitchenette"
    assert d["condition"] == "Good condition / Liveable"
    assert d["energy"]["class"] == "G" and d["energy"]["heating"].startswith("central")
    assert d["costs"]["condominium_fees"] == 250 and d["costs"]["condominium_fees_period"] == "month"
    assert d["location"]["address"] == "Via Giuseppe Avezzana" and d["location"]["street_number"] == "14"
    assert len(d["photos"]) == 26 and d["photos"][0]["room"] == "Facade"
    assert d["videos"] == [{"id": 41688050, "link": "https://youtube.com/embed/1GMMMPbmx8w"}]
    assert len(d["floor_plans"]) == 2 and d["virtual_tours"][0]["link"].startswith("https://my.matterport.com/")
    assert d["mortgage"]["estimated_monthly_payment"] == 907 and d["mortgage"]["rates_by_loan_to_value"][0]["loan_to_value_pct"] == 50
    assert d["surface_constitution"]["total_main_surface_m2"] == 85
    assert "Security door" in d["features"] and "cantina" in d["features_original"]
    assert d["description_original"].startswith("Nel cuore") and d["description"].startswith("In the heart")
    assert d["keywords"] and d["rent"] is None and d["auction"] is None
    assert d["agency"]["opening_hours"][0]["weekday"] == 1


def test_detail_project_units():
    d = P.parse_detail(P.next_data(fixture("detail_project_121232008.html")), "en")
    assert d["is_project"] and d["units_count"] == 15 and len(d["units"]) == 15
    assert d["project"]["residential_units"] == 99 and d["project"]["work_dates"] == "05/01/2025 - 12/31/2027"
    assert d["units"][0]["id"] == 24213086 and d["units"][0]["reference"] == "E2.2"
    assert d["units"][0]["price"]["per_m2"] == 6190


def test_detail_rent_and_auction():
    rent = P.parse_detail(P.next_data(fixture("detail_rent_134342929.html")), "en")
    assert rent["contract"] == "rent" and rent["contract_label"] == "Rent, 4+4"
    assert rent["price"]["amount"] == 12000 and rent["price"]["period"] == "month" and rent["price"]["per_m2"] == 47
    assert rent["rent"]["is_available_to_students"] is False and rent["costs"]["heating_expenses"] == "€ 1/year"
    auction = P.parse_detail(P.next_data(fixture("detail_auction_133539596.html")), "en")
    assert auction["contract"] == "auction" and auction["listing_type"] == "auction"
    assert auction["auction"]["sale_date"] == "2026-12-15" and auction["auction"]["minimum_offer"] == 195000
    assert auction["auction"]["sale_state"] == "Open to participate" and auction["auction"]["is_open"] is True
    assert auction["auction"]["published_at"] == "2026-10-14" and auction["auction"]["lots_count"] == 1


def test_detail_other_language():
    de = P.parse_detail(P.next_data(fixture("detail_de_128951952.html")), "de")
    assert de["id"] == 128951952 and de["link"] == "https://www.immobiliare.it/de/annunci/128951952/"
    assert de["property_type"] == "Wohnung"


def test_detail_not_found_and_garbage():
    html = fixture("detail_not_found.html")
    assert P.is_not_found_page(html) and P.next_data(html) is None
    with pytest.raises(ValueError):
        P.parse_detail(P.next_data(html), "en")
    with pytest.raises(ValueError):
        P.parse_detail({"props": {"pageProps": {"detailData": {"realEstate": {}}}}}, "en")
    # the card parser never crashes on a partial record
    assert P.parse_card({"realEstate": {"id": 1}}, "en")["link"] == "https://www.immobiliare.it/en/annunci/1/"
    assert P.parse_card({"realEstate": None}) is None


# ---- agencies -------------------------------------------------------------------------------

def test_agencies_search():
    parsed = P.parse_agencies(fixture("agencies_search_milano_p1.json"))
    assert parsed["total"] == 2328 and parsed["title"] == "real estate agencies in Milan"
    assert parsed["link"] == "https://www.immobiliare.it/en/agenzie-immobiliari/milano/"
    row = parsed["results"][0]
    assert row["id"] == 83565 and row["name"] == "CFC Immobiliare" and row["partnership"] == "Fiaip"
    assert row["listings_count"] == 161 and row["sold_count"] == 146 and row["quality_index"] == 92
    assert row["badge"] == "gold" and row["is_highlighted"] is True and row["years_on_site"] == 14
    assert row["phones"][1] == {"number": "02 2897 0540", "international": "+390228970540", "type": "landline", "is_virtual": False}
    assert row["location"]["latitude"] == 45.4929 and row["location"]["macrozone"] == "Udine, Lambrate"
    past = P.parse_agencies(fixture("agencies_search_past_end.json"))
    assert past["total"] == 2328 and past["results"] == []
    assert P.parse_agencies(None)["results"] == []


def test_agencies_page_resolves_a_link():
    page = P.parse_agencies_page(fixture("agencies_list_page_en_roma_provincia.html"))
    assert page["params"] == {"nationId": "IT", "regionId": "laz", "provinceId": "RM"} and page["page"] == 2
    milan = P.parse_agencies_page(fixture("agencies_list_page_en_milano.html"))
    assert milan["params"]["cityId"] == "8042" and milan["page"] == 1 and milan["payload"]["count"] == 2328
    assert P.parse_agencies_page(fixture("agencies_list_page_en_not_found.html")) is None


def test_agency_page():
    parsed = P.parse_agency(P.next_data(fixture("agency_page_385732.html")))
    profile = parsed["profile"]
    assert profile["id"] == 385732 and profile["name"] == "Formula Immobiliare SRLS" and profile["slug"] == "formula-pomezia-roma"
    assert profile["address"] == "Piazza Italia 8 00071 - Pomezia" and profile["listings_count"] == 27
    assert len(profile["phones"]) == 3 and profile["phones"][2]["type"] == "landline"
    assert profile["opening_hours"][0] == {"weekday": 1, "hours": [["09:00", "13:00"], ["16:00", "19:30"]]}
    assert profile["location"]["city"] == {"id": "6725", "name": "Pomezia", "slug": "pomezia"}
    assert profile["location"]["latitude"] == 41.6214 and profile["directory"]["city"]["name"] == "Pomezia"
    assert parsed["listing"]["total"] == 27 and len(parsed["listing"]["results"]) == 25 and parsed["listing_page"] == 1
    big = P.parse_agency(P.next_data(fixture("agency_page_83565_p2.html")))
    assert big["profile"]["website"] == "https://www.cfcimmobiliare.it" and len(big["profile"]["agents"]) > 3
    assert big["listing_page"] == 2
    builder = P.parse_agency(P.next_data(fixture("agency_page_builder_439495.html")))
    assert builder["profile"]["id"] == 439495 and builder["profile"]["type"] in ("constructor", "agency")


def test_agency_unknown_id_is_the_home_page():
    with pytest.raises(ValueError):
        P.parse_agency(P.next_data(fixture("agency_page_not_found_1.html")))
    with pytest.raises(ValueError):
        P.parse_agency(None)


def test_agency_listing_json():
    parsed = P.parse_agency_listing(fixture("agency_listing_385732_p1.json"), "en")
    assert parsed["total"] == 27 and len(parsed["results"]) == 25 and parsed["results"][0]["agency"]["id"] == 385732
    page2 = P.parse_agency_listing(fixture("agency_listing_385732_p2.json"), "en")
    assert page2["total"] == 27 and len(page2["results"]) == 2
    unknown = P.parse_agency_listing(fixture("agency_listing_unknown.json"), "en")
    assert unknown["total"] == 0 and unknown["results"] == []


# ---- places ----------------------------------------------------------------------------------

def test_autocomplete():
    results = P.parse_autocomplete(fixture("autocomplete_milano.json"), 5)
    assert len(results) == 5
    milan = results[0]
    assert milan["key"] == "city:8042" and milan["type"] == "city" and milan["name"] == "Milan"
    assert milan["latitude"] == 45.4637 and milan["is_admin_centre"] is True
    assert [p["key"] for p in milan["parents"]] == ["province:MI", "region:lom", "country:IT"]
    assert milan["zones"][0]["name"] == "Centro" and milan["zones"][0]["microzones"][2]["name"] == "Duomo"
    assert P.place_chain(fixture("autocomplete_milano.json")[0]) == {"city": "8042", "province": "MI", "region": "lom", "country": "IT"}
    assert P.parse_autocomplete(fixture("autocomplete_empty.json")) == []
    street = P.parse_autocomplete(fixture("autocomplete_via.json"), 3)
    assert street[0]["type"] == "city" and street[0]["name"] == "Turin"


def test_geography_lists():
    tree = P.parse_geography_lists(fixture("geography_lists_milano_zones.json"), fixture("geography_lists_milano_metro.json"))
    assert tree["place"]["key"] == "city:8042" and tree["place"]["parents"][0]["key"] == "province:MI"
    assert len(tree["zones"]) == 32 and tree["zones"][0]["name"] == "Centro" and len(tree["zones"][0]["microzones"]) == 10
    assert len(tree["metro_lines"]) == 5 and tree["metro_lines"][0]["name"] == "Linea M1 Rossa"
    station = tree["metro_lines"][0]["stations"][0]
    assert station["key"] == "metro_station:1166" and station["latitude"] == 45.4554
    pomezia = P.parse_geography_lists(fixture("geography_lists_pomezia_zones.json"))
    assert pomezia["place"]["name"] == "Pomezia" and pomezia["metro_lines"] == []


# ---- market ----------------------------------------------------------------------------------

def test_market_city_page():
    m = P.parse_market_page(fixture("market_city_milano.html"))
    assert m["title"] == "Quotazioni immobiliari nel comune di Milano"
    assert m["link"] == "https://www.immobiliare.it/mercato-immobiliare/lombardia/milano/"
    assert m["place"]["key"] == "city:8042" and m["place"]["type"] == "city" and m["place"]["parents"][0]["id"] == "MI"
    assert m["period"] == "2026-10-01"
    assert m["prices"]["sale"] == {"average_per_m2": 5667.0, "min_per_m2": 3306.0, "max_per_m2": 11094.0,
                                   "average_per_m2_last_year": 5572.0, "change_pct_year": 1.7, "currency": "EUR",
                                   "period": "2026-10-01"}
    assert m["prices"]["rent"]["average_per_m2"] == 22.52
    levels = {b["level"]: b for b in m["breakdown"]}
    assert len(levels["macrozone"]["items"]) == 32 and levels["macrozone"]["items"][0]["name"] == "Centro"
    assert levels["macrozone"]["items"][0]["sale_per_m2"] == 11094.0 and levels["macrozone"]["items"][0]["sale_change_pct_year"] == -0.81
    assert len(levels["address"]["items"]) == 84


def test_market_other_levels():
    italy = P.parse_market_page(fixture("market_italy.html"))
    assert italy["place"]["type"] == "country" and [b["level"] for b in italy["breakdown"]] == ["region", "capitals"]
    region = P.parse_market_page(fixture("market_region_lombardia.html"))
    assert region["place"]["key"] == "region:lom" and region["breakdown"][0]["level"] == "province"
    province = P.parse_market_page(fixture("market_province_milano.html"))
    assert province["place"]["key"] == "province:MI" and len(province["breakdown"][0]["items"]) == 133
    zone = P.parse_market_page(fixture("market_zone_centro.html"))
    assert zone["place"]["key"] == "macrozone:10046" and zone["breakdown"][0]["level"] == "microzone"
    street = P.parse_market_page(fixture("market_street_san_calimero.html"))
    assert street["place"]["type"] == "street" and street["place"]["key"] is None and street["breakdown"] == []
    assert street["prices"]["sale"]["average_per_m2"] == 9476.0 and street["prices"]["sale"]["change_pct_year"] is None
    english = P.parse_market_page(fixture("market_city_milano_en.html"))
    assert english["title"] == "Housing prices in the municipality of Milan"
    with pytest.raises(ValueError):
        P.parse_market_page(fixture("market_not_found.html"))
    with pytest.raises(ValueError):
        P.parse_market_page("<html></html>")


def test_price_history():
    h = P.parse_price_history(fixture("price_history_milano_sale.json"))
    assert h["title"] == "Prezzi case in vendita" and h["place_label"] == "Milano"
    assert h["link"] == "https://www.immobiliare.it/mercato-immobiliare/lombardia/milano/"
    assert len(h["series"]) == 100 and h["series"][0]["month"] == "2018-07" and h["series"][-1] == {"month": "2026-10", "average_per_m2": 5667.0}
    rent = P.parse_price_history(fixture("price_history_milano_rent.json"))
    assert rent["series"][-1]["average_per_m2"] == 22.52
    assert P.parse_price_history(fixture("price_history_unknown_422.json"))["series"] == []


# ---- refs ------------------------------------------------------------------------------------

def test_resolve_property():
    assert refs.resolve_property("128951952") == 128951952
    assert refs.resolve_property("https://www.immobiliare.it/annunci/128951952/") == 128951952
    assert refs.resolve_property("https://www.immobiliare.it/en/annunci/128951952/?utm=x") == 128951952
    assert refs.resolve_property("immobiliare.it/de/annunci/128951952") == 128951952
    for bad in ("abc", "https://www.immobiliare.it/vendita-case/milano/", "https://example.com/annunci/1/"):
        with pytest.raises(ValueError):
            refs.resolve_property(bad)


def test_resolve_agency():
    assert refs.resolve_agency("385732") == 385732
    assert refs.resolve_agency("https://www.immobiliare.it/agenzie-immobiliari/385732/formula-pomezia-roma/") == 385732
    assert refs.resolve_agency("https://www.immobiliare.it/en/imprese-edili/439495/bliss-milano/") == 439495
    with pytest.raises(ValueError):
        refs.resolve_agency("https://www.immobiliare.it/agenzie-immobiliari/milano/")


def test_classify_location_and_keys():
    assert refs.classify_location("Milano") == ("name", "Milano")
    assert refs.classify_location("8042") == ("key", {"city": "8042"})
    assert refs.classify_location("city:8042/macrozone:10046") == ("key", {"city": "8042", "macrozone": "10046"})
    assert refs.classify_location("REGION:LOM/province:mi") == ("key", {"region": "lom", "province": "MI"})
    kind, (language, path, query) = refs.classify_location("https://www.immobiliare.it/en/vendita-case/milano/?pag=2")
    assert kind == "link" and language == "en" and path == "/vendita-case/milano/" and query == {"pag": "2"}
    assert refs.place_key("macrozone", "10046", {"city": "8042"}) == "city:8042/macrozone:10046"
    assert refs.place_key("province", "MI", {"region": "lom"}) == "region:lom/province:MI"
    assert refs.place_key("city", "8042", {"region": "lom"}) == "city:8042"
    assert refs.innermost({"region": "lom", "city": "8042"}) == "city"
    with pytest.raises(ValueError):
        refs.classify_location("x")
    with pytest.raises(ValueError):
        refs.classify_location("https://example.com/")


def test_polygon():
    assert refs.parse_polygon("45.47,9.17;45.49,9.17;45.49,9.20") == [(45.47, 9.17), (45.49, 9.17), (45.49, 9.2)]
    assert refs.polygon_param([(45.47, 9.17), (45.49, 9.2)]) == "45.47,9.17;45.49,9.2"
    for bad in ("45,9;45,9", "x;y;z", "95,9;45,9;45,9"):
        with pytest.raises(ValueError):
            refs.parse_polygon(bad)


def test_area():
    assert refs.parse_area("41.8902,12.4922") == {"type": "radius", "lat": 41.8902, "lng": 12.4922}
    assert refs.parse_area("-33.9, 151.2 ;") == {"type": "radius", "lat": -33.9, "lng": 151.2}
    assert refs.parse_area("45.47,9.17|45.49,9.17|45.49,9.20") == {
        "type": "polygon", "points": [[45.47, 9.17], [45.49, 9.17], [45.49, 9.2]]}
    for bad in ("", "45,9;45.1,9.1", "Rome", "41.8902", "95,9", "45,190"):
        with pytest.raises(ValueError):
            refs.parse_area(bad)


# ---- fetch classification ---------------------------------------------------------------------

def test_datadome_detection():
    assert F.is_datadome('<html><head><title>immobiliare.it</title></head><body><script src="https://ct.captcha-delivery.com/i.js">')
    assert F.is_datadome('{"url":"https://geo.captcha-delivery.com/interstitial/?initialCid=x"}')
    assert not F.is_datadome(fixture("detail_apartment_128951952.html")[:3000])
    with open(os.path.join(FX, "search_bad_param_422.json"), encoding="utf-8") as f:
        assert F._upstream_message(f.read()) == "energyEfficiencyId: This value should be of type int."
    assert F._upstream_message('{"error":"Bad Request"}') == "Bad Request"
    assert F._upstream_message("not json") is None


# ---- the identity ladder ----------------------------------------------------------------------

@pytest.fixture
def ladder(monkeypatch):
    """A fresh ladder state with three identities and a fallback exit."""
    monkeypatch.setattr(F, "_PROFILES", ["chrome", "firefox155", "chrome146"])
    monkeypatch.setattr(F, "_profile_index", 0)
    monkeypatch.setattr(F, "_blocked_until", 0.0)
    monkeypatch.setattr(F, "_direct_blocks", [])
    monkeypatch.setattr(F.config, "immobiliare_it_proxy", lambda: None)
    monkeypatch.setattr(F.config, "immobiliare_it_fallback_proxy", lambda: "http://fallback.example:1")
    monkeypatch.setattr(F.config, "IMMOBILIARE_IT_BLOCK_HOLD_S", 600)
    F._local.__dict__.clear()
    yield F
    F._local.__dict__.clear()


def test_available_profiles_follow_the_installed_curl_cffi():
    profiles = F.available_profiles(("chrome", "firefox155", "chrome999x", "firefox147"))
    assert profiles[0] == "chrome" and "chrome999x" not in profiles and "firefox147" in profiles
    assert F.available_profiles(("nope1", "nope2")) == ["chrome"]
    assert F.current_profile() in F.available_profiles()


def test_a_block_moves_the_ladder_once_per_refused_identity(ladder):
    assert ladder.current_profile() == "chrome"
    ladder._rotate_profile("chrome")
    ladder._rotate_profile("chrome")        # a second thread refused on the same identity
    assert ladder.current_profile() == "firefox155"
    ladder._rotate_profile("chrome146")     # not the current identity: no move
    assert ladder.current_profile() == "firefox155"


def _blocked_drop(F, profile, proxy=None):
    F._local.session, F._local.proxy, F._local.profile = None, proxy, profile
    F._drop_session(blocked=True)


def test_direct_tier_is_held_off_only_after_every_identity_was_refused(ladder):
    F = ladder
    _blocked_drop(F, "chrome")
    _blocked_drop(F, "firefox155")
    assert F._proxy() is None and F.current_profile() == "chrome146"     # still direct
    _blocked_drop(F, "chrome146")
    assert F._proxy() == "http://fallback.example:1"                       # all three refused
    assert F.current_profile() == "chrome"                                 # the ladder wrapped
    F._drop_session(blocked=False)                                         # a plain drop changes nothing
    assert F._proxy() == "http://fallback.example:1"


def test_proxy_tier_blocks_never_hold_off(ladder, monkeypatch):
    F = ladder
    for profile in ("chrome", "firefox155", "chrome146"):
        _blocked_drop(F, profile, proxy="http://exit.example:2")
    assert F._direct_blocks == [] and F._proxy() is None


def test_no_fallback_exit_means_no_hold(ladder, monkeypatch):
    F = ladder
    monkeypatch.setattr(F.config, "immobiliare_it_fallback_proxy", lambda: None)
    for profile in ("chrome", "firefox155", "chrome146"):
        _blocked_drop(F, profile)
    assert F._proxy() is None and F._blocked_until == 0.0
