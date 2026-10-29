# 🎧 JB HiFi Scraper

JB HiFi Scraper is a **free and open-source** scraper that gets you **unlimited** detailed JB Hi-Fi Australia data for free.

## ✨ What Can I Get?

- 🛍️ **Full details on 100K+ products** — price, was-price, stock, specs, images, barcodes & variants
- 🔍 **Search & browse every aisle** — keyword search, 18 departments, 2,100+ categories, brands & deals
- ⭐ **Every customer review** — full text, star rating, Value & Quality scores, helpful votes & star breakdown
- 📍 **Live stock at all 210 stores** — who has it in stock, nearest first, plus addresses, phones & opening hours

## 🎮 Example: A Full JB Hi-Fi Product

```json
{
  "sku": "808380",
  "title": "Nintendo Switch 2 Console",
  "link": "https://www.jbhifi.com.au/products/nintendo-switch-2-console",
  "brand": "NINTENDO",
  "image": "https://cdn.shopify.com/s/files/1/0024/9803/5810/files/808380-Product-0-I-638792042401905111_bf87046f-52c7-495a-a4b5-4826f9abfea6.jpg?v=1743607995",
  "category": { "name": "Nintendo Switch 2 consoles", "path": ["Gaming", "Nintendo", "Nintendo consoles", "Nintendo Switch 2 consoles"] },
  "pricing": { "currency": "AUD", "price": 769, "price_ex_gst": 699.09, "gst": 69.91, "was_price": null, "discount_percent": null },
  "availability": { "status": "InStock", "statement": "In stock", "delivery": "InStock", "click_and_collect": "InStock", "in_store": "InStock" },
  "seller": { "id": 0, "name": "JB Hi-Fi" },
  "release_date": "2025-06-04T14:00:00+00:00",
  "barcode": "9318113101011",
  "key_features": [
    "Console Type: Hybrid console that play games at up to 120 fps via compatible games and TVs with dock",
    "Storage: 256 GB of internal storage",
    "Hardware: 7.9-inch built-in LCD screen that displays in full HD at 1080p"
  ],
  "specifications": [
    { "name": "eMMC storage", "value": "256GB" },
    { "name": "USB Ports", "value": 2 },
    { "name": "HDMI outputs", "value": 1 },
    { "name": "Colour", "value": "Black" },
    { "name": "Manufacturer's warranty", "value": "1 Year" }
  ],
  "review_summary": { "count": 93, "average": 4.23, "distribution": { "5": 68, "4": 8, "3": 2, "2": 0, "1": 15 }, "recommended": 56, "not_recommended": 12 },
  "family": { "options": [{ "name": "Model", "values": ["Switch 2 Console + Pokémon Pokopia", "Switch 2", "Switch 2 + Mario Kart World"] }] }
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free JB Hi-Fi Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/jb-hifi-scraper
cd jb-hifi-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/products/details?product=808380"
```

```json
{
  "sku": "808380",
  "title": "Nintendo Switch 2 Console",
  "link": "https://www.jbhifi.com.au/products/nintendo-switch-2-console",
  "brand": "NINTENDO",
  "category": { "name": "Nintendo Switch 2 consoles", "path": ["Gaming", "Nintendo", "Nintendo consoles", "Nintendo Switch 2 consoles"] },
  "pricing": { "currency": "AUD", "price": 769, "was_price": null, "discount_percent": null },
  "availability": { "status": "InStock", "statement": "In stock", "click_and_collect": "InStock", "in_store": "InStock" },
  "in_stock_store_count": 207,
  "seller": { "id": 0, "name": "JB Hi-Fi" },
  "barcode": "9318113101011",
  "review_summary": { "count": 93, "average": 4.23, "distribution": { "5": 68, "4": 8, "3": 2, "2": 0, "1": 15 } },
  "specifications": [
    { "name": "eMMC storage", "value": "256GB" },
    { "name": "HDMI outputs", "value": 1 },
    { "name": "Manufacturer's warranty", "value": "1 Year" }
  ]
}
```

All 13 endpoints are now live at `http://localhost:8000`.

Running it at high volume? If your IP ever starts getting 403s, set `JB_HIFI_PROXY` to an Australian residential proxy (`http://user:pass@host:port`). Otherwise you need nothing.

## 📚 Endpoints

13 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Product Details | `/products/details` | Everything about one product in a single call |
| Search Suggestions | `/products/suggestions` | Autocomplete terms shoppers use, with popularity and result counts |
| Search Products | `/products/search` | 20 products per page; filter by brand, price, stock, sale, specs |
| Product Reviews | `/products/reviews` | Full review text, star rating, helpful votes and star breakdown |
| Store Stock | `/products/stock` | Stock at every JB Hi-Fi store, nearest first |
| Deals | `/deals` | On sale, clearance, Red Hot Deals, pre-orders and more |
| Category Tree | `/categories` | Every department and category with link, or one category's facets |
| Category Products | `/categories/products` | Any category, 20 per page, fully filterable |
| Brands | `/brands` | Top 1,000 brands by product count, store-wide or per category |
| Search Stores | `/stores/search` | Stores near a suburb, postcode or GPS point |
| Store Details | `/stores/details` | Address, phone, GPS, weekly and holiday trading hours |
| Sitemap Links | `/sitemap/links` | Every child sitemap with its type and link |
| Sitemap Products | `/sitemap/products` | Every product URL, up to 1,000 per page |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-jb-hifi-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-jb-hifi-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-jb-hifi-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/products/search",
    params={"query": "iphone 17 pro", "sort": "price_asc"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about JB HiFi Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20JB%20HiFi%20Scraper%20API.)

[![Ask Us by Email about JB HiFi Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20JB%20HiFi%20Scraper%20API&body=I%20need%20help%20using%20the%20JB%20HiFi%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/jb-hifi-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/jb-hifi-scraper)
