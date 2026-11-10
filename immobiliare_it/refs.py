"""Reference resolvers, link parsing and the site's filter vocabularies for
/immobiliare-it/* (www.immobiliare.it, Italy's largest property portal).

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair):

    property   a numeric listing id (128951952) OR any listing link
               (…/annunci/<id>/, with or without a locale prefix)
    agency     a numeric agency id (385732) OR any agency link
               (…/agenzie-immobiliari/<id>/<slug>/, …/imprese-edili/<id>/…)
    location   a place name ("Milano", "Navigli, Milano"), a place key from
               locations/autocomplete ("city:8042", "macrozone:10046",
               "province:MI", "region:lom", a bare number = a city id) OR
               any immobiliare.it search / agencies / market link

Identifiers (captured 2026-11-07):
  * listing id   8-9 digits, the /annunci/<id>/ segment; `uuid` is a
                 secondary key the site never exposes in links
  * agency id    numeric, the first segment after /agenzie-immobiliari/ or
                 /imprese-edili/ (builders); the slug after it is optional
  * place ids    region = 3 letters (lom), province = 2 letters (MI),
                 city / macrozone / microzone / metro = digits; the
                 autocomplete's `type` tells the level (PLACE_LEVELS)

The filter vocabularies are the site's own search form (formConfigAtom of
the search page + the api-next parameter names, captured 2026-11-07).
"""
import re
from urllib.parse import parse_qs, unquote, urlparse

SITE = "https://www.immobiliare.it"
HOSTS = ("www.immobiliare.it", "immobiliare.it")

# The renderings DataDome serves to plain HTTP: every locale prefix but the
# Italian default (immobiliare_it/fetch.py). The JSON routes take the same
# codes as `__lang`.
LANGUAGES = ("en", "de", "es", "fr", "el", "pt", "ru")
DEFAULT_LANGUAGE = "en"

ITEMS_PER_PAGE = 25        # search-list/listings and agency/<id>/listing
MAX_PAGES = 80             # page 81 of any search answers HTTP 418 (2,000 results)
AGENCIES_PER_PAGE = 25
AGENCIES_MAX_PAGES = 400   # no site cap seen (Milan = 94 pages); a page past the end is empty

# ---- search vocabularies ------------------------------------------------------------

CONTRACTS = {"sale": "1", "rent": "2", "auction": "14"}
CONTRACT_NAMES = {v: k for k, v in CONTRACTS.items()}

# idCategoria (the search-page category menu)
CATEGORIES = {
    "residential": "1", "new_builds": "6", "rooms": "4", "buildings": "20", "storage": "21",
    "garages": "22", "offices": "23", "land": "24", "warehouses": "25", "shops": "26",
}
CATEGORY_NAMES = {v: k for k, v in CATEGORIES.items()}

# idTipologia[] — residential subtypes (counts verified on Milan 2026-11-07)
PROPERTY_TYPES = {
    "apartment": "4", "penthouse": "5", "detached_house": "7", "country_house": "11", "villa": "12",
    "terraced_house": "13", "loft": "31", "building": "100", "project": "112",
}

SORTS = {
    "relevance": None,
    "price_asc": ("prezzo", "asc"), "price_desc": ("prezzo", "desc"),
    "price_per_m2_asc": ("prezzoMq", "asc"), "price_per_m2_desc": ("prezzoMq", "desc"),
    "size_asc": ("superficie", "asc"), "size_desc": ("superficie", "desc"),
    "rooms_asc": ("locali", "asc"), "rooms_desc": ("locali", "desc"),
    "newest": ("dataModifica", "desc"), "oldest": ("dataModifica", "asc"),
}
AGENCY_SORTS = {"relevance": None, "price_asc": ("prezzo", "asc"), "price_desc": ("prezzo", "desc"),
                "newest": ("data", "desc"), "oldest": ("data", "asc")}

CONDITIONS = {"new": "1", "good": "2", "needs_renovation": "5", "excellent": "6"}
ENERGY_RATINGS = {"high": "2", "medium": "5", "low": "8"}          # A-B / C-D / E-G
FLOORS = {"ground": "10", "intermediate": "20", "top": "30"}
GARAGE = {"single_garage": "1", "double_garage": "3", "parking_space": "4"}
HEATING = {"autonomous": "1", "central": "2", "air_conditioning": "10"}
OUTDOOR = {"balcony": "balcone", "terrace": "terrazzo"}
GARDEN = {"private": "10", "shared": "20"}
OWNERSHIP = {"full": "1", "bare": "5", "partial": "9", "usufruct": "13", "fractional": "17", "land_lease": "21"}
BATHROOMS = ("1", "2", "3", "4")      # 4 = four or more

# public flag -> site param (every one is "1" when set)
FLAGS = {
    "lift": "ascensore", "cellar": "cantina", "pool": "piscina", "furnished": "arredato", "luxury": "luxury",
    "virtual_tour": "virtualTour", "exclude_auctions": "noAste", "private_only": "noAgenzie",
    "investment": "aReddito", "students": "perStudenti", "pets": "animali",
}

# ---- places ---------------------------------------------------------------------------

# the autocomplete / geography-lists `type` codes
PLACE_LEVELS = {-1: "country", 0: "region", 1: "province", 2: "city", 3: "macrozone", 5: "street",
                6: "microzone", 7: "metro_line", 8: "metro_station"}
LEVEL_TYPES = {v: k for k, v in PLACE_LEVELS.items()}

# the search-list / agencies parameter that carries each level
SEARCH_GEO_PARAM = {"region": "fkRegione", "province": "idProvincia", "city": "idComune",
                    "macrozone": "idMZona[]", "microzone": "idQuartiere[]"}
AGENCIES_GEO_PARAM = {"country": "nationId", "region": "regionId", "province": "provinceId", "city": "cityId"}
MARKET_GEO_PARAM = {"country": "nation-id", "region": "region-id", "province": "province-id", "city": "city-id",
                    "macrozone": "macrozone-id", "microzone": "microzone-id"}

_KEY_PART_RE = re.compile(r"^(country|region|province|city|macrozone|microzone|metro_line|metro_station):([A-Za-z0-9_-]{1,32})$", re.I)
# a place key is one or more "level:id" parts joined by "/", innermost last
# (city:8042, region:lom/province:MI, city:8042/macrozone:10046)
_KEY_RE = re.compile(r"^[a-z_]+:[A-Za-z0-9_-]{1,32}(?:/[a-z_]+:[A-Za-z0-9_-]{1,32}){0,3}$", re.I)
_ID_RE = re.compile(r"^[0-9]{1,12}$")
_LISTING_ID_RE = re.compile(r"^[0-9]{5,12}$")
_LINK_LISTING_RE = re.compile(r"/annunci/([0-9]{5,12})(?:/|$)")
_LINK_AGENCY_RE = re.compile(r"/(?:agenzie-immobiliari|imprese-edili|agenzia)/([0-9]{1,10})(?:/|$)")
_LOCALE_RE = re.compile(r"^/(en|de|es|fr|el|pt|ru|it)(?=/|$)")


def _is_link(value):
    value = value.strip().lower()
    return value.startswith(("http://", "https://", "//", "www.immobiliare.it", "immobiliare.it"))


def _as_url(value):
    value = value.strip()
    if value.startswith("//"):
        return "https:" + value
    if value.startswith(("www.", "immobiliare.it")):
        return "https://" + value
    return value


def parse_site_link(value):
    """An immobiliare.it link -> (language or None, path without the locale
    prefix, query dict of single values). Raises ValueError for another
    site's link."""
    parsed = urlparse(_as_url(value))
    host = (parsed.hostname or "").lower()
    if host not in HOSTS:
        raise ValueError("Must be an immobiliare.it link.")
    path = unquote(parsed.path or "/")
    language = None
    match = _LOCALE_RE.match(path)
    if match:
        language = match.group(1)
        path = path[match.end():] or "/"
    if not path.endswith("/"):
        path += "/"
    query = {k: v[-1] for k, v in parse_qs(parsed.query, keep_blank_values=False).items()}
    return language, path, query


def resolve_property(value):
    """'128951952' or any listing link -> the listing id (int)."""
    value = value.strip()
    if _LISTING_ID_RE.match(value):
        return int(value)
    if _is_link(value):
        _lang, path, _query = parse_site_link(value)
        match = _LINK_LISTING_RE.search(path)
        if match:
            return int(match.group(1))
        raise ValueError("Not an immobiliare.it listing link (expected …/annunci/<id>/).")
    raise ValueError("Must be an immobiliare.it listing id (128951952) or a listing link.")


def resolve_agency(value):
    """'385732' or any agency / builder link -> the agency id (int)."""
    value = value.strip()
    if _ID_RE.match(value):
        return int(value)
    if _is_link(value):
        _lang, path, _query = parse_site_link(value)
        match = _LINK_AGENCY_RE.search(path)
        if match:
            return int(match.group(1))
        raise ValueError("Not an immobiliare.it agency link (expected …/agenzie-immobiliari/<id>/…).")
    raise ValueError("Must be an immobiliare.it agency id (385732) or an agency link.")


def _normal_id(level, ident):
    if level == "region":
        return ident.lower()
    if level in ("province", "country"):
        return ident.upper()
    return ident


def parse_place_key(value):
    """'city:8042' / 'region:lom/province:MI' / 'city:8042/macrozone:10046'
    -> {level: id} (the chain), raising ValueError when malformed."""
    chain = {}
    for part in value.strip().split("/"):
        match = _KEY_PART_RE.match(part.strip())
        if not match:
            raise ValueError("Not a place key (expected level:id, e.g. city:8042 or city:8042/macrozone:10046).")
        level, ident = match.group(1).lower(), match.group(2)
        chain[level] = _normal_id(level, ident)
    return chain


def classify_location(value):
    """A location param -> ("link", (language, path, query)) |
    ("key", {level: id}) | ("name", text). A bare number is a city id."""
    value = value.strip()
    if _is_link(value):
        return "link", parse_site_link(value)
    if _KEY_RE.match(value):
        return "key", parse_place_key(value)
    if _ID_RE.match(value):
        return "key", {"city": value}
    if len(value) < 2:
        raise ValueError("Must be a place name, a place key (city:8042) or an immobiliare.it link.")
    return "name", value


# the levels a key must spell out for the search / agencies JSON (a city's
# parents are looked up through geography-lists; a zone's or a province's
# cannot be, so their keys carry the chain)
KEY_CHAIN = {"country": (), "region": (), "province": ("region",), "city": (), "macrozone": ("city",),
             "microzone": ("city",), "metro_line": ("city",), "metro_station": ("city",)}


def place_key(level, ident, chain=None):
    """The public key of a place: 'level:id', prefixed by the parent levels
    KEY_CHAIN needs when `chain` (a {level: id} dict) carries them."""
    if not level or ident in (None, ""):
        return None
    parts = []
    for parent in KEY_CHAIN.get(level, ()):
        if chain and chain.get(parent):
            parts.append(f"{parent}:{chain[parent]}")
    parts.append(f"{level}:{ident}")
    return "/".join(parts)


def innermost(chain):
    """The deepest level present in a {level: id} chain."""
    for level in ("metro_station", "metro_line", "microzone", "macrozone", "city", "province", "region", "country"):
        if chain.get(level):
            return level
    return None


# ---- paths -----------------------------------------------------------------------------

def locale_prefix(language):
    return f"/{language}" if language else ""


def detail_path(language, listing_id):
    return f"{locale_prefix(language)}/annunci/{listing_id}/"


def agency_path(language, agency_id, page=1):
    path = f"{locale_prefix(language)}/agenzie-immobiliari/{agency_id}/"
    return path + (f"?pag={page}" if page and page > 1 else "")


def listing_link(listing_id, language=None):
    return SITE + detail_path(language, listing_id)


def agency_link(agency_id, language=None):
    return SITE + f"{locale_prefix(language)}/agenzie-immobiliari/{agency_id}/"


def absolute(path):
    return path if path.startswith("http") else SITE + path


def strip_locale(path):
    """'/en/vendita-case/milano/' -> '/vendita-case/milano/'."""
    match = _LOCALE_RE.match(path)
    return path[match.end():] or "/" if match else path


# ---- the drawn area / radius ---------------------------------------------------------------

_POINT_RE = re.compile(r"^\s*(-?[0-9]{1,3}(?:\.[0-9]+)?)\s*,\s*(-?[0-9]{1,3}(?:\.[0-9]+)?)\s*$")


def _parse_points(value):
    """'lat,lng;lat,lng;…' -> [(lat, lng), …] (floats), any count.
    Raises ValueError with a user-facing message."""
    points = []
    for raw in re.split(r"[;|]", value.strip()):
        raw = raw.strip()
        if not raw:
            continue
        match = _POINT_RE.match(raw)
        if not match:
            raise ValueError("Each point must be 'lat,lng' (41.8902,12.4922), points separated by ';'.")
        lat, lng = float(match.group(1)), float(match.group(2))
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError("Latitude must be within ±90 and longitude within ±180.")
        points.append((lat, lng))
    return points


def parse_polygon(value):
    """'lat,lng;lat,lng;…' (3+ points) -> [(lat, lng), …] (floats).
    Raises ValueError with a user-facing message."""
    points = _parse_points(value)
    if len(points) < 3:
        raise ValueError("A polygon needs at least 3 points ('lat,lng;lat,lng;lat,lng').")
    return points


def parse_area(value):
    """The `area` param of properties/search_by_area -> {"type": "radius",
    "lat", "lng"} for ONE point 'lat,lng' (a radius search around it) or
    {"type": "polygon", "points": [[lat, lng], …]} for 3+ points
    'lat,lng;lat,lng;lat,lng' (the map area). Raises ValueError with a
    user-facing message."""
    points = _parse_points(value)
    if len(points) == 1:
        return {"type": "radius", "lat": points[0][0], "lng": points[0][1]}
    if len(points) >= 3:
        return {"type": "polygon", "points": [[lat, lng] for lat, lng in points]}
    raise ValueError("Give one point 'lat,lng' (a radius search around it) or at least 3 points "
                     "'lat,lng;lat,lng;lat,lng' (a polygon).")


def polygon_param(points):
    """The site's `vrt` value: 'lat,lng;lat,lng;…'."""
    return ";".join(f"{lat:g},{lng:g}" for lat, lng in points)
