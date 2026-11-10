"""The /immobiliare-it/* endpoint functions (route_glue's route_table calls
them with the schema's loaded kwargs). Caching happens here through
cache.cached_call, keyed on the validated params.

Shared upstream pages are cached once and sliced: the agency page (its
profile for agencies/details and its page-1 listing for agencies/listings),
a search link resolved through its /en/ page (geo ids + filters, reused by
every page of that link), a place name resolved through the cached
autocomplete, and a city's parent chain through the cached geography-lists.
"""
import math
import re
import unicodedata
from urllib.parse import urlencode

from cache import cached_call
from immobiliare_it import cache_config as ttl
from immobiliare_it import parsers, refs
from immobiliare_it.fetch import (ImmobiliareItBadRequest, ImmobiliareItNotFound, fetch_agencies_page,
                                  fetch_agencies_search, fetch_agency_listing, fetch_agency_page,
                                  fetch_autocomplete, fetch_detail, fetch_geography_lists, fetch_list_page,
                                  fetch_market_page, fetch_price_history, fetch_search)

ITEMS_PER_PAGE = refs.ITEMS_PER_PAGE
SEARCH_PATH = "/search-list/"


# ---- shared helpers --------------------------------------------------------------------

def _pagination(total, page, per_page, max_pages=None, past_end=False):
    """The scraper's pagination block. `total` None (a page past the end
    of a search, whose JSON carries no count) -> has_next false."""
    if total is None:
        return {"page": page, "items_per_page": per_page, "has_next": False, "total_pages": None, "total_count": None}
    total_pages = math.ceil(total / per_page) if total else 0
    if max_pages:
        total_pages = min(total_pages, max_pages)
    if past_end:
        total_pages = min(total_pages, page)
    return {"page": page, "items_per_page": per_page, "total_pages": total_pages, "total_count": total}


def _place_echo(chain, name=None, link=None):
    level = refs.innermost(chain or {})
    return {
        "key": refs.place_key(level, (chain or {}).get(level), chain) if level else None,
        "type": level,
        "id": (chain or {}).get(level) if level else None,
        "name": name,
        "link": link,
        "chain": {k: v for k, v in (chain or {}).items()},
    }


# ---- places ------------------------------------------------------------------------------

def _autocomplete(query, language, limit=20):
    payload = fetch_autocomplete(query, language)
    results = parsers.parse_autocomplete(payload, limit)
    for item in results:
        chain = parsers.place_chain(item)
        item["key"] = refs.place_key(item["type"], item["id"], chain)
        for zone in item.get("zones") or []:
            zone["key"] = refs.place_key("macrozone", zone["id"], chain)
            for micro in zone.get("microzones") or []:
                micro["key"] = refs.place_key("microzone", micro["id"], chain)
    return {"query": query, "count": len(results), "results": results}


def _autocomplete_cached(query, language, limit=20):
    return cached_call("immobiliare_it.autocomplete", {"query": query, "language": language, "limit": limit},
                       _autocomplete, ttl.LOCATIONS_CACHE)


def locations_autocomplete(query, limit, language):
    answer = _autocomplete_cached(query, language, 20)
    return {"query": query, "count": min(answer["count"], limit), "results": answer["results"][:limit]}


def _city_tree(city_id, language):
    zones = fetch_geography_lists(city_id, 3, language)     # unknown id -> NotFound
    try:
        metro = fetch_geography_lists(city_id, 7, language)
    except ImmobiliareItNotFound:
        metro = None
    return parsers.parse_geography_lists(zones, metro)


def _city_tree_cached(city_id, language):
    return cached_call("immobiliare_it.city_tree", {"city_id": str(city_id), "language": language}, _city_tree,
                       ttl.LOCATIONS_CACHE)


def _chain_of_city(city_id, language):
    """A city id -> its {country, region, province, city} chain (cached
    geography-lists); an unknown id raises NotFound."""
    tree = _city_tree_cached(city_id, language)
    chain = {"city": str(city_id)}
    for parent in tree["place"].get("parents") or []:
        if parent.get("type") and parent.get("id"):
            chain[parent["type"]] = parent["id"]
    return chain, tree["place"].get("name")


_SEARCHABLE_RANK = {"city": 0, "region": 1, "province": 2, "macrozone": 3, "microzone": 4, "country": 5}


def _fold(text):
    """'Cortina d’Ampezzo' -> 'cortina d ampezzo' (accents, case and
    punctuation folded) for name matching."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    return " ".join(re.sub(r"[^0-9a-z]+", " ", text).split())


def _names(item):
    """The names a place answers to: its label and its slug (the Italian
    name, e.g. label 'Milan', slug 'Milano')."""
    return {n for n in (_fold(item.get("name")), _fold((item.get("slug") or "").replace("_", " "))) if n}


def pick_place(results, name):
    """The autocomplete result a typed place name means. The site ranks
    by its own relevance ('Rome' -> 'Rometta Marea' first, 'Como' -> the
    'Como Sole' micro-zone first), so: an exact name match wins, a town
    before a region / province / zone of the same name; 'Zone, Town' matches
    the zone whose parent is that town; else the site's first searchable
    result."""
    searchable = [r for r in results or [] if r.get("type") in _SEARCHABLE_RANK]
    if not searchable:
        return None
    wanted = _fold(name)
    exact = [r for r in searchable if wanted in _names(r)]
    if exact:
        return min(exact, key=lambda r: _SEARCHABLE_RANK[r["type"]])
    head, _sep, tail = str(name).partition(",")
    head, tail = _fold(head), _fold(tail)
    if head and tail:
        for r in searchable:
            if head in _names(r) and any(tail in _names(p) for p in r.get("parents") or []):
                return r
    return searchable[0]


def _resolve_name(name, language):
    """A typed place name -> (chain, the autocomplete match) or NotFound."""
    answer = _autocomplete_cached(name, language, 20)
    item = pick_place(answer["results"], name)
    if item is None and "," in name:
        # 'Navigli, Milano': the site's autocomplete may not take the
        # comma form; look the zone up alone and match the town
        answer = _autocomplete_cached(name.split(",")[0].strip(), language, 20)
        item = pick_place(answer["results"], name)
    if item is None:
        raise ImmobiliareItNotFound(f"No immobiliare.it place matches '{name}'.")
    chain = {}
    for parent in item.get("parents") or []:
        if parent.get("type") and parent.get("id"):
            chain[parent["type"]] = parent["id"]
    chain[item["type"]] = item["id"]
    return chain, item


def _complete_chain(chain, language):
    """Fill a key's missing parents: a city (or a zone below it) through
    geography-lists; a lone province / zone cannot be completed (400)."""
    chain = dict(chain)
    level = refs.innermost(chain)
    if level in ("metro_line", "metro_station"):
        raise ValueError("Metro lines and stations are listed by locations/zones but cannot be searched; use a zone key.")
    if level in ("city", "macrozone", "microzone"):
        if not chain.get("city"):
            raise ValueError(f"A {level} key must carry its town: city:<id>/{level}:<id> (see locations/autocomplete).")
        if not (chain.get("region") and chain.get("province")):
            parents, _name = _chain_of_city(chain["city"], language)
            for k, v in parents.items():
                chain.setdefault(k, v)
    elif level == "province" and not chain.get("region"):
        raise ValueError("A province key must carry its region: region:<id>/province:<id> (see locations/autocomplete).")
    chain.setdefault("country", "IT")
    return chain


def locations_zones(location, language):
    kind, value = refs.classify_location(location)
    if kind == "link":
        raise ValueError("locations/zones takes a town name, a place key (city:8042) or a city id, not a link.")
    if kind == "name":
        chain, _item = _resolve_name(value, language)
    else:
        chain = value
    city_id = chain.get("city")
    if not city_id:
        raise ValueError("locations/zones needs a town (city:<id> or its name).")
    tree = _city_tree_cached(city_id, language)
    full = {"city": str(city_id)}
    for parent in tree["place"].get("parents") or []:
        if parent.get("type") and parent.get("id"):
            full[parent["type"]] = parent["id"]
    place = dict(tree["place"])
    place["key"] = refs.place_key("city", city_id, full)
    zones = []
    for zone in tree["zones"]:
        zone = dict(zone)
        zone["key"] = refs.place_key("macrozone", zone["id"], full)
        zone["microzones"] = [{**m, "key": refs.place_key("microzone", m["id"], full)} for m in zone.get("microzones") or []]
        zones.append(zone)
    lines = []
    for line in tree["metro_lines"]:
        line = dict(line)
        line["key"] = refs.place_key("metro_line", line["id"], full)
        line["stations"] = [{**s, "key": refs.place_key("metro_station", s["id"], full)} for s in line.get("stations") or []]
        lines.append(line)
    return {"place": place, "zones_count": len(zones), "zones": zones, "metro_lines": lines}


# ---- properties/search ---------------------------------------------------------------------

def _geo_params(chain):
    params = {}
    for level, name in refs.SEARCH_GEO_PARAM.items():
        if chain.get(level):
            params[name] = [chain[level]] if name.endswith("[]") else chain[level]
    return params


def _filter_params(data):
    """The validated filter params -> the site's query dict."""
    query = {}
    types = [refs.PROPERTY_TYPES[t] for t in data.get("property_type") or [] if t in refs.PROPERTY_TYPES]
    if types:
        query["idTipologia[]"] = types
    for public, site in (("min_price", "prezzoMinimo"), ("max_price", "prezzoMassimo"), ("min_size", "superficieMinima"),
                         ("max_size", "superficieMassima"), ("min_rooms", "localiMinimo"), ("max_rooms", "localiMassimo"),
                         ("min_bedrooms", "camereDaLettoMinimo")):
        if data.get(public):
            query[site] = str(data[public])
    if data.get("bathrooms"):
        query["bagni"] = data["bathrooms"]
    if data.get("condition"):
        query["stato"] = refs.CONDITIONS[data["condition"]]
    if data.get("energy_rating"):
        query["classeEnergetica"] = refs.ENERGY_RATINGS[data["energy_rating"]]
    for public, site, table in (("floor", "fasciaPiano[]", refs.FLOORS), ("garage", "boxAuto[]", refs.GARAGE),
                                ("heating", "riscaldamenti[]", refs.HEATING), ("outdoor", "balconeOterrazzo[]", refs.OUTDOOR),
                                ("garden", "giardino[]", refs.GARDEN), ("ownership", "tipoProprieta[]", refs.OWNERSHIP)):
        values = [table[v] for v in data.get(public) or [] if v in table]
        if values:
            query[site] = values
    for public, site in refs.FLAGS.items():
        if data.get(public):
            query[site] = "1"
    if data.get("keyword"):
        query["keyword[]"] = [data["keyword"]]
    sort = refs.SORTS.get(data.get("sort") or "relevance")
    if sort:
        query["criterio"], query["ordine"] = sort
    return query


def _resolve_search_link(language, path, query):
    """A pasted search link -> (its site params, the page it points at)."""
    stripped = refs.strip_locale(path)
    if stripped.startswith(SEARCH_PATH):
        params = {k: v for k, v in query.items() if k not in ("__lang", "pag", "paramsCount", "path")}
        page = int(query["pag"]) if str(query.get("pag", "")).isdigit() else 1
        return params, page
    page_query = {k: v for k, v in query.items() if k != "pag"}
    page = int(query["pag"]) if str(query.get("pag", "")).isdigit() else 1
    resolved = cached_call("immobiliare_it.search_link", {"path": stripped, "query": page_query, "language": language},
                           _search_link_page, ttl.LINK_CACHE)
    return resolved["params"], page if page > 1 else resolved["page"]


def _search_link_page(path, query, language):
    html = fetch_list_page(language, path, query or None)
    parsed = parsers.parse_search_page(html)
    if not parsed:
        raise ImmobiliareItNotFound("The link is not an immobiliare.it search page.")
    return {"params": parsed["params"], "page": parsed["page"]}


def _echo_filters(data):
    keys = ("property_type", "min_price", "max_price", "min_size", "max_size", "min_rooms", "max_rooms", "min_bedrooms",
            "bathrooms", "condition", "energy_rating", "floor", "garage", "heating", "outdoor", "garden", "ownership",
            "keyword", "sort") + tuple(refs.FLAGS)
    return {k: data.get(k) for k in keys if data.get(k) not in (None, [], False)}


def _run_search(params, page, language, contract, category, place, filters):
    params = dict(params)
    params["__lang"] = language
    params["path"] = params.get("path") or SEARCH_PATH
    params["pag"] = page
    payload = fetch_search(params)
    parsed = parsers.parse_search(payload, language)
    link = parsed["link"]
    if link and page > 1 and "pag=" not in link:
        link += ("&" if "?" in link else "?") + urlencode({"pag": page})
    return {
        "location": place,
        "contract": contract,
        "category": category,
        "filters": filters,
        "title": parsed["title"],
        "link": link,
        "zones": parsed["zones"],
        "results": parsed["results"],
        "pagination": _pagination(parsed["total"], page, ITEMS_PER_PAGE, min(refs.MAX_PAGES, parsed["max_pages"] or refs.MAX_PAGES),
                                  past_end=parsed["past_end"]),
    }


def _properties_search(location, contract, category, page, language, **filters):
    kind, value = refs.classify_location(location)
    contract_id, category_id = refs.CONTRACTS[contract], refs.CATEGORIES[category]
    if kind == "link":
        link_language, path, link_query = value
        site_params, link_page = _resolve_search_link(language, path, link_query)
        if page == 1 and link_page > 1:
            page = link_page
        params = {k: v for k, v in site_params.items()}
        # the link's own contract / category win over the defaults
        contract = refs.CONTRACT_NAMES.get(str(params.get("idContratto")), contract)
        category = refs.CATEGORY_NAMES.get(str(params.get("idCategoria")), category)
        geo = {name: params.get(name) or params.get(name + "[]")       # a /search-list/ link spells idMZona[]
               for name in ("fkRegione", "idProvincia", "idComune", "idMZona", "idQuartiere")}
        chain = {level: geo[name][0] if isinstance(geo[name], list) else geo[name]
                 for level, name in (("region", "fkRegione"), ("province", "idProvincia"), ("city", "idComune"),
                                     ("macrozone", "idMZona"), ("microzone", "idQuartiere")) if geo[name]}
        place = _place_echo(chain, link=refs.absolute(f"{refs.locale_prefix(language)}{refs.strip_locale(path)}"))
        params.update(_filter_params(filters))
    else:
        if kind == "name":
            chain, item = _resolve_name(value, language)
            name = item.get("name")
        else:
            chain, name = _complete_chain(value, language), None
            if not name and chain.get("city") and refs.innermost(chain) == "city":
                _parents, name = _chain_of_city(chain["city"], language)
        if refs.innermost(chain) == "country":
            raise ValueError("Give a region, province, town or zone to search in (locations/autocomplete).")
        params = _geo_params(chain)
        params.update({"idContratto": contract_id, "idCategoria": category_id})
        params.update(_filter_params(filters))
        place = _place_echo(chain, name=name)
    return _run_search(params, page, language, contract, category, place, _echo_filters(filters))


def properties_search(**data):
    return cached_call("immobiliare_it.search", data, _properties_search, ttl.SEARCH_CACHE)


# ---- properties/search_by_area ----------------------------------------------------------------

def _properties_search_by_area(area, contract, category, page, language, radius_m=None, **filters):
    params = {"idContratto": refs.CONTRACTS[contract], "idCategoria": refs.CATEGORIES[category]}
    if area["type"] == "polygon":
        points = [(lat, lng) for lat, lng in area["points"]]
        params["vrt"] = refs.polygon_param(points)
        area = {"type": "polygon", "points": [{"lat": lat, "lng": lng} for lat, lng in points]}
    else:
        radius = radius_m or 1000
        params["centro"] = f"{area['lat']:g},{area['lng']:g}"
        params["raggio"] = str(radius)
        area = {"type": "radius", "lat": area["lat"], "lng": area["lng"], "radius_m": radius}
    params.update(_filter_params(filters))
    result = _run_search(params, page, language, contract, category, None, _echo_filters(filters))
    result.pop("location", None)
    return {"area": area, **result}


def properties_search_by_area(**data):
    return cached_call("immobiliare_it.search_by_area", data, _properties_search_by_area, ttl.SEARCH_CACHE)


# ---- properties/details ----------------------------------------------------------------------

def _property_details(property, language):
    html = fetch_detail(language, property)
    payload = parsers.next_data(html)
    try:
        return parsers.parse_detail(payload, language)
    except ValueError:
        raise ImmobiliareItNotFound(f"listing {property} not found")


def property_details(**data):
    return cached_call("immobiliare_it.details", data, _property_details, ttl.DETAILS_CACHE)


# ---- agencies/search --------------------------------------------------------------------------

def _agencies_link_page(path, language):
    html = fetch_agencies_page(language, path)
    parsed = parsers.parse_agencies_page(html)
    if not parsed:
        raise ImmobiliareItNotFound("The link is not an immobiliare.it agencies-directory page.")
    return parsed["params"]


def _agencies_params(chain):
    params = {}
    for level, name in refs.AGENCIES_GEO_PARAM.items():
        if chain.get(level):
            params[name] = chain[level]
    return params


def _agencies_search(location, page, language):
    kind, value = refs.classify_location(location)
    if kind == "link":
        link_language, path, link_query = value
        stripped = refs.strip_locale(path)
        if not stripped.startswith("/agenzie-immobiliari/") or refs._LINK_AGENCY_RE.search(stripped):
            raise ValueError("Not an agencies-directory link (expected …/agenzie-immobiliari/<town>/); "
                             "an agency's own link goes to agencies/details.")
        if page == 1 and str(link_query.get("pag", "")).isdigit():
            page = int(link_query["pag"])
        params = cached_call("immobiliare_it.agencies_link", {"path": stripped, "language": language},
                             _agencies_link_page, ttl.LINK_CACHE)
        chain = {level: params[name] for level, name in refs.AGENCIES_GEO_PARAM.items() if params.get(name)}
        place = _place_echo(chain, link=refs.absolute(f"{refs.locale_prefix(language)}{stripped}"))
    else:
        if kind == "name":
            chain, item = _resolve_name(value, language)
            name = item.get("name")
        else:
            chain, name = _complete_chain(value, language), None
            if chain.get("city"):
                _parents, name = _chain_of_city(chain["city"], language)
        level = refs.innermost(chain)
        if level in ("macrozone", "microzone"):
            chain = {k: v for k, v in chain.items() if k in ("country", "region", "province", "city")}
        elif level in ("country", "region"):
            raise ValueError("Agencies are listed per town or province (locations/autocomplete).")
        params = _agencies_params(chain)
        place = _place_echo(chain, name=name)
    params["pag"] = page
    params["__lang"] = language
    payload = fetch_agencies_search(params)
    parsed = parsers.parse_agencies(payload)
    link = parsed["link"]
    return {
        "location": place,
        "title": parsed["title"],
        "link": link,
        "results": parsed["results"],
        "pagination": _pagination(parsed["total"], page, refs.AGENCIES_PER_PAGE),
    }


def agencies_search(**data):
    return cached_call("immobiliare_it.agencies", data, _agencies_search, ttl.AGENCIES_CACHE)


# ---- the agency page (shared) ------------------------------------------------------------------

def _agency_page(agency, language):
    html = fetch_agency_page(language, agency)
    try:
        return parsers.parse_agency(parsers.next_data(html))
    except ValueError:
        raise ImmobiliareItNotFound(f"agency {agency} not found")


def _agency_page_cached(agency, language):
    return cached_call("immobiliare_it.agency_page", {"agency": agency, "language": language}, _agency_page, ttl.AGENCY_CACHE)


def agency_details(agency, language):
    return _agency_page_cached(agency, language)["profile"]


def _agency_listings(agency, sort, page, language):
    page_data = _agency_page_cached(agency, language)      # NotFound for an unknown id
    profile = page_data["profile"]
    if page == 1 and sort == "relevance":
        listing = page_data["listing"]
    else:
        params = {"type": "agency", "pag": page, "__lang": language}
        site_sort = refs.AGENCY_SORTS.get(sort)
        if site_sort:
            params["sortBy"], params["sortDir"] = site_sort
        listing = parsers.parse_agency_listing(fetch_agency_listing(agency, params), language)
    total = listing["total"] if listing["total"] is not None else profile.get("listings_count")
    return {
        "agency": {"id": profile["id"], "name": profile["name"], "link": profile["link"],
                   "listings_count": profile.get("listings_count")},
        "sort": sort,
        "results": listing["results"],
        "pagination": _pagination(total, page, ITEMS_PER_PAGE, refs.MAX_PAGES),
    }


def agency_listings(**data):
    return cached_call("immobiliare_it.agency_listings", data, _agency_listings, ttl.AGENCY_LISTINGS_CACHE)


# ---- market -------------------------------------------------------------------------------------

def _stats_params(chain, contract):
    params = {}
    for level, name in refs.MARKET_GEO_PARAM.items():
        if chain.get(level):
            params[name] = chain[level]
    params.setdefault("nation-id", "IT")
    params["contract"] = refs.CONTRACTS[contract]
    return params


def _market_chain(location, language):
    """A market location -> (chain, name, market page path or None)."""
    kind, value = refs.classify_location(location)
    if kind == "link":
        link_language, path, _query = value
        stripped = refs.strip_locale(path)
        if not stripped.startswith("/mercato-immobiliare/"):
            raise ValueError("Not an immobiliare.it market link (expected …/mercato-immobiliare/…).")
        return None, None, stripped
    if kind == "name":
        chain, item = _resolve_name(value, language)
        return chain, item.get("name"), None
    chain = _complete_chain(value, language)
    name = None
    if chain.get("city") and refs.innermost(chain) == "city":
        _parents, name = _chain_of_city(chain["city"], language)
    return chain, name, None


def _market_record(html, language):
    try:
        record = parsers.parse_market_page(html)
    except ValueError:
        raise ImmobiliareItNotFound("immobiliare.it publishes no market prices for this place")
    place = record.get("place") or {}
    if place.get("type") and place.get("type") != "street":
        chain = {p["type"]: p["id"] for p in place.get("parents") or [] if p.get("type") and p.get("id")}
        chain[place["type"]] = place.get("id")
        place["key"] = refs.place_key(place["type"], place.get("id"), chain)
    return record


def _market_prices(location, language):
    chain, _name, path = _market_chain(location, language)
    if path is None:
        history = fetch_price_history(_stats_params(chain, "sale"))     # NotFound for an unknown place
        path = history.get("url")
        if not path:
            raise ImmobiliareItNotFound("immobiliare.it publishes no market prices for this place")
    html = fetch_market_page(language, refs.strip_locale(path))
    return _market_record(html, language)


def market_prices(**data):
    return cached_call("immobiliare_it.market", data, _market_prices, ttl.MARKET_CACHE)


def _market_price_history(location, contract):
    chain, name, path = _market_chain(location, refs.DEFAULT_LANGUAGE)
    if path is not None:
        html = fetch_market_page(refs.DEFAULT_LANGUAGE, path)
        record = _market_record(html, refs.DEFAULT_LANGUAGE)
        place = record.get("place") or {}
        if not place.get("type") or place.get("type") == "street":
            raise ImmobiliareItNotFound("immobiliare.it publishes no price series for streets")
        chain = {p["type"]: p["id"] for p in place.get("parents") or [] if p.get("type") and p.get("id")}
        chain[place["type"]] = place.get("id")
        name = place.get("name")
    payload = fetch_price_history(_stats_params(chain, contract))
    parsed = parsers.parse_price_history(payload)
    return {
        "location": _place_echo(chain, name=name or parsed.get("place_label"), link=parsed.get("link")),
        "contract": contract,
        "title": parsed["title"],
        "currency": parsed["currency"],
        "unit": "EUR per m² (monthly rent per m² for rentals)",
        "count": len(parsed["series"]),
        "series": parsed["series"],
    }


def market_price_history(**data):
    return cached_call("immobiliare_it.market_history", data, _market_price_history, ttl.MARKET_CACHE)
