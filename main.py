"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does (paged endpoints carry a
`pagination` block instead of next / previous links); results are written
to output/*.json. The schemas fill in every default, exactly as the API does.
"""
import json
import os

from immobiliare_it import api, schemas

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


def params(schema_cls, **query):
    """Validate a query exactly like the API: defaults filled, links resolved."""
    return schema_cls().load(query)


if __name__ == "__main__":
    # a listing id or any immobiliare.it listing link
    save("property_132732166.json", api.property_details(
        **params(schemas.PropertyDetailsSchema, property="132732166")))

    # 25 listings per page; a place name, place key, city id or search link
    save("search_rome.json", api.properties_search(
        **params(schemas.PropertiesSearchSchema, location="Rome", lift="true", sort="newest")))

    # asking prices per m² for sale and rent, with every zone of the town
    save("market_florence.json", api.market_prices(
        **params(schemas.MarketPricesSchema, location="Florence")))
