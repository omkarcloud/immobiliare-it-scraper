"""The 10 Immobiliare It endpoints. Every path is served with and without the
`/immobiliare-it` prefix, so code generated against the hosted API on
RapidAPI (paths like /properties/details) runs unchanged against this
server.

Params are validated by the marshmallow schemas in immobiliare_it/schemas.py
(ONE param per input: `property` takes a listing id or listing link;
`agency` an agency id or agency link; `location` a place name, a place key
from Autocomplete Locations, a city id or an immobiliare.it search /
agencies / market link; `area` one `lat,lng` point or a polygon); unknown
params are rejected."""
import json
from urllib.parse import urlencode

from bottle import request, response, route

from schema_fields import load_query
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from immobiliare_it import api, schemas


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The request query as unicode strings (bottle 0.12's .get() hands back
    latin-1 decoded bytes, so getunicode is mandatory)."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _page_link(path, params, page):
    if not page:
        return None
    query = {k: v for k, v in params.items() if v not in (None, "", False)}
    query["page"] = page
    scheme, host = request.urlparts.scheme, request.urlparts.netloc
    return f"{scheme}://{host}{path}?{urlencode(query, doseq=True)}"


def paginate(result, path, params):
    """Lift the `pagination` block into the flat shape the hosted API
    returns: count / per_page / current_page / total_pages / next / previous."""
    pagination = result.pop("pagination", None) or {}
    result.pop("count", None)   # per-page count; `count` is the total
    page = _as_int(pagination.get("page")) or _as_int(params.get("page")) or 1
    if "has_next" in pagination:
        has_next = bool(pagination["has_next"])
        total_pages = pagination.get("total_pages")
        if total_pages is not None:
            total_pages = _as_int(total_pages, None)
    else:
        total_pages = max(_as_int(pagination.get("total_pages")), 0)
        has_next = page < total_pages
    out = {
        "count": pagination.get("total_count"),
        "per_page": pagination.get("items_per_page"),
        "current_page": page,
        "total_pages": total_pages,
        "next": _page_link(path, params, page + 1 if has_next else None),
        "previous": _page_link(path, params, page - 1 if page > 1 else None),
    }
    out.update(result)
    return out


def call(label, schema_cls, impl, paginated=False):
    """Validate, run, map errors: bad params -> 400, missing entity -> 404,
    blocks / transport -> 502, anything else -> 500."""
    raw = query_dict()
    data, error = load_query(schema_cls, raw)
    if error:
        return json_response(error, 400)
    try:
        result = impl(**data)
    except ValueError as e:
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:
        return json_response({"error": f"immobiliare.it rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Blocked as e:
        return json_response({"error": f"immobiliare.it blocked the request, retry later: {e}"}, 502)
    except UpstreamError as e:
        return json_response({"error": f"immobiliare.it {label} failed: {e}"}, 502)
    except Exception as e:                 # parser surprises
        return json_response({"error": f"immobiliare.it {label} failed: {type(e).__name__}: {e}"}, 500)
    if paginated:
        result = paginate(result, request.path, raw)
    return json_response(result)


ENDPOINTS = [
    ("/properties/details", schemas.PropertyDetailsSchema, api.property_details, False),
    ("/locations/autocomplete", schemas.LocationsAutocompleteSchema, api.locations_autocomplete, False),
    ("/locations/zones", schemas.LocationsZonesSchema, api.locations_zones, False),
    ("/properties/search", schemas.PropertiesSearchSchema, api.properties_search, True),
    ("/properties/search_by_area", schemas.PropertiesSearchByAreaSchema, api.properties_search_by_area, True),
    ("/market/prices", schemas.MarketPricesSchema, api.market_prices, False),
    ("/market/price_history", schemas.MarketPriceHistorySchema, api.market_price_history, False),
    ("/agencies/search", schemas.AgenciesSearchSchema, api.agencies_search, True),
    ("/agencies/details", schemas.AgencyDetailsSchema, api.agency_details, False),
    ("/agencies/listings", schemas.AgencyListingsSchema, api.agency_listings, True),
]


def mount(path, schema_cls, impl, paginated):
    """Serve a handler at /path and /immobiliare-it/path."""
    label = path.strip("/")

    def handler():
        return call(label, schema_cls, impl, paginated)

    handler.__name__ = "immobiliare_it_" + label.replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route("/immobiliare-it" + path, method="GET")(handler)


for _path, _schema, _impl, _paginated in ENDPOINTS:
    mount(_path, _schema, _impl, _paginated)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, *_ in ENDPOINTS]})
