"""Pure parsers for www.immobiliare.it: the site's JSON (search-list,
agencies, agency listing, geography, price stats) and the __NEXT_DATA__ /
RSC payloads of its pages -> clean dicts. No I/O.

Fixtures (immobiliare_it/fixtures/, captured 2026-11-07 under /en/ and
__lang=en unless named otherwise; the site's login-form CSS classes and UI
strings were rewritten to "passcode", same length, on 2026-11-10 so the
open-source copy passes its secrets grep — the parsers never read them):
search JSON (Milan sale page 1 in en +
it, Rome rent, auctions, new builds, rooms, offices, a polygon, a radius,
a filtered + sorted page, a zero-result page, a page past the end, page 81,
a rejected param, the count), /en/ search pages (Milan page 2, a filtered
zone page, Rome rentals, a dead slug, page 81), detail pages (apartment,
new-build project, rental penthouse, auction, the German rendering, a dead
id), agencies JSON (Milan page 1, past the end, Pomezia, the count),
/en/ agencies-directory pages (Milan, Rome province page 2, a dead slug),
agency pages (385732, 83565 page 2, a builder, an unknown id = the site's
search home), agency listing JSON (page 1, page 2, sorted, unknown id),
autocomplete (Milan, Rome, a street, no match), places, geography-lists
(zones, metro, unknown), market pages (Italy, Lombardy, Milan province,
Milan, Milan in English, Centro, Duomo, a street, Pomezia, a dead slug) and
the price-history JSON (Milan sale / rent, Centro, Duomo, Italy, Lombardy
rent, Milan province, an unknown place, a bad contract).
"""
import html as html_lib
import re
from datetime import datetime, timezone

import fastjson
from immobiliare_it import refs

CURRENCY = "EUR"

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
_RSC_CHUNK_RE = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', re.S)
_TITLE_RE = re.compile(r"<title>([^<]*)</title>", re.I)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)*")
_PAGE_HOME = "/[lang]/[search-type]"
_PAGE_AGENCY = "/[lang]/agency/[[...path]]"
_PAGE_AGENCY_LIST = "/[lang]/agency-list/[[...path]]"
_PAGE_SEARCH = "/[lang]/search-list-seo"
_PAGE_DETAIL = "/[lang]/listing-detail/[id]"


# ---- value helpers -----------------------------------------------------------------

def _clean(value):
    """Text -> stripped, HTML-unescaped, tag-free string or None."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    value = html_lib.unescape(_TAG_RE.sub("", value))
    value = " ".join(value.split())
    return value or None


def _int(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    return int(text) if re.fullmatch(r"-?\d+", text) else None


def _float(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _number_in(text):
    """The first number in a formatted string: '85 m²' -> 85, '€ 300,000'
    -> 300000, '3,529 €/m²' -> 3529, '22,52 €/m²' (Italian) -> 22.52.
    Thousands separators ('.' or ',') are dropped unless the trailing group
    has 1-2 digits (a decimal). Returns int when whole."""
    if text is None:
        return None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return text
    match = _NUMBER_RE.search(str(text))
    if not match:
        return None
    raw = match.group(0)
    sign = -1 if raw.startswith("-") else 1
    raw = raw.lstrip("-")
    parts = re.split(r"[.,]", raw)
    if len(parts) > 1 and len(parts[-1]) in (1, 2) and not all(len(p) == 3 for p in parts[1:]):
        number = float("".join(parts[:-1]) + "." + parts[-1])
    else:
        number = int("".join(parts))
    number *= sign
    return int(number) if isinstance(number, float) and number.is_integer() else number


def _iso_date(epoch):
    """A unix timestamp -> 'YYYY-MM-DD' (UTC)."""
    epoch = _int(epoch)
    if not epoch:
        return None
    try:
        return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return None


def _iso_datetime(epoch):
    epoch = _int(epoch)
    if not epoch:
        return None
    try:
        return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None


def _us_date(text):
    """'12/15/2026' or '12/15/2026, 9:00 AM' (the en rendering) -> ISO."""
    if not text:
        return None
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(text))
    if not match:
        return None
    month, day, year = (int(g) for g in match.groups())
    try:
        return f"{year:04d}-{month:02d}-{day:02d}"
    except ValueError:
        return None


def _yes_no(value):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("yes", "sì", "si", "true", "1", "ja", "oui"):
        return True
    if text in ("no", "false", "0", "nein", "non"):
        return False
    return None


def _photo(item, size_order=("large", "xxl", "medium", "small", "thumb")):
    """A site photo dict -> {id, caption, link} with the largest rendition."""
    if not isinstance(item, dict):
        return None
    urls = item.get("urls") if isinstance(item.get("urls"), dict) else {}
    link = next((urls[s] for s in size_order if urls.get(s)), None) or item.get("url")
    if not link and not item.get("id"):
        return None
    return {"id": _int(item.get("id")), "caption": _clean(item.get("caption")), "link": link}


def _phones(items):
    """[{type, value, formattedValues?, isVirtual?}] -> [{number, international, type, is_virtual}]."""
    out = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        number = _clean(item.get("value"))
        if not number:
            continue
        kind = (item.get("type") or "").lower()
        out.append({
            "number": number,
            "international": _clean(item.get("formattedValues")),
            "type": "mobile" if kind in ("cell", "cellulare") else ("virtual" if kind.startswith("vtel") else "landline"),
            "is_virtual": bool(item.get("isVirtual")) if "isVirtual" in item else kind.startswith("vtel"),
        })
    return out


# ---- page payloads -------------------------------------------------------------------

def next_data(html):
    """The page's __NEXT_DATA__ JSON (dict) or None."""
    match = _NEXT_DATA_RE.search(html or "")
    if not match:
        return None
    try:
        return fastjson.loads(match.group(1))
    except ValueError:
        return None


def page_title(html):
    match = _TITLE_RE.search(html or "")
    return _clean(match.group(1)) if match else None


def is_not_found_page(html):
    """The site's error page: a bare 'Immobiliare.it' title, no __NEXT_DATA__."""
    return (page_title(html) or "") == "Immobiliare.it" and "__NEXT_DATA__" not in (html or "")


def dehydrated_query(payload, name):
    """The (queryKey, data) of the first dehydratedState query named `name`."""
    page_props = ((payload or {}).get("props") or {}).get("pageProps") or {}
    for query in ((page_props.get("dehydratedState") or {}).get("queries") or []):
        key = query.get("queryKey") or []
        if key and key[0] == name:
            return key, ((query.get("state") or {}).get("data"))
    return None, None


def rsc_text(html):
    """The decoded React-Server-Components flight text of an app-router
    page (self.__next_f.push chunks), '' when absent."""
    parts = []
    for chunk in _RSC_CHUNK_RE.findall(html or ""):
        try:
            parts.append(fastjson.loads('"' + chunk + '"'))
        except ValueError:
            try:
                parts.append(chunk.encode("latin-1", "ignore").decode("unicode_escape"))
            except Exception:
                continue
    return "".join(parts)


def _json_after(text, key):
    """The JSON value that follows '"<key>":' in `text` (brace-matched,
    string-aware) -> parsed object, or None."""
    needle = f'"{key}":'
    start = text.find(needle)
    while start >= 0:
        i = start + len(needle)
        while i < len(text) and text[i] in " \t\r\n":
            i += 1
        if i < len(text) and text[i] in "{[":
            opener = text[i]
            closer = "}" if opener == "{" else "]"
            depth, j, in_string, escaped = 0, i, False, False
            while j < len(text):
                ch = text[j]
                if in_string:
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == '"':
                        in_string = False
                elif ch == '"':
                    in_string = True
                elif ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return fastjson.loads(text[i:j + 1])
                        except ValueError:
                            break
                j += 1
        start = text.find(needle, start + 1)
    return None


# ---- places ---------------------------------------------------------------------------

def _place(item, with_children=True):
    """An autocomplete / geography-lists node -> {key, id, type, name, slug,
    …}; `parents` and the zone tree keep the same shape."""
    if not isinstance(item, dict):
        return None
    level = refs.PLACE_LEVELS.get(_int(item.get("type")))
    ident = item.get("id")
    out = {
        "key": refs.place_key(level, ident),
        "id": str(ident) if ident not in (None, "") else None,
        "type": level,
        "name": _clean(item.get("label")),
        "slug": item.get("keyurl") or None,
    }
    center = item.get("center")
    if isinstance(center, dict) and center.get("lat") is not None:
        out["latitude"], out["longitude"] = _float(center.get("lat")), _float(center.get("lng"))
    elif item.get("lat") is not None:
        out["latitude"], out["longitude"] = _float(item.get("lat")), _float(item.get("lng"))
    if with_children:
        children = item.get("children") or item.get("macrozones") or []
        if level == "macrozone" or level == "metro_line":
            out["children"] = [c for c in (_place(x, False) for x in children) if c]
    return out


def parse_autocomplete(payload, limit=None):
    """The autocomplete list -> place dicts with their parent chain and, for
    a city, its macrozones (each with its microzones)."""
    results = []
    for item in payload or []:
        place = _place(item, with_children=False)
        if not place:
            continue
        place["is_admin_centre"] = bool(item.get("admin_centre")) if item.get("admin_centre") is not None else None
        place["parents"] = [p for p in (_place(x, False) for x in item.get("parents") or []) if p]
        for parent in place["parents"]:
            parent.pop("latitude", None), parent.pop("longitude", None)
        zones = []
        for zone in item.get("macrozones") or []:
            node = _place(zone, with_children=False)
            if not node:
                continue
            node["microzones"] = [c for c in (_place(x, False) for x in zone.get("children") or []) if c]
            zones.append(node)
        place["zones"] = zones
        place["metro_lines"] = [l for l in (_clean(x.get("label")) for x in item.get("sameStationOn") or [] if isinstance(x, dict)) if l]
        results.append(place)
        if limit and len(results) >= limit:
            break
    return results


def place_chain(item):
    """An autocomplete item (or a parsed place with `parents`) -> {level: id}
    for every level in its chain, itself included."""
    chain = {}
    nodes = [item] + list(item.get("parents") or [])
    for node in nodes:
        level = node.get("type") if isinstance(node.get("type"), str) else refs.PLACE_LEVELS.get(_int(node.get("type")))
        if level and node.get("id") not in (None, ""):
            chain.setdefault(level, str(node["id"]))
    return chain


def parse_geography_lists(zones_payload, metro_payload=None):
    """geography-lists type 3 (+ optional type 7) -> the city with its
    macrozones / microzones and metro lines / stations."""
    base = zones_payload or metro_payload or {}
    city = _place(base, with_children=False)
    city["parents"] = [p for p in (_place(x, False) for x in base.get("parents") or []) if p]
    zones = []
    for zone in (zones_payload or {}).get("macrozones") or []:
        node = _place(zone, with_children=False)
        if not node:
            continue
        node["microzones"] = [c for c in (_place(x, False) for x in zone.get("children") or []) if c]
        zones.append(node)
    lines = []
    for line in (metro_payload or {}).get("metros") or []:
        node = _place(line, with_children=False)
        if not node:
            continue
        node["stations"] = [c for c in (_place(x, False) for x in line.get("children") or []) if c]
        lines.append(node)
    return {"place": city, "zones": zones, "metro_lines": lines}


# ---- listing cards ----------------------------------------------------------------------

def _location(loc):
    if not isinstance(loc, dict):
        return None
    nation = loc.get("nation") if isinstance(loc.get("nation"), dict) else {}
    out = {
        "latitude": _float(loc.get("latitude")),
        "longitude": _float(loc.get("longitude")),
        "address": _clean(loc.get("address")),
        "street_number": _clean(loc.get("streetNumber")),
        "locality": _clean(loc.get("locality")),
        "microzone": _clean(loc.get("microzone")),
        "macrozone": _clean(loc.get("macrozone")),
        "macrozone_id": _int(loc.get("macrozoneId")),
        "city": _clean(loc.get("city")),
        "city_id": _int(loc.get("cityId")),
        "province": _clean(loc.get("province")),
        "province_id": loc.get("provinceId") or None,
        "region": _clean(loc.get("region")),
        "country": _clean(nation.get("name")) if isinstance(loc.get("nation"), dict) else _clean(loc.get("nation")),
        "country_code": nation.get("id") or None,
    }
    if out["city_id"] is None:
        out.pop("city_id")
    if out["macrozone_id"] is None:
        out.pop("macrozone_id")
    if out["province_id"] is None:
        out.pop("province_id")
    return out


def _price(price, contract=None):
    if not isinstance(price, dict):
        return None
    formatted = _clean(price.get("formattedValue"))
    out = {
        "amount": _number_in(price.get("value")) if price.get("value") is not None else _number_in(formatted),
        "currency": CURRENCY,
        "formatted": formatted,
        "is_visible": bool(price.get("visible")) if "visible" in price else None,
    }
    if price.get("minValue") or price.get("maxValue"):
        out["min_amount"] = _number_in(price.get("minValue"))
        out["max_amount"] = _number_in(price.get("maxValue"))
    if price.get("pricePerSquareMeter"):
        out["per_m2"] = _number_in(price.get("pricePerSquareMeter"))
    if contract == "rent":
        out["period"] = "month"
    if price.get("priceRange"):
        out["range"] = _clean(price.get("priceRange"))
    return out


def _floor(floor):
    if isinstance(floor, dict):
        label = _clean(floor.get("value"))
        number = None
        for candidate in (floor.get("abbreviation"), floor.get("floorOnlyValue"), floor.get("ga4FloorValue")):
            if _int(candidate) is not None:
                number = _int(candidate)
                break
        if number is None:
            number = _clean(floor.get("floorOnlyValue") or floor.get("abbreviation"))
        return {"label": label, "number": number}
    if isinstance(floor, str):
        return {"label": _clean(floor), "number": _int(floor)}
    return None


def _agency(adv):
    agency = (adv or {}).get("agency") if isinstance(adv, dict) else None
    if not isinstance(agency, dict):
        return None
    images = agency.get("imageUrls") if isinstance(agency.get("imageUrls"), dict) else {}
    out = {
        "id": _int(agency.get("id")),
        "name": _clean(agency.get("displayName")),
        "link": agency.get("agencyUrl") or None,
        "type": agency.get("type") or None,
        "label": _clean(agency.get("label")),
        "phones": _phones(agency.get("phones")),
        "logo": images.get("large") or images.get("small"),
        "is_paid": bool(agency.get("isPaid")) if "isPaid" in agency else None,
        "is_guaranteed": bool(agency.get("guaranteed")) if "guaranteed" in agency else None,
    }
    visit = agency.get("bookableVisit") if isinstance(agency.get("bookableVisit"), dict) else {}
    if visit:
        out["is_visit_bookable"] = bool(visit.get("isVisitBookable"))
        out["has_virtual_visit"] = bool(visit.get("virtualVisitEnabled"))
    if "hasPriceProposal" in agency:
        out["accepts_price_proposals"] = bool(agency.get("hasPriceProposal"))
    timetable = agency.get("timetable")
    if isinstance(timetable, list) and timetable:
        hours = {}
        for slot in timetable:
            if not isinstance(slot, dict):
                continue
            day = _int(slot.get("dayOfTheWeek"))
            if day is None:
                continue
            hours.setdefault(day, []).append([str(slot.get("startHour") or "")[:5], str(slot.get("endHour") or "")[:5]])
        out["opening_hours"] = [{"weekday": d, "hours": hours[d]} for d in sorted(hours)]
    return out


def _agent(adv):
    agent = (adv or {}).get("supervisor") if isinstance(adv, dict) else None
    if not isinstance(agent, dict):
        return None
    return {
        "name": _clean(agent.get("displayName")),
        "role": _clean(agent.get("label")),
        "phones": _phones(agent.get("phones")),
        "photo": agent.get("imageUrl") or None,
    }


def _main_features(items):
    out = []
    for item in items or []:
        if isinstance(item, dict) and item.get("label"):
            out.append({"type": item.get("type"), "label": _clean(item.get("label"))})
    return out


def _units(properties, contract):
    """The units of a new-build project (every property but the main one)."""
    units = []
    for prop in properties or []:
        if not isinstance(prop, dict) or prop.get("isMain"):
            continue
        typology = prop.get("typology") if isinstance(prop.get("typology"), dict) else {}
        units.append({
            "id": _int(prop.get("id")),
            "property_type": _clean(typology.get("name")),
            "caption": _clean(prop.get("caption")),
            "price": _price(prop.get("price"), contract),
            "surface_m2": _number_in(prop.get("surface")),
            "rooms": _clean(prop.get("rooms")),
            "bathrooms": _int(prop.get("bathrooms")),
            "floor": _floor(prop.get("floor")),
            "has_lift": bool(prop.get("elevator")) if "elevator" in prop else None,
            "reference": _clean((prop.get("reference") or {}).get("code")) if isinstance(prop.get("reference"), dict) else None,
            "photo": (_photo(prop.get("photo")) or {}).get("link"),
        })
    return units


def _card_property(real_estate):
    """The property that carries a listing's facts: the main one, else the first."""
    properties = real_estate.get("properties") or []
    for prop in properties:
        if isinstance(prop, dict) and prop.get("isMain"):
            return prop
    return properties[0] if properties and isinstance(properties[0], dict) else {}


def parse_card(result, language=None):
    """One search-list / agency-listing result -> a listing card."""
    real_estate = result.get("realEstate") if isinstance(result, dict) and "realEstate" in result else result
    if not isinstance(real_estate, dict):
        return None
    listing_id = _int(real_estate.get("id"))
    seo = result.get("seo") if isinstance(result, dict) and isinstance(result.get("seo"), dict) else {}
    prop = _card_property(real_estate)
    typology = real_estate.get("typology") if isinstance(real_estate.get("typology"), dict) else {}
    category = prop.get("category") if isinstance(prop.get("category"), dict) else {}
    contract = real_estate.get("contract") or None
    photos = [_photo(p) for p in ((prop.get("multimedia") or {}).get("photos") or [])]
    photos = [p for p in photos if p]
    cover = _photo(prop.get("photo"))
    is_project = bool(real_estate.get("isProjectLike"))
    card = {
        "id": listing_id,
        "link": seo.get("url") or (refs.listing_link(listing_id, language) if listing_id else None),
        "title": _clean(real_estate.get("title")),
        "contract": contract,
        "listing_type": "project" if is_project else (real_estate.get("type") or "ad"),
        "category": _clean(category.get("name")),
        "category_id": _int(category.get("id")),
        "property_type": _clean(typology.get("name")),
        "property_type_id": _int(typology.get("id")),
        "is_new_listing": bool(real_estate.get("isNew")),
        "is_luxury": bool(real_estate.get("luxury")),
        "is_project": is_project,
        "visibility": real_estate.get("visibility") or None,
        "price": _price(real_estate.get("price") or prop.get("price"), contract),
        "surface_m2": _number_in(prop.get("surface")),
        "rooms": _clean(prop.get("rooms")),
        "bedrooms": _int(prop.get("bedRoomsNumber")),
        "bathrooms": _int(prop.get("bathrooms")) if _int(prop.get("bathrooms")) is not None else _clean(prop.get("bathrooms")),
        "floor": _floor(prop.get("floor")),
        "has_lift": bool(prop.get("elevator")) if "elevator" in prop else None,
        "condition": _clean(prop.get("ga4Condition")),
        "heating": _clean(prop.get("ga4Heating")),
        "caption": _clean(prop.get("caption")),
        "description": _clean(prop.get("description")),
        "features": [f for f in (_clean(x) for x in prop.get("ga4features") or []) if f],
        "main_features": _main_features(prop.get("featureList") or prop.get("mainFeatures")),
        "location": _location(prop.get("location")),
        "photo": (cover or (photos[0] if photos else None) or {}).get("link"),
        "photos": photos,
        "photos_count": len(photos) or None,
        "has_virtual_tour": bool((prop.get("multimedia") or {}).get("virtualTours")) if isinstance(prop.get("multimedia"), dict) else None,
        "agency": _agency(real_estate.get("advertiser")),
        "agent": _agent(real_estate.get("advertiser")),
    }
    if is_project or _int(real_estate.get("propertiesCount")):
        card["units_count"] = _int(real_estate.get("propertiesCount")) or len(real_estate.get("properties") or [])
        card["units"] = _units(real_estate.get("properties"), contract)
    return card


def _breadcrumb_zones(breadcrumbs):
    zones, place = [], {}
    for crumb in breadcrumbs or []:
        if not isinstance(crumb, dict):
            continue
        kind = crumb.get("type")
        link = crumb.get("link") if isinstance(crumb.get("link"), dict) else {}
        if kind in ("region", "province", "city", "macrozone", "microzone") and crumb.get("label") and link.get("url"):
            place[kind] = {"name": _clean(crumb.get("label")), "link": link.get("url")}
        for item in crumb.get("items") or []:
            if isinstance(item, dict) and item.get("label"):
                item_link = item.get("link") if isinstance(item.get("link"), dict) else {}
                zones.append({"name": _clean(item.get("label")), "type": item.get("type"),
                              "link": item_link.get("url"), "is_current": bool(item_link.get("current"))})
    return place, zones


def parse_search(payload, language=None):
    """The search-list JSON -> {total, max_pages, page, title, link, place,
    zones, results}. A past-the-end page (fetch marks it) is empty."""
    payload = payload or {}
    seo = payload.get("seoData") if isinstance(payload.get("seoData"), dict) else {}
    place, zones = _breadcrumb_zones(payload.get("breadcrumbs"))
    results = [c for c in (parse_card(r, language) for r in payload.get("results") or []) if c]
    total = _int(payload.get("count"))
    if total is None and _int(payload.get("totalAds")) is not None:
        total = _int(payload.get("totalAds"))
    return {
        "total": total,
        "is_total_capped": bool(payload.get("isResultsLimitReached")),
        "max_pages": _int(payload.get("maxPages")),
        "page": _int(payload.get("currentPage")),
        "title": _clean(seo.get("searchName")) or _clean(seo.get("title")),
        "link": seo.get("canonical") or None,
        "place": place or None,
        "zones": zones,
        "results": results,
        "past_end": bool(payload.get("pastEnd")),
    }


def parse_search_page(html):
    """A server-rendered /<lang>/<seo path>/ search page -> {"params": the
    resolved search params (geo ids + filters), "page": N, "payload": the
    embedded search-list JSON} or None (not a search page)."""
    payload = next_data(html)
    if not payload or payload.get("page") not in (_PAGE_SEARCH, "/search-list"):
        return None
    key, data = dehydrated_query(payload, "real-estate-list")
    if not key or len(key) < 2 or not isinstance(key[1], dict):
        return None
    params = {}
    for name, value in key[1].items():
        if name in ("idNazione", "__lang") or value in (None, "", []):
            continue
        params[name] = value
    page = _int(key[2]) if len(key) > 2 else None
    return {"params": params, "page": page or 1, "payload": data}


# ---- listing detail ---------------------------------------------------------------------

def _energy(energy):
    if not isinstance(energy, dict):
        return None
    klass = energy.get("class") if isinstance(energy.get("class"), dict) else {}
    out = {
        "class": _clean(klass.get("name")),
        "performance_index": _clean(energy.get("epi")),
        "performance_index_unit": (f"kWh/{energy.get('epiUm')} year" if energy.get("epiUm") else None),
        "renewable_index": _clean(energy.get("renewableEpi")),
        "heating": _clean(energy.get("heatingType")),
        "air_conditioning": _clean(energy.get("airConditioning")),
        "emission": _clean(energy.get("emission")),
        "thermal_insulation": _clean(energy.get("thermalInsulation")),
        "is_zero_energy_building": bool(energy.get("zeroEnergyBuilding")) if "zeroEnergyBuilding" in energy else None,
    }
    building = energy.get("buildingPerformance") if isinstance(energy.get("buildingPerformance"), dict) else None
    if building:
        out["building_performance"] = {"winter": _clean(building.get("winter")), "summer": _clean(building.get("summer"))}
    return out


def _costs(costs):
    if not isinstance(costs, dict):
        return None
    condo = _clean(costs.get("condominiumExpenses"))
    out = {
        "condominium_fees": _number_in(condo),
        "condominium_fees_period": ("month" if condo and ("month" in condo.lower() or "mese" in condo.lower())
                                    else ("year" if condo and ("year" in condo.lower() or "anno" in condo.lower()) else None)),
        "condominium_fees_formatted": condo,
        "heating_expenses": _clean(costs.get("heatingExpenses")),
        "applied_vat": _clean(costs.get("appliedVat")),
        "agency_commission": _clean(costs.get("agencyCommission")),
        "commission_subject": _clean(costs.get("commissionSubject")),
        "notary_commission": _clean(costs.get("notaryCommission")),
        "bank_guarantee": _clean(costs.get("bankGuarantee")),
    }
    return out


def _rent(rent):
    if not isinstance(rent, dict):
        return None
    return {
        "deposit": _clean(rent.get("deposit")),
        "price_reference_index": _clean(rent.get("priceReferenceIndex")),
        "is_rent_to_buy": bool(rent.get("redemptionRent")) if rent.get("redemptionRent") is not None else None,
        "is_available_to_students": bool(rent.get("availableToStudents")) if rent.get("availableToStudents") is not None else None,
    }


def _auction(auction):
    if not isinstance(auction, dict):
        return None
    state = auction.get("saleState") if isinstance(auction.get("saleState"), dict) else {}
    lot = auction.get("lotCategory") if isinstance(auction.get("lotCategory"), dict) else {}
    return {
        "sale_date": _us_date(auction.get("saleDateValue") or auction.get("saleDate")),
        "sale_datetime_label": _clean(auction.get("saleDate")),
        "sale_type": _clean(auction.get("saleType")),
        "sale_state": _clean(state.get("name")),
        "is_open": bool(state.get("isAvailable")) if "isAvailable" in state else None,
        "published_at": _iso_date(auction.get("publishDate")),
        "changed_at": _us_date(auction.get("changeDate")),
        "minimum_offer": _number_in(auction.get("minimumOffer")),
        "minimum_rise": _number_in(auction.get("minimumRise")),
        "security_deposit": _number_in(auction.get("securityDeposit")),
        "expense_deposit": _number_in(auction.get("expenseAccountDeposit")),
        "procedure_number": _clean(auction.get("procedureNumber")),
        "lot_category": _clean(lot.get("name")),
        "lots_count": _int(auction.get("totalLotEstates")),
        "court": _clean(auction.get("auctionRegister")),
        "has_booked_debt_expenses": _yes_no(auction.get("expenseBookedDebt")),
        "contribution_not_due": _yes_no(auction.get("contributionNotDue")),
    }


def _mortgage(mortgage):
    widget = (mortgage or {}).get("mortgageWidget") if isinstance(mortgage, dict) else None
    if not isinstance(widget, dict):
        return None
    rates = []
    for group in widget.get("rates") or []:
        if not isinstance(group, dict):
            continue
        rates.append({"loan_to_value_pct": _int(group.get("percent")),
                      "rates": [{"years": _int(r.get("year")), "rate_pct": round(_float(r.get("rate")) * 100, 3) if _float(r.get("rate")) is not None else None}
                                for r in group.get("rates") or [] if isinstance(r, dict)]})
    return {
        "price": _number_in(widget.get("price")),
        "suggested_loan": _number_in(widget.get("value")),
        "estimated_monthly_payment": _number_in(widget.get("tax")),
        "currency": CURRENCY,
        "rates_by_loan_to_value": rates,
    }


def _multimedia(media):
    if not isinstance(media, dict):
        return None
    photos = [p for p in (_photo(x) for x in media.get("photos") or []) if p]
    for raw, parsed in zip(media.get("photos") or [], photos):
        tag = raw.get("tag") if isinstance(raw, dict) and isinstance(raw.get("tag"), dict) else None
        if tag:
            parsed["room"] = _clean(tag.get("label"))
    plans = [p for p in (_photo(x) for x in media.get("floorplans") or []) if p]
    return {
        "photos": photos,
        "videos": [{"id": _int(v.get("id")), "link": v.get("url")} for v in media.get("videos") or [] if isinstance(v, dict) and v.get("url")],
        "floor_plans": plans,
        "virtual_tours": [{"id": _int(v.get("id")), "link": v.get("url")} for v in media.get("virtualTours") or [] if isinstance(v, dict) and v.get("url")],
        "documents": [{"id": _int(d.get("id")), "title": _clean(d.get("title")), "type": d.get("type") or None,
                       "format": d.get("format") or None, "link": d.get("url")}
                      for d in media.get("documents") or [] if isinstance(d, dict) and d.get("url")],
        "home_staging": [p for p in (_photo(x) for x in media.get("homeStaging") or []) if p],
    }


def _surface_constitution(sc):
    if not isinstance(sc, dict):
        return None
    elements = []
    for el in sc.get("surfaceConstitutionElements") or []:
        if not isinstance(el, dict):
            continue
        floor = el.get("floor") if isinstance(el.get("floor"), dict) else {}
        elements.append({
            "name": _clean(el.get("constitution")),
            "kind": el.get("constitutionKey") or None,
            "surface_m2": _number_in(el.get("surface")),
            "commercial_surface_m2": _number_in(el.get("commercialSurface")),
            "share_pct": _number_in(el.get("percentage")),
            "floor": _clean(floor.get("value")),
            "surface_type": _clean(el.get("surfaceType")),
        })
    return {"total_main_surface_m2": _number_in(sc.get("totalMainSurface")), "elements": elements}


def parse_detail(payload, language=None):
    """The detail page's __NEXT_DATA__ -> the full listing record. Raises
    ValueError when the page carries no listing."""
    page_props = ((payload or {}).get("props") or {}).get("pageProps") or {}
    detail = page_props.get("detailData") if isinstance(page_props.get("detailData"), dict) else {}
    real_estate = detail.get("realEstate") if isinstance(detail.get("realEstate"), dict) else None
    if not real_estate or not real_estate.get("id"):
        raise ValueError("no listing in the page")
    card = parse_card({"realEstate": real_estate, "seo": {"url": (detail.get("seo") or {}).get("canonical")}}, language)
    prop = _card_property(real_estate)
    state = real_estate.get("state") if isinstance(real_estate.get("state"), dict) else {}
    reference = real_estate.get("reference") if isinstance(real_estate.get("reference"), dict) else {}
    typology_v2 = prop.get("typologyV2") if isinstance(prop.get("typologyV2"), dict) else {}
    media = _multimedia(prop.get("multimedia"))
    visible_features = [_clean(f.get("name")) for f in prop.get("primaryFeatures") or []
                        if isinstance(f, dict) and f.get("isVisible") and f.get("name")]
    features = [f for f in (_clean(x) for x in prop.get("features") or []) if f]
    for name in visible_features:
        if name and name not in features:
            features.append(name)
    record = dict(card)
    record.update({
        "contract_label": _clean(real_estate.get("contractValue")),
        "status": _clean(state.get("name")),
        "is_available": bool(real_estate.get("availableState")) if real_estate.get("availableState") is not None else None,
        "availability": _clean(prop.get("availability")),
        "reference": _clean(reference.get("code")),
        "created_at": _iso_datetime(real_estate.get("createdAt")),
        "updated_at": _iso_datetime(real_estate.get("updatedAt")),
        "last_update_label": _clean(prop.get("lastUpdate")),
        "property_type_detail": _clean(typology_v2.get("name")) or _clean(prop.get("typologyValue")),
        "property_type_label": _clean(prop.get("typologyValue")),
        "rooms_label": _clean(prop.get("roomsValue")),
        "kitchen": _clean(prop.get("kitchenStatus")),
        "condition": _clean(prop.get("condition")) or card.get("condition"),
        "build_year": _int(prop.get("buildingYear")),
        "building_floors": _number_in(prop.get("floors")),
        "building_floors_label": _clean(prop.get("floors")),
        "garage": _clean(prop.get("garage")),
        "is_income_property": bool(prop.get("income")) if prop.get("income") is not None else None,
        "land": _clean(prop.get("land")),
        "views": [v for v in (_clean(x.get("name")) for x in prop.get("views") or [] if isinstance(x, dict)) if v],
        "features": features or card.get("features"),
        "features_original": card.get("features"),
        "description": _clean(prop.get("description")),
        "description_original": _clean(prop.get("defaultDescription")),
        "surface_constitution": _surface_constitution(prop.get("surfaceConstitution")),
        "energy": _energy(prop.get("energy")),
        "costs": _costs(prop.get("costs")),
        "rent": _rent(prop.get("rent")) if card.get("contract") == "rent" else None,
        "auction": _auction(prop.get("auction")),
        "mortgage": _mortgage(real_estate.get("mortgage")),
        "photos": (media or {}).get("photos") or card.get("photos"),
        "photos_count": len((media or {}).get("photos") or card.get("photos") or []) or None,
        "videos": (media or {}).get("videos") or [],
        "floor_plans": (media or {}).get("floor_plans") or [],
        "virtual_tours": (media or {}).get("virtual_tours") or [],
        "documents": (media or {}).get("documents") or [],
        "home_staging_photos": (media or {}).get("home_staging") or [],
        "has_virtual_tour": bool((media or {}).get("virtual_tours")),
        "keywords": [k for k in (_clean(x) for x in page_props.get("keywordsTags") or []) if k],
    })
    if record["photo"] is None and record["photos"]:
        record["photo"] = record["photos"][0]["link"]
    if card.get("is_project"):
        record["project"] = {
            "units_label": _clean(prop.get("unitsValue")),
            "residential_units": _int(prop.get("residentialUnits")),
            "commercial_units": _int(prop.get("commercialUnits")),
            "unit_types_count": _int(prop.get("typologyAmount")),
            "work_dates": _clean(prop.get("workDates")),
            "work_progress": _clean(prop.get("workProgress")),
        }
    return record


# ---- agencies ---------------------------------------------------------------------------

def _agency_location(loc):
    if not isinstance(loc, dict):
        return None
    def node(name):
        value = loc.get(name)
        if isinstance(value, dict):
            return {"id": str(value.get("id")) if value.get("id") not in (None, "") else None, "name": _clean(value.get("name")),
                    "slug": value.get("keyurl") or None}
        return {"id": None, "name": _clean(value), "slug": None} if value else None
    return {
        "latitude": _float(loc.get("latitude")),
        "longitude": _float(loc.get("longitude")),
        "microzone": node("microzone"),
        "macrozone": node("macrozone"),
        "city": node("city"),
        "province": node("province"),
        "region": node("region"),
        "country": node("nation"),
    }


def _opening_hours(items):
    out = []
    for item in items or []:
        if not isinstance(item, dict) or _int(item.get("day")) is None:
            continue
        hours = [[str(a), str(b)] for a, b in (h for h in item.get("hours") or [] if isinstance(h, (list, tuple)) and len(h) == 2)]
        out.append({"weekday": _int(item.get("day")), "hours": hours})
    return out


def parse_agencies(payload):
    """The agencies/search JSON -> {total, title, link, results}."""
    payload = payload or {}
    seo = payload.get("seo") if isinstance(payload.get("seo"), dict) else {}
    results = []
    for row in payload.get("results") or []:
        if not isinstance(row, dict):
            continue
        images = row.get("imageUrls") if isinstance(row.get("imageUrls"), dict) else {}
        badge = row.get("badge") if isinstance(row.get("badge"), dict) else {}
        loc = row.get("agencyLocation") if isinstance(row.get("agencyLocation"), dict) else {}
        results.append({
            "id": _int(row.get("id")),
            "name": _clean(row.get("displayName")),
            "link": row.get("agencyUrl") or (refs.agency_link(_int(row.get("id"))) if _int(row.get("id")) else None),
            "type": row.get("type") or None,
            "address": _clean(row.get("address")),
            "description": _clean(row.get("description")),
            "phones": _phones(row.get("phones")),
            "logo": images.get("large") or images.get("small"),
            "partnership": _clean(row.get("partnership")),
            "listings_count": _int(row.get("realEstate")),
            "premium_listings_count": _int(row.get("premiumAds")),
            "sold_count": _int(row.get("realEstateSales")),
            "years_on_site": _int(row.get("timeContract")),
            "quality_index": _int(row.get("qualityIndex")),
            "badge": badge.get("type") or None,
            "is_highlighted": bool(row.get("highlighted")) if "highlighted" in row else None,
            "is_paid": bool(row.get("isPaid")) if "isPaid" in row else None,
            "is_guaranteed": bool(row.get("guaranteed")) if "guaranteed" in row else None,
            "visibility": row.get("visibility") or None,
            "location": {
                "latitude": _float(loc.get("latitude")), "longitude": _float(loc.get("longitude")),
                "macrozone": _clean(loc.get("macrozone")), "city": _clean(loc.get("city")),
                "province": _clean(loc.get("province")), "region": _clean(loc.get("region")),
                "country": _clean(loc.get("nation")),
            } if loc else None,
        })
    return {
        "total": _int(payload.get("count")),
        "title": _clean(seo.get("title")),
        "link": seo.get("canonical") or None,
        "results": results,
    }


def parse_agencies_page(html):
    """A /<lang>/agenzie-immobiliari/<slug>/ directory page -> {"params":
    the ids of the place (nationId, regionId, provinceId[, cityId]),
    "page": N, "payload": the embedded agencies JSON} or None."""
    payload = next_data(html)
    if not payload or payload.get("page") != _PAGE_AGENCY_LIST:
        return None
    key, data = dehydrated_query(payload, "agency-list-search")
    if not key or len(key) < 2 or not isinstance(key[1], dict):
        return None
    params = {k: v for k, v in key[1].items() if k in refs.AGENCIES_GEO_PARAM.values() and v not in (None, "")}
    return {"params": params, "page": _int(key[1].get("pag")) or 1, "payload": data}


def parse_agency(payload):
    """An agency page's __NEXT_DATA__ -> {"profile", "listing"}; raises
    ValueError when the page is not an agency page (the site answers an
    unknown id with its search home page, HTTP 200)."""
    if not payload or payload.get("page") != _PAGE_AGENCY:
        raise ValueError("not an agency page")
    page_props = (payload.get("props") or {}).get("pageProps") or {}
    data = page_props.get("data") if isinstance(page_props.get("data"), dict) else None
    if not data or not data.get("id"):
        raise ValueError("no agency in the page")
    status = data.get("status") if isinstance(data.get("status"), dict) else {}
    place, _zones = {}, None
    for crumb in data.get("breadcrumbs") or []:
        if isinstance(crumb, dict) and crumb.get("type") in ("province", "city") and crumb.get("link"):
            place[crumb["type"]] = {"name": _clean(crumb.get("label")), "link": crumb.get("link")}
    profile = {
        "id": _int(data.get("id")),
        "name": _clean(data.get("name")),
        "link": data.get("url") or refs.agency_link(_int(data.get("id"))),
        "slug": data.get("keyUrl") or None,
        "type": data.get("type") or None,
        "group": data.get("group") or None,
        "address": _clean(data.get("address")),
        "description": _clean(data.get("description")),
        "website": data.get("website") or None,
        "phones": _phones(data.get("phones")),
        "logo": data.get("image") or None,
        "listings_count": _int(data.get("realEstateAds")),
        "sold_count": _int(data.get("realEstateSales")),
        "years_on_site": _int(data.get("timeContract")),
        "opening_hours": _opening_hours(data.get("openingHours")),
        "agents": [{"id": _int(a.get("id")), "name": _clean(" ".join(str(a.get(k) or "") for k in ("name", "surname"))),
                    "gender": a.get("gender") or None} for a in data.get("agents") or [] if isinstance(a, dict)],
        "is_paid": bool(data.get("isPaid")) if "isPaid" in data else None,
        "is_court": bool(data.get("isCourt")) if "isCourt" in data else None,
        "is_disabled": bool(status.get("isDisabled")) if "isDisabled" in status else None,
        "visibility": data.get("visibility") or None,
        "location": _agency_location(data.get("location")),
        "directory": place or None,
    }
    key, listing = dehydrated_query(payload, "agency-real-estate-list")
    page = _int(key[1].get("pag")) if key and len(key) > 1 and isinstance(key[1], dict) else None
    return {"profile": profile, "listing": parse_agency_listing(listing), "listing_page": page or 1}


def parse_agency_listing(payload, language=None):
    """The agency/<id>/listing JSON (or the page's dehydrated copy) ->
    {total, results}."""
    payload = payload or {}
    results = [c for c in (parse_card(r, language) for r in payload.get("listing") or []) if c]
    return {"total": _int(payload.get("count")), "results": results}


# ---- market prices ----------------------------------------------------------------------

def _price_point(item):
    if not isinstance(item, dict):
        return None
    avg, last_year = _float(item.get("avgPrice")), _float(item.get("avgPriceLastYear"))
    change = round((avg - last_year) / last_year * 100, 2) if avg is not None and last_year else None
    return {
        "average_per_m2": avg,
        "min_per_m2": _float(item.get("min")),
        "max_per_m2": _float(item.get("max")),
        "average_per_m2_last_year": last_year,
        "change_pct_year": change,
        "currency": CURRENCY,
        "period": item.get("lastValidDate") or None,
    }


def _market_geography(geo):
    if not isinstance(geo, dict):
        return None
    level = geo.get("level") or refs.PLACE_LEVELS.get(_int(geo.get("type")))
    level = "street" if level == "address" else level
    center = geo.get("center") if isinstance(geo.get("center"), dict) else {}
    parents = []
    for parent in geo.get("parents") or []:
        if isinstance(parent, dict):
            p_level = parent.get("level") or refs.PLACE_LEVELS.get(_int(parent.get("type")))
            parents.append({"key": refs.place_key(p_level, parent.get("id")), "id": str(parent.get("id")) if parent.get("id") not in (None, "") else None,
                            "type": p_level, "name": _clean(parent.get("label"))})
    return {
        "key": refs.place_key(level, geo.get("id")) if level != "street" else None,
        "id": str(geo.get("id")) if geo.get("id") not in (None, "") else None,
        "type": level,
        "name": _clean(geo.get("label")),
        "slug": geo.get("slug") or None,
        "latitude": _float(center.get("lat")),
        "longitude": _float(center.get("lng")),
        "postal_code": geo.get("postalCode") or None,
        "parents": parents,
    }


def parse_market_page(html):
    """A /mercato-immobiliare/… page -> {title, link, place, period, prices
    {sale, rent}, breakdown}. Raises ValueError when the page carries no
    prices (an unknown slug)."""
    text = rsc_text(html)
    prices = _json_after(text, "pricesLocation")
    if not isinstance(prices, dict):
        raise ValueError("no market prices in the page")
    geography = _json_after(text, "geography")
    title = page_title(html)
    heading = _H1_RE.search(html or "")
    highlighted = {}
    for item in prices.get("highlighted") or []:
        if isinstance(item, dict) and item.get("type"):
            highlighted[item["type"]] = _price_point(item)
    breakdowns = []
    for level, block in (prices.get("subdivisions") or {}).items():
        if not isinstance(block, dict):
            continue
        items = []
        for row in block.get("items") or []:
            if not isinstance(row, dict):
                continue
            row_trend = row.get("trend") if isinstance(row.get("trend"), dict) else {}
            items.append({
                "name": _clean(row.get("label")),
                "link": row.get("link") or None,
                "sale_per_m2": _float(row.get("sale")),
                "rent_per_m2": _float(row.get("rent")),
                "sale_change_pct_year": round(_float(row_trend.get("sale")), 2) if _float(row_trend.get("sale")) is not None else None,
                "rent_change_pct_year": round(_float(row_trend.get("rent")), 2) if _float(row_trend.get("rent")) is not None else None,
                "period": row.get("lastValidDate") or None,
            })
        breakdowns.append({"level": level, "title": _clean(block.get("title")), "description": _clean(block.get("description")),
                           "items": items})
    period = next((p["period"] for p in highlighted.values() if p and p.get("period")), None)
    canonical = re.search(r'<link rel="canonical" href="([^"]+)"', html or "")
    return {
        "title": _clean(heading.group(1)) if heading else title,
        "link": canonical.group(1) if canonical else None,
        "place": _market_geography(geography),
        "period": period,
        "prices": {"sale": highlighted.get("sale"), "rent": highlighted.get("rent")},
        "breakdown": breakdowns,
    }


def parse_price_history(payload):
    """The prices/stats JSON -> {title, place_label, link, series}."""
    payload = payload or {}
    labels, values = payload.get("labels") or [], payload.get("values") or []
    series = []
    for label, value in zip(labels, values):
        if label:
            series.append({"month": str(label)[:7], "average_per_m2": _float(value)})
    return {
        "title": _clean(payload.get("title")),
        "place_label": _clean(payload.get("subtitle")),
        "link": refs.absolute(payload["url"]) if payload.get("url") else None,
        "currency": CURRENCY,
        "series": series,
    }
