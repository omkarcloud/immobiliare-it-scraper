"""Cache TTL per /immobiliare-it/* endpoint (cache.py, keyed on the
validated params). Listings move daily (new ads, price cuts, withdrawals),
so the search views cache for hours; a listing's own facts change only
when the advertiser edits it; places, agency profiles and the monthly
market statistics are near-static.
"""
from datetime import timedelta

# locations/autocomplete + locations/zones: the site's place index; new
# zones appear rarely.
LOCATIONS_CACHE = timedelta(days=7)
# a search link resolved through its /en/ page (geo ids + filters): static
# for a given link.
LINK_CACHE = timedelta(days=7)
# properties/search + properties/search_by_area: one page of a search; the
# order and membership change through the day, prices too.
SEARCH_CACHE = timedelta(hours=6)
# properties/details: the advertiser edits price / text now and then; a
# withdrawn listing turns 404 — serve the last page for a day at most.
DETAILS_CACHE = timedelta(hours=24)
# agencies/search: the directory of a town (counts, badges) moves slowly.
AGENCIES_CACHE = timedelta(days=1)
# agencies/details: the profile (address, hours, phones) is near-static;
# shared with agencies/listings page 1 (api._agency_page).
AGENCY_CACHE = timedelta(days=3)
# agencies/listings: the agency's own portfolio, same cadence as a search.
AGENCY_LISTINGS_CACHE = timedelta(hours=6)
# market/prices + market/price_history: the site publishes one value per
# month (lastValidDate = the 1st of the month).
MARKET_CACHE = timedelta(days=3)
