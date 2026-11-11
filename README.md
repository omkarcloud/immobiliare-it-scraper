# 🏡 Immobiliare It Scraper

Immobiliare It Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Immobiliare.it property data for free.

## ✨ What Can I Get?

- 🏡 **Full details on 1.2M+ Italian listings** — price, €/m², rooms, energy class, GPS, photos, floor plans & video tours
- 🔍 **Search all of Italy your way** — any town, zone, map polygon or radius, 29 filters, sale, rent or auction
- 📈 **8 years of market prices** — €/m² for sale and rent in any region, town, zone or street
- 🏢 **31,000+ agencies & builders** — phones, website, opening hours, agents & every property they list

## 🎥 Example: A Full Immobiliare.it Listing

```json
{
  "id": 132732166,
  "link": "https://www.immobiliare.it/en/annunci/132732166/",
  "title": "Single family villa via Arienzo 70, Positano",
  "contract": "sale",
  "property_type": "Villa",
  "is_luxury": true,
  "price": { "amount": 26000000, "currency": "EUR", "formatted": "€ 26,000,000", "per_m2": 17333 },
  "surface_m2": 800,
  "rooms": "5+",
  "bedrooms": 8,
  "bathrooms": "3+",
  "condition": "Excellent / Refurbished",
  "caption": "Extraordinary property with a guest house and private access to the sea for sale in Positano",
  "description": "Extraordinary panoramic home for sale set in the heart of the Amalfi Coast, in a private and quiet position in Positano...",
  "features": ["Hydromassage", "Private garden"],
  "location": { "address": "via Arienzo 70", "city": "Positano", "province": "Salerno", "region": "Campania", "latitude": 40.6378, "longitude": 14.4851 },
  "photos": [
    { "id": 2010826496, "caption": "Piscina", "link": "https://pwm.im-cdn.it/image/2010826496/xxl.jpg", "room": "Swimming pool" }
  ],
  "photos_count": 20,
  "agency": { "id": 192057, "name": "Lionard Luxury Real Estate", "phones": [{ "number": "055 062 1219", "type": "virtual" }] },
  "created_at": "2024-02-16T15:00:31Z",
  "updated_at": "2026-11-05T16:50:54Z",
  "build_year": 1500,
  "views": ["sea", "panoramic"],
  "energy": { "class": "G", "heating": "independent, with radiators, gas powered", "air_conditioning": "independent, cold/hot" },
  "mortgage": { "suggested_loan": 18200000, "estimated_monthly_payment": 78609, "currency": "EUR" },
  "videos": [{ "id": 43344292, "link": "https://youtube.com/embed/VLyDP3HGgF0" }],
  "virtual_tours": [{ "id": null, "link": "https://tour360.getrix.it/vrtours/2559347/" }]
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Immobiliare.it Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/immobiliare-it-scraper
cd immobiliare-it-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

Immobiliare.it's DataDome bot protection refuses some IPs outright (many cloud servers among them). Getting `blocked` errors? Start it on a proxy instead:
```bash
IMMOBILIARE_IT_PROXY=http://user:pass@host:port python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/properties/details?property=132732166"
```

```json
{
  "id": 132732166,
  "link": "https://www.immobiliare.it/en/annunci/132732166/",
  "title": "Single family villa via Arienzo 70, Positano",
  "contract": "sale",
  "property_type": "Villa",
  "is_luxury": true,
  "price": { "amount": 26000000, "currency": "EUR", "formatted": "€ 26,000,000", "per_m2": 17333 },
  "surface_m2": 800,
  "rooms": "5+",
  "bedrooms": 8,
  "bathrooms": "3+",
  "condition": "Excellent / Refurbished",
  "location": { "address": "via Arienzo 70", "city": "Positano", "province": "Salerno", "region": "Campania", "latitude": 40.6378, "longitude": 14.4851 },
  "photos_count": 20,
  "has_virtual_tour": true,
  "agency": { "id": 192057, "name": "Lionard Luxury Real Estate", "phones": [{ "number": "055 062 1219", "type": "virtual" }] },
  "build_year": 1500,
  "views": ["sea", "panoramic"]
}
```

All 10 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

10 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Property Details | `/properties/details` | Everything about one listing: price, specs, GPS, photos, agency |
| Autocomplete Locations | `/locations/autocomplete` | Towns, zones and streets with their place keys, as you type |
| Location Zones | `/locations/zones` | Every zone, micro-zone and metro station of a town |
| Search Properties | `/properties/search` | Sale, rent or auction listings, 25 per page, 29 filters |
| Search Map Area | `/properties/search_by_area` | Every listing inside a polygon or radius you pick |
| Market Prices | `/market/prices` | €/m² for sale and rent, plus every sub-area's price |
| Price History | `/market/price_history` | Monthly €/m² for sale or rent since 2018 |
| Search Agencies | `/agencies/search` | Every agency in a town with phones, listings and sales |
| Agency Details | `/agencies/details` | Phones, website, opening hours, agents and listing counts |
| Agency Listings | `/agencies/listings` | Every property one agency advertises, 25 per page |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-immobiliare-it-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-immobiliare-it-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-immobiliare-it-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/properties/details",
    params={"property": "132732166"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Immobiliare It Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://www.omkar.cloud/l/immobiliare-it-scraper-github-whatsapp)

[![Ask Us by Email about Immobiliare It Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Immobiliare%20It%20Scraper%20API&body=I%20need%20help%20using%20the%20Immobiliare%20It%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Zap Imoveis Scraper**](https://github.com/omkarcloud/zap-imoveis-scraper) — ZAP Imóveis Brazil listings: prices, condo fees, IPTU, photos & agencies

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/immobiliare-it-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/immobiliare-it-scraper)
