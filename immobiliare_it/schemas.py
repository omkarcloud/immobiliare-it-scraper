"""Marshmallow request schemas for every /immobiliare-it/* route.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair):

    property   a numeric listing id (128951952) OR any immobiliare.it listing link
    agency     a numeric agency id (385732) OR any agency / builder link
    location   a place name ("Milano", "Navigli, Milano"), a place key from
               locations/autocomplete ("city:8042", "macrozone:10046",
               "province:MI", "region:lom"; a bare number = a city id) OR
               any immobiliare.it search / agencies-directory / market link
               (its filters and page are kept)
    area       one point 'lat,lng' (a radius search, with radius_m) OR a
               polygon 'lat,lng;lat,lng;lat,lng;…' (3+ points)

`language` picks the rendering of the texts (en, de, es, fr, el, pt, ru):
the Italian rendering itself is not served over plain HTTP
(immobiliare_it/fetch.py); a listing's original Italian description comes
back as `description_original`.

The filter vocabularies are the site's own search form
(immobiliare_it/refs.py, captured 2026-11-07).
"""
from marshmallow import ValidationError, validate, validates_schema

from schema_fields import (BaseSchema, ChoiceField, CommaListField, Flag, LimitField, PageField, PositiveInt,
                           QueryField, RefField, StrippedString)
from immobiliare_it import refs


class PropertyRefField(RefField):
    resolver = staticmethod(refs.resolve_property)


class AgencyRefField(RefField):
    resolver = staticmethod(refs.resolve_agency)


class LocationField(StrippedString):
    """Classifies the value (link / key / name) without network; api.py
    resolves names through the site's autocomplete and links through
    their own page."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", True)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        if value is None:
            return None
        try:
            refs.classify_location(value)
        except ValueError as e:
            raise ValidationError(str(e))
        return value


class AreaField(StrippedString):
    """ONE param for the map area: a point 'lat,lng' (radius search) or a
    polygon of 3+ points -> refs.parse_area's dict."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", True)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        if value is None:
            return None
        try:
            return refs.parse_area(value)
        except ValueError as e:
            raise ValidationError(str(e))


def _language():
    return ChoiceField(list(refs.LANGUAGES), load_default=refs.DEFAULT_LANGUAGE, metadata={
        "description": "language of the texts: en, de, es, fr, el, pt or ru (the Italian original of a description "
                       "comes back as description_original)"})


def _contract():
    return ChoiceField(list(refs.CONTRACTS), load_default="sale", metadata={"description": "sale, rent or auction"})


def _category():
    return ChoiceField(list(refs.CATEGORIES), load_default="residential", metadata={
        "description": "residential, new_builds, rooms (rent only), buildings, storage, garages, offices, land, "
                       "warehouses or shops"})


def _page(per_page, max_page):
    return PageField(max_page=max_page, metadata={
        "description": f"page of {per_page} results (immobiliare.it serves at most {max_page} pages per search)"})


class _FilterMixin:
    """The search filters shared by properties/search and
    properties/search_by_area (the site's own filter form)."""
    property_type = CommaListField(allowed=list(refs.PROPERTY_TYPES), upper=False, max_items=9, metadata={
        "description": "residential subtypes, comma-separated: apartment, penthouse, detached_house, country_house, "
                       "villa, terraced_house, loft, building, project"})
    min_price = PositiveInt(metadata={"description": "minimum price in EUR (monthly rent for rentals)"})
    max_price = PositiveInt(metadata={"description": "maximum price in EUR (monthly rent for rentals)"})
    min_size = PositiveInt(metadata={"description": "minimum surface in m²"})
    max_size = PositiveInt(metadata={"description": "maximum surface in m²"})
    min_rooms = PositiveInt(max_value=20, metadata={"description": "minimum number of rooms (locali)"})
    max_rooms = PositiveInt(max_value=20, metadata={"description": "maximum number of rooms (locali)"})
    min_bedrooms = PositiveInt(max_value=20, metadata={"description": "minimum number of bedrooms"})
    bathrooms = ChoiceField(list(refs.BATHROOMS), metadata={"description": "minimum bathrooms: 1, 2, 3 or 4 (four or more)"})
    condition = ChoiceField(list(refs.CONDITIONS), metadata={
        "description": "new (new or under construction), good, excellent (renovated) or needs_renovation"})
    energy_rating = ChoiceField(list(refs.ENERGY_RATINGS), metadata={
        "description": "energy certificate band: high (A-B), medium (C-D) or low (E-G)"})
    floor = CommaListField(allowed=list(refs.FLOORS), upper=False, max_items=3, metadata={
        "description": "floor levels, comma-separated: ground, intermediate, top"})
    garage = CommaListField(allowed=list(refs.GARAGE), upper=False, max_items=3, metadata={
        "description": "parking, comma-separated: single_garage, double_garage, parking_space"})
    heating = CommaListField(allowed=list(refs.HEATING), upper=False, max_items=3, metadata={
        "description": "autonomous, central, air_conditioning (comma-separated)"})
    outdoor = CommaListField(allowed=list(refs.OUTDOOR), upper=False, max_items=2, metadata={
        "description": "balcony, terrace (comma-separated)"})
    garden = CommaListField(allowed=list(refs.GARDEN), upper=False, max_items=2, metadata={
        "description": "private, shared (comma-separated)"})
    ownership = CommaListField(allowed=list(refs.OWNERSHIP), upper=False, max_items=6, metadata={
        "description": "sales: full, bare (nuda proprietà), partial, usufruct, fractional, land_lease (comma-separated)"})
    lift = Flag(metadata={"description": "true = only properties with a lift"})
    cellar = Flag(metadata={"description": "true = only properties with a cellar"})
    pool = Flag(metadata={"description": "true = only properties with a pool"})
    furnished = Flag(metadata={"description": "true = only furnished properties"})
    luxury = Flag(metadata={"description": "true = only luxury properties"})
    virtual_tour = Flag(metadata={"description": "true = only listings with a virtual tour"})
    exclude_auctions = Flag(metadata={"description": "true = leave auctions out of a sale search"})
    private_only = Flag(metadata={"description": "true = only listings by private owners (no agencies)"})
    investment = Flag(metadata={"description": "true = only income properties (sold with a tenant in place)"})
    students = Flag(metadata={"description": "rentals: true = only listings open to students"})
    pets = Flag(metadata={"description": "rentals: true = only listings that allow pets"})
    keyword = StrippedString(load_default=None, validate=validate.Length(min=1, max=60), metadata={
        "description": "a word the listing text must contain (terrazzo, attico, …)"})
    sort = ChoiceField(list(refs.SORTS), metadata={
        "description": "relevance (default), price_asc, price_desc, price_per_m2_asc, price_per_m2_desc, size_asc, "
                       "size_desc, rooms_asc, rooms_desc, newest, oldest"})

    @validates_schema
    def _ranges(self, data, **kwargs):
        for low, high in (("min_price", "max_price"), ("min_size", "max_size"), ("min_rooms", "max_rooms")):
            if data.get(low) and data.get(high) and data[low] > data[high]:
                raise ValidationError(f"{low} must not exceed {high}.", high)


class LocationsAutocompleteSchema(BaseSchema):
    query = QueryField(max_length=80, metadata={
        "description": "place name prefix: a region, province, town, zone, street or metro station (Mila, Navigli, "
                       "via Torino Milano); immobiliare.it's own autocomplete"})
    limit = LimitField(default=10, max_size=20, metadata={"description": "number of suggestions (1-20, default 10)"})
    language = _language()


class LocationsZonesSchema(BaseSchema):
    location = LocationField(metadata={
        "description": "a town: its name (Milano), its place key (city:8042) or a bare city id"})
    language = _language()


class PropertiesSearchSchema(_FilterMixin, BaseSchema):
    location = LocationField(metadata={
        "description": "place name (Milano, Navigli Milano), a place key from locations/autocomplete (city:8042, "
                       "macrozone:10046, province:MI, region:lom), a bare city id, or any immobiliare.it search link"})
    contract = _contract()
    category = _category()
    page = _page(refs.ITEMS_PER_PAGE, refs.MAX_PAGES)
    language = _language()


class PropertiesSearchByAreaSchema(_FilterMixin, BaseSchema):
    area = AreaField(metadata={
        "description": "the map area: one point 'lat,lng' (41.8902,12.4922) searches a circle of radius_m around it; "
                       "3 or more points 'lat,lng;lat,lng;lat,lng' search inside that polygon"})
    radius_m = PositiveInt(max_value=50000, metadata={
        "description": "radius in metres around a one-point area (default 1000, max 50000); not used with a polygon"})
    contract = _contract()
    category = _category()
    page = _page(refs.ITEMS_PER_PAGE, refs.MAX_PAGES)
    language = _language()

    @validates_schema
    def _radius_needs_a_point(self, data, **kwargs):
        area = data.get("area")
        if data.get("radius_m") and isinstance(area, dict) and area.get("type") == "polygon":
            raise ValidationError("radius_m applies to a one-point area 'lat,lng', not to a polygon.", "radius_m")


class PropertyDetailsSchema(BaseSchema):
    property = PropertyRefField(metadata={
        "description": "immobiliare.it listing id (128951952) or any listing link (…/annunci/<id>/)"})
    language = _language()


class AgenciesSearchSchema(BaseSchema):
    location = LocationField(metadata={
        "description": "a town or province: its name (Milano, Roma provincia), a place key (city:8042, province:MI), "
                       "a bare city id, or any immobiliare.it agencies-directory link"})
    page = _page(refs.AGENCIES_PER_PAGE, refs.AGENCIES_MAX_PAGES)
    language = _language()


class AgencyDetailsSchema(BaseSchema):
    agency = AgencyRefField(metadata={
        "description": "immobiliare.it agency id (385732) or any agency / builder link (…/agenzie-immobiliari/<id>/…)"})
    language = _language()


class AgencyListingsSchema(BaseSchema):
    agency = AgencyRefField(metadata={
        "description": "immobiliare.it agency id (385732) or any agency / builder link (…/agenzie-immobiliari/<id>/…)"})
    sort = ChoiceField(list(refs.AGENCY_SORTS), load_default="relevance", metadata={
        "description": "relevance (default), price_asc, price_desc, newest, oldest"})
    page = _page(refs.ITEMS_PER_PAGE, refs.MAX_PAGES)
    language = _language()


class MarketPricesSchema(BaseSchema):
    location = LocationField(metadata={
        "description": "Italy (country:IT), a region, province, town, zone or micro-zone: its name, a place key "
                       "(region:lom, province:MI, city:8042, macrozone:10046), a bare city id, or any "
                       "immobiliare.it market link (…/mercato-immobiliare/…, streets included)"})
    language = _language()


class MarketPriceHistorySchema(BaseSchema):
    location = LocationField(metadata={
        "description": "Italy (country:IT), a region, province, town, zone or micro-zone: its name, a place key "
                       "(region:lom, province:MI, city:8042, macrozone:10046), a bare city id, or any "
                       "immobiliare.it market link"})
    contract = ChoiceField(["sale", "rent"], load_default="sale", metadata={"description": "sale (default) or rent"})
