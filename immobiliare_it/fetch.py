"""immobiliare.it transport: plain curl_cffi with browser-impersonated TLS,
rotated over a ladder of identities (IMPERSONATE_LADDER). No browser, no
login, no cookies kept across sessions. Egress: one sticky exit per thread
session (config.immobiliare_it_proxy(), knob IMMOBILIARE_IT_EXIT — the
pod's own IP); a retryable failure drops the session, so the retry rides a
fresh session (and, on a proxy tier, a fresh exit).

DataDome fronts www.immobiliare.it (research 2026-11-07 and 2026-11-10,
curl_cffi on the Mac's own IP, on Italian residential and US / Italian
datacenter proxy exits, and from the pod; tables in config.py):

  * The Italian default renderings (/vendita-case/<slug>/, /affitto-…,
    /annunci/<id>/) answer the 777-byte captcha-delivery page to EVERY
    curl identity on EVERY exit, the Mac's and the pod's own IPs included.
    The same pages under any other locale prefix (/en/, /de/, /fr/, …)
    pass, so every page here carries a non-Italian locale (refs.LANGUAGES)
    and the texts come back in that language, the Italian original of a
    description riding along as `defaultDescription`.
  * The TLS fingerprint decides, and the verdict DRIFTS: DataDome flags a
    fingerprint after heavy use. On 2026-11-07 `chrome` (chrome150) passed
    only the FIRST request on an exit while `firefox147` passed every page
    kind (pod: 13/13 on every tier); by 2026-11-10, after three days of
    firefox147 traffic, firefox147 (and firefox144) passed only the first
    request (pod's own IP 6/35) while chrome, chrome152, firefox155 passed
    35/35 back to back on the pod's own IP and chrome, chrome146, chrome131
    21/21 on the Mac's. So no single identity is trusted: a session takes
    the ladder's current identity, and a DataDome block moves the ladder to
    the next one (_rotate_profile) before the retry.
  * The /api-next/ JSON routes (search-list/listings, listing/count,
    agencies/search, agency/<id>/listing, geography/*, market-insights)
    pass wherever the pages do; agency/<id>/listing, agencies/search, the
    price stats and the autocomplete pass even for a flagged identity. A
    flagged identity gets the interstitial on everything else, so a 403
    drops the session.

Upstream surfaces:
  SEARCH    GET /api-next/search-list/listings/?<geo>&idContratto&idCategoria
            &…filters&criterio&ordine&__lang&path=/search-list/&pag=N — 25
            cards a page, HTTP 418 past page 80 (refs.MAX_PAGES), HTTP 404 for
            a page past the end of a shorter search (empty page here), 422
            for a rejected param (BadRequest). `path` is required (500).
  COUNT     GET /api-next/listing/count/?<same params> -> {"count"}
  LIST PAGE GET /<lang>/<seo path>/?<query> — the server-rendered search
            page; its __NEXT_DATA__ carries the resolved search params of
            that link (how a pasted search link becomes ids). 404 = unknown
            slug or a page past the cap.
  DETAIL    GET /<lang>/annunci/<id>/ — __NEXT_DATA__ detailData; a dead id
            is HTTP 404.
  AGENCIES  GET /api-next/agencies/search/?nationId&regionId&provinceId
            [&cityId]&pag&__lang -> {results[25], count, seo}; a page past
            the end is an empty page. /api-next/agencies/count/ -> number.
            The /<lang>/agenzie-immobiliari/<slug>/ page resolves a
            directory link to ids (its __NEXT_DATA__ query keys).
  AGENCY    GET /<lang>/agenzie-immobiliari/<id>/[?pag=N] — __NEXT_DATA__
            pageProps.data (profile) + the dehydrated page-1 listing; an
            unknown id answers HTTP 200 with the site's search HOME page
            (page "/[lang]/[search-type]"), mapped to NotFound by api.py.
            GET /api-next/agency/<id>/listing/?type=agency&pag=N[&sortBy
            &sortDir]&__lang -> {count, listing[25]}; unknown id -> count 0.
  PLACES    GET /api-next/geography/autocomplete/?query&macrozones=1
            &microzones=1&min_level=5&withRegions=1&__lang -> JSON list.
            GET /api-next/geography/geography-lists/?id=<cityId>&type=3|7
            -> the city's macrozones + microzones (3) / metro lines (7);
            HTTP 404 for an unknown city.
  MARKET    GET /<lang>/mercato-immobiliare/<region>/[<province>-provincia |
            <city>[/<zone>|/in-<street>]]/ — an app-router page whose RSC
            payload (self.__next_f) carries pricesLocation + geography;
            HTTP 404 for an unknown slug.
            GET /api-next/market-insights/prices/stats/?nation-id=IT
            [&region-id&province-id&city-id&macrozone-id&microzone-id]
            &contract=1|2 -> {labels[], values[], url, title, subtitle}
            (100 monthly €/m² points); HTTP 404 with empty lists for an
            unknown place, 400 for a non-numeric contract.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  ImmobiliareItUpstreamError  transport failure / 5xx           — retryable
  ImmobiliareItBlocked        DataDome 403 / 429 / challenge     — retryable
  ImmobiliareItBadRequest     upstream 400 / 418 / 422           — never retried
  ImmobiliareItNotFound       dead listing / agency / place      — never retried
"""
import os
import re
import sys
import threading
import time
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import egress
import fastjson
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from immobiliare_it import refs

# The curl_cffi identities a session may wear, in the order tried: the
# ones DataDome served 35/35 back to back on 2026-11-10 first, the one it
# had flagged by then last (module docstring). Entries the installed
# curl_cffi does not know are skipped (0.16 has no firefox15x / chrome152).
IMPERSONATE_LADDER = ("chrome", "firefox155", "chrome152", "chrome146", "firefox154", "chrome131", "firefox147")
PAGE_TIMEOUT = 35       # list / agency / detail pages are 500-800 KB
JSON_TIMEOUT = 25       # a search page of JSON is ~200 KB

_TITLE_RE = re.compile(r"<title>([^<]*)</title>", re.I)
_DATADOME_MARKERS = ("captcha-delivery.com", "geo.captcha-delivery", "Please enable JS and disable any ad blocker")


class ImmobiliareItUpstreamError(UpstreamError):
    """Transport failure or 5xx — retryable."""


class ImmobiliareItBlocked(ImmobiliareItUpstreamError, Blocked):
    """DataDome / 403 / 429 / challenge page — retryable on a fresh exit."""


class ImmobiliareItBadRequest(BadRequest):
    """Upstream 400 / 418 / 422 — never retried."""


class ImmobiliareItNotFound(NotFound):
    """Listing / agency / place / page does not exist — never retried."""


# ---- sessions ------------------------------------------------------------------

_local = threading.local()
_block_lock = threading.Lock()
_blocked_until = 0.0     # new sessions ride the fallback exit until then
_direct_blocks = []      # monotonic times of recent blocks on the direct tier
_profile_index = 0       # the ladder's current identity (shared by every thread)


def available_profiles(ladder=IMPERSONATE_LADDER):
    """The ladder entries the installed curl_cffi can impersonate (the
    generic "chrome" alias always; versioned names only when this build
    knows them)."""
    try:
        from curl_cffi.requests.impersonate import BrowserType
        known = {b.value for b in BrowserType}
    except Exception:       # an unexpected curl_cffi layout: trust the ladder
        return list(ladder)
    profiles = [p for p in ladder if p == "chrome" or p in known]
    return profiles or ["chrome"]


_PROFILES = available_profiles()


def current_profile():
    with _block_lock:
        return _PROFILES[_profile_index % len(_PROFILES)]


def _rotate_profile(failed):
    """A DataDome block on `failed`: move the ladder to the next identity,
    once per refused identity (several threads refused together advance it
    once)."""
    global _profile_index
    with _block_lock:
        if _PROFILES[_profile_index % len(_PROFILES)] == failed:
            _profile_index += 1
            print(f"immobiliare-it: DataDome refused {failed}; new sessions use "
                  f"{_PROFILES[_profile_index % len(_PROFILES)]}")


def _proxy():
    """The exit for a new session: the knob's tier, or the fallback exit
    while the direct tier is being held off (every identity refused there
    within IMMOBILIARE_IT_BLOCK_HOLD_S)."""
    proxy = config.immobiliare_it_proxy()
    if proxy is None and time.monotonic() < _blocked_until:
        return config.immobiliare_it_fallback_proxy()
    return proxy


def _session():
    sess = getattr(_local, "session", None)
    if sess is None:
        from curl_cffi import requests as curl_requests
        profile = current_profile()
        sess = curl_requests.Session(impersonate=profile)
        proxy = _proxy()
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
        sess.headers["accept-language"] = egress.accept_language(proxy)
        _local.session = sess
        _local.proxy = proxy
        _local.profile = profile
    return sess


def _drop_session(blocked=False):
    """Close the thread's session: a refused session must not be reused. A
    block also moves the identity ladder on (_rotate_profile); once every
    identity was refused on the direct tier within
    config.IMMOBILIARE_IT_BLOCK_HOLD_S, new sessions take the fallback exit
    for that long."""
    global _blocked_until
    sess = getattr(_local, "session", None)
    proxy = getattr(_local, "proxy", None)
    profile = getattr(_local, "profile", None)
    _local.session = None
    _local.proxy = None
    _local.profile = None
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass
    if not blocked:
        return
    if profile:
        _rotate_profile(profile)
    hold = config.IMMOBILIARE_IT_BLOCK_HOLD_S
    if proxy is None and hold and config.immobiliare_it_fallback_proxy() is not None:
        now = time.monotonic()
        with _block_lock:
            _direct_blocks[:] = [t for t in _direct_blocks if now - t < hold] + [now]
            if len(_direct_blocks) >= len(_PROFILES):
                _blocked_until = now + hold
                _direct_blocks.clear()


def _retrying(fn):
    """Run fn() under the shared retry policy (ImmobiliareItUpstreamError
    only; NotFound / BadRequest surface immediately). Each retry drops the
    session, so it leaves through a fresh sticky exit."""
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except ImmobiliareItUpstreamError as e:
            last = e
            _drop_session(blocked=isinstance(e, ImmobiliareItBlocked))
            if attempt < config.MAX_RETRIES:
                time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


# ---- classification ------------------------------------------------------------

def page_title(text):
    match = _TITLE_RE.search(text or "")
    return match.group(1).strip() if match else ""


def is_datadome(text):
    head = (text or "")[:3000]
    return any(marker in head for marker in _DATADOME_MARKERS)


def _upstream_message(text):
    """The site's own validation message from a 422 / 400 JSON body."""
    try:
        payload = fastjson.loads(text or "")
    except ValueError:
        return None
    if isinstance(payload, dict):
        errors = payload.get("errors")
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            path = errors[0].get("path")
            message = errors[0].get("message")
            return f"{path}: {message}" if path else message
        if payload.get("error"):
            return str(payload["error"])
    return None


def _classify(resp, label, not_found_ok=False):
    """Map an HTTP response to the taxonomy; return the body text. A 404 is
    returned (not raised) when `not_found_ok` — the search JSON answers 404
    for a page past the end and the stats route for an unknown place."""
    text = resp.text
    status = resp.status_code
    if status in (401, 403, 429) or is_datadome(text):
        raise ImmobiliareItBlocked(f"HTTP {status} (anti-bot) for {label}")
    if status == 404:
        if not_found_ok:
            return text
        raise ImmobiliareItNotFound(f"{label} not found")
    if status == 418:
        raise ImmobiliareItBadRequest(f"immobiliare.it serves at most {refs.MAX_PAGES} pages per search")
    if status in (400, 422):
        message = _upstream_message(text)
        raise ImmobiliareItBadRequest(message or f"immobiliare.it rejected the request for {label}")
    if status != 200:
        raise ImmobiliareItUpstreamError(f"HTTP {status} for {label}")
    return text


def _url(path, query=None):
    url = refs.absolute(path)
    if query:
        url += ("&" if "?" in url else "?") + urlencode(query, doseq=True)
    return url


def _get_html(path, query, label, not_found_ok=False):
    def once():
        try:
            resp = _session().get(_url(path, query), timeout=PAGE_TIMEOUT)
        except Exception as e:
            raise ImmobiliareItUpstreamError(f"request failed: {type(e).__name__}: {e}")
        text = _classify(resp, label, not_found_ok=not_found_ok)
        if "<html" not in text[:3000].lower():
            raise ImmobiliareItBlocked(f"non-HTML answer for {label}: {text[:80]!r}")
        return text, resp.status_code
    return _retrying(once)


def _get_json(path, query, label, not_found_ok=False):
    def once():
        try:
            resp = _session().get(_url(path, query), timeout=JSON_TIMEOUT)
        except Exception as e:
            raise ImmobiliareItUpstreamError(f"request failed: {type(e).__name__}: {e}")
        text = _classify(resp, label, not_found_ok=not_found_ok)
        try:
            return fastjson.loads(text), resp.status_code
        except ValueError:
            if is_datadome(text) or "<html" in text[:500].lower():
                raise ImmobiliareItBlocked(f"non-JSON answer for {label}: {text[:80]!r}")
            raise ImmobiliareItUpstreamError(f"non-JSON answer for {label}: {text[:80]!r}")
    return _retrying(once)


# ---- surfaces ------------------------------------------------------------------

def fetch_search(params):
    """One page of the search JSON. A page past the end of the search is
    the site's 404: returned as an empty payload (count unknown)."""
    payload, status = _get_json("/api-next/search-list/listings/", params, "search results", not_found_ok=True)
    if status == 404 or not isinstance(payload, dict):
        return {"results": [], "count": None, "maxPages": None, "pastEnd": True}
    return payload


def fetch_count(params):
    payload, _status = _get_json("/api-next/listing/count/", params, "search count")
    return payload if isinstance(payload, dict) else {}


def fetch_list_page(language, path, query=None):
    """A server-rendered search page under `language` (resolves a pasted
    search link). Unknown slug / past the cap: ImmobiliareItNotFound."""
    html, _status = _get_html(f"{refs.locale_prefix(language)}{path}", query, f"search page {path}")
    return html


def fetch_detail(language, listing_id):
    html, _status = _get_html(refs.detail_path(language, listing_id), None, f"listing {listing_id}")
    return html


def fetch_agencies_search(params):
    payload, _status = _get_json("/api-next/agencies/search/", params, "agencies")
    return payload if isinstance(payload, dict) else {}


def fetch_agencies_page(language, path, query=None):
    """A server-rendered agencies-directory page (resolves a directory link
    to its place ids)."""
    html, _status = _get_html(f"{refs.locale_prefix(language)}{path}", query, f"agencies page {path}")
    return html


def fetch_agency_page(language, agency_id, page=1):
    query = {"pag": page} if page and page > 1 else None
    html, _status = _get_html(f"{refs.locale_prefix(language)}/agenzie-immobiliari/{agency_id}/", query,
                              f"agency {agency_id}")
    return html


def fetch_agency_listing(agency_id, params):
    payload, _status = _get_json(f"/api-next/agency/{agency_id}/listing/", params, f"listings of agency {agency_id}")
    return payload if isinstance(payload, dict) else {}


def fetch_autocomplete(query, language):
    params = {"query": query, "macrozones": 1, "microzones": 1, "min_level": 5, "withRegions": 1, "__lang": language}
    payload, _status = _get_json("/api-next/geography/autocomplete/", params, f"places matching {query!r}")
    return payload if isinstance(payload, list) else []


def fetch_geography_lists(city_id, kind, language):
    """kind 3 = macrozones + microzones, 7 = metro lines + stations."""
    payload, _status = _get_json("/api-next/geography/geography-lists/", {"id": city_id, "type": kind, "__lang": language},
                                 f"place {city_id}")
    return payload if isinstance(payload, dict) else {}


def fetch_market_page(language, path):
    html, _status = _get_html(f"{refs.locale_prefix(language)}{path}", None, f"market page {path}")
    return html


def fetch_price_history(params):
    """The monthly €/m² series; an unknown place is the site's 404 with
    empty lists -> ImmobiliareItNotFound."""
    payload, status = _get_json("/api-next/market-insights/prices/stats/", params, "price history", not_found_ok=True)
    if status == 404 or not isinstance(payload, dict) or not payload.get("labels"):
        raise ImmobiliareItNotFound("immobiliare.it publishes no price series for this place")
    return payload
