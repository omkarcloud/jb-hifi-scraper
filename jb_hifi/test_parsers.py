"""Offline tests for jb_hifi/parsers.py against the raw captures in
fixtures/ (taken 2026-10-28; the HTML pages are trimmed to the script
statements the parsers read, the sitemaps to their first entries).

    python -m pytest jb_hifi/test_parsers.py -q
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jb_hifi import parsers  # noqa: E402
from jb_hifi import api  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load_json(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


def load_text(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


def hit(name):
    return load_json(name)["hits"][0]


# ---- product cards --------------------------------------------------------------------

def test_product_card_samsung():
    card = parsers.parse_product_card(hit("algolia_product_795454.json"))
    assert card["sku"] == "795454" and card["id"] == "795454"
    assert card["title"] == "Samsung Galaxy S25 256GB (Navy)"
    assert card["link"] == "https://www.jbhifi.com.au/products/samsung-galaxy-s25-256gb-navy"
    assert card["brand"] == "SAMSUNG" and card["model"] == "SM-S931BDBEATS_11901334136"
    assert card["image"].startswith("https://cdn.shopify.com/")
    assert card["category"] == {"name": "Android phones", "path": ["Mobile Phones", "Outright phones", "Android phones"],
                                "department": "COMMUNICATIONS", "group": "SAMSUNG MOBILE - OUTRIGHT"}
    assert card["pricing"] == {"currency": "AUD", "price": 887, "price_ex_gst": 806.36, "gst": 80.64, "was_price": 1387,
                               "save_amount": 500, "discount_percent": 36.0, "cashback": None,
                               "price_after_cashback": None, "ticket_price": 1387}
    assert card["is_on_sale"] is True and card["promotion_ends"] == "2026-11-18T12:59:59+00:00"
    assert card["availability"]["status"] == "InStock" and card["availability"]["click_and_collect"] == "InStock"
    assert card["availability"]["can_buy_online"] is True and card["availability"]["lifecycle"] == "NonReplenishable"
    assert card["in_stock_store_count"] == 209
    assert card["rating"] == 4.72 and card["reviews_count"] == 718
    assert card["badges"]["banner"] == "On Sale" and card["badges"]["all"] == ["On Sale"]
    assert card["seller"] == {"id": 0, "name": "JB Hi-Fi"} and card["is_marketplace"] is False
    assert card["is_family"] is False and card["family_id"] == "71f1e431-5882-4c03-a732-720017957af1"
    assert card["release_date"] == "2025-02-13T13:00:00+00:00"
    assert card["published_at"] == "2025-01-22T18:13:30+00:00"


def test_product_card_marketplace():
    card = parsers.parse_product_card(hit("algolia_product_marketplace_10067849.json"))
    assert card["is_marketplace"] is True
    assert card["seller"]["name"] == "Bounce Mobile" and card["seller"]["id"] == 5509
    assert card["pricing"]["price"] == 475 and card["pricing"]["was_price"] is None
    assert card["availability"]["delivery_only"] is True and card["availability"]["click_and_collect"] == "NotAvailable"
    assert card["in_stock_store_count"] == 0 and card["rating"] is None


def test_product_card_family_record():
    card = parsers.parse_product_card(hit("algolia_product_family_parent.json"))
    assert card["is_family"] is True and card["sku"] is None
    assert card["id"] == "fb9792bc-c965-43cd-aa94-762eec20f20b"
    assert card["title"] == "JBL Flip 6 Portable Bluetooth Speaker"
    assert card["pricing"]["price"] == 169 and card["pricing"]["was_price"] is None   # displayWasPrice false


# ---- full product -----------------------------------------------------------------------

def test_product_details_samsung():
    record = parsers.parse_product(hit("algolia_product_795454.json"),
                                   load_json("shopify_product_samsung-galaxy-s25-256gb-navy.js.json"),
                                   load_json("bv_summary_795454.json")["response"])
    assert record["links"] == {"product": "https://www.jbhifi.com.au/products/samsung-galaxy-s25-256gb-navy",
                               "sku_page": "https://www.jbhifi.com.au/pages/sku/795454"}
    assert record["condition"] == "New"
    assert record["description"].startswith("Introducing the new Galaxy S25")
    assert record["description_html"].startswith("<p>")
    assert len(record["key_features"]) == 3
    specs = {s["name"]: s["value"] for s in record["specifications"]}
    assert specs["Internal storage"] == "256GB" and specs["RAM (GB)"] == 12
    assert specs["Video Frames Per Second"] == ["@60fps", "UHD 8K (7680 x 4320)"]
    assert "Brand" not in specs and "Price" not in specs and "Kids phone" not in specs
    assert record["graphic_attributes"][0] == {"name": "Network compatibility", "value": "5G", "type": "String",
                                               "icon": "https://s3.us-east-1.amazonaws.com/product-image-bucket-prod-us/blob-177363.jpeg"}
    assert len(record["images"]) == 8 and all(u.startswith("https://") for u in record["images"])
    assert len(record["media"]) == 7 and record["media"][0]["type"] == "image"
    assert record["offers"][0]["type"] == "SpecialOffers" and record["offers"][0]["heading"].startswith("Get a $1000")
    assert record["offers"][0]["ends"] == "2026-11-11T12:59:00+00:00"
    assert record["marketplace_offers"] == []
    assert record["review_summary"] == {"count": 718, "average": 4.78, "rating_range": 5,
                                        "distribution": {"5": 604, "4": 84, "3": 21, "2": 5, "1": 4},
                                        "recommended": 679, "not_recommended": 27, "questions": 0, "answers": 0}
    assert record["reviews_count"] == 718
    assert record["family"] == {"id": "71f1e431-5882-4c03-a732-720017957af1", "options": None, "members": None}
    assert record["variants"][0]["barcode"] == "8806095852225" and record["variants"][0]["weight_grams"] == 306
    assert record["barcode"] == "8806095852225"
    assert record["supplier"] == {"number": 10439, "name": "LIKEWIZE AUSTRALIA PTY LTD",
                                  "stock_code": "SM-S931BDBEATS_11901334136"}
    assert record["packaged_dimensions"] == {"height_cm": 2.9, "width_cm": 8.9, "depth_cm": 16.5, "weight_kg": 0.306}
    assert record["limit_per_order"] == 5 and record["freight_price"] == 9.99 and record["free_delivery"] is False
    assert record["release_date_text"] == "Available for Click and Collect or Delivery from 4th Feb"
    assert record["media_info"] is None          # a phone: display.artist is not an artist
    assert "galaxy-s25-series" in record["collections"]
    assert record["tags"] == ["Brand:Samsung", "InStock"]
    assert record["shopify"]["product_id"] == 7333451006153 and record["shopify"]["variant_id"] == 40424745926857
    assert len(record["in_stock_store_ids"]) == 209 and record["in_stock_store_ids"][0] == 2
    assert record["created_at"] == "2025-01-09T23:03:05+00:00"


def test_product_details_family_and_members():
    parent = hit("algolia_product_family_parent.json")
    record = parsers.parse_product(parent)
    assert record["family"]["id"] == "fb9792bc-c965-43cd-aa94-762eec20f20b"
    assert record["family"]["options"] == [{"name": "Colour", "values": ["Black", "Blue"], "render": "Swatches"}]
    assert len(record["family"]["members"]) == 4
    member = record["family"]["members"][0]
    assert member["sku"] == "597793" and member["values"] == ["Black"] and member["is_displayed"] is True
    assert member["link"] == "https://www.jbhifi.com.au/products/jbl-flip-6-portable-bluetooth-speaker-black"
    # a member record borrows the family record's option / member lists
    child = parsers.parse_product(hit("algolia_product_family_child_597793.json"), family_hit=parent)
    assert child["sku"] == "597793" and child["family"]["members"][1]["sku"] == "597794"


def test_product_details_marketplace_offers_and_music():
    record = parsers.parse_product(hit("algolia_product_marketplace_10067849.json"))
    assert record["condition"] == "As New"
    offer = record["marketplace_offers"][0]
    assert offer["rank"] == 1 and offer["seller"] == {"id": 5509, "name": "Bounce Mobile"}
    assert offer["pricing"]["price"] == 475 and offer["availability"]["delivery_only"] is True
    assert offer["shipping_min"] == 0
    music = parsers.parse_product(hit("algolia_product_music_912357.json"))
    assert music["media_info"]["artist"] == "SOUNDTRACK (Various)" and music["media_info"]["tracklist"] == []
    assert music["category"]["path"] == ["Music", "Vinyl"]
    assert music["availability"]["status"] == "InStock"


def test_shopify_product_without_data():
    assert parsers.parse_shopify_product(None) is None
    shop = parsers.parse_shopify_product(load_json("shopify_product_samsung-galaxy-s25-256gb-navy.js.json"))
    assert shop["options"] == [] and shop["variants"][0]["title"] is None   # "Default Title" hidden
    assert shop["variants"][0]["price"] == 887 and shop["variants"][0]["compare_at_price"] == 1387
    assert shop["published_at"] == "2025-01-23T05:13:30+11:00"


def test_review_summary_empty():
    summary = parsers.parse_review_summary(load_json("bv_summary_empty.json")["response"])
    assert summary["count"] == 0 and summary["average"] is None
    assert summary["distribution"] == {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0}


# ---- listings ---------------------------------------------------------------------------

def test_listing_iphone():
    listing = parsers.parse_listing(load_json("algolia_search_iphone.json"), 1, 3)
    assert listing["pagination"] == {"page": 1, "items_per_page": 3, "total_pages": 653, "total_count": 1957,
                                     "is_count_exact": True}
    assert len(listing["results"]) == 3 and listing["results"][0]["sku"]
    names = [f["name"] for f in listing["facets"]]
    assert names == ["Brand", "Seller", "Condition", "Department", "Category", "Subcategory", "Availability",
                     "Badge", "Marketplace", "On sale"]
    brand = listing["facets"][0]
    assert brand["key"] == "Brand" and brand["values"][0] == {"value": "APPLE", "count": 1957}
    assert listing["price_range"] is None       # facets.Price was not requested in this capture


def test_listing_extra_facets_and_empty():
    listing = parsers.parse_listing(load_json("algolia_deals_clearance.json"), 2, 2, ("Screen Size (Inches)",))
    assert listing["pagination"]["page"] == 2 and listing["pagination"]["total_count"] > 0
    assert listing["price_range"] is None                                          # facets.Price not in the capture
    assert all(f["name"] != "Screen Size (Inches)" for f in listing["facets"])   # neither is this
    stats = {"facets_stats": {"facets.Price": {"min": 0.5, "max": 23888, "avg": 1, "sum": 2}}, "hits": [],
             "nbHits": 0, "page": 0, "nbPages": 0, "hitsPerPage": 20}
    assert parsers.parse_listing(stats, 1, 20)["price_range"] == {"min": 0.5, "max": 23888}
    empty = parsers.parse_listing(load_json("algolia_search_empty.json"), 1, 3)
    assert empty["results"] == [] and empty["facets"] == [] and empty["pagination"]["total_count"] == 0


def test_suggestions_and_brands():
    rows = parsers.parse_suggestions(load_json("algolia_suggestions_iph.json"))
    assert rows[0] == {"query": "iphone", "popularity": 187170, "results_count": 18401}
    brands = parsers.parse_brand_facets(load_json("algolia_brands_facets.json"))
    assert brands[0] == {"name": "APPLE", "count": 3152, "slug": "apple"} and len(brands) == 40


# ---- navigation / categories ----------------------------------------------------------

def test_nav_tree():
    menus = parsers.parse_nav(load_text("home_trimmed.html"))
    assert [m["name"] for m in menus] == ["New", "Products", "Brands", "Deals & Catalogues", "Clearance", "Services",
                                          "Gift Cards", "Join JB Perks", "News & Reviews"]
    products = menus[1]
    assert len(products["children"]) == 18
    computers = products["children"][0]
    assert computers["name"] == "Computers & Tablets" and computers["icon"] == "Laptop" and computers["link"] is None
    main = computers["children"][0]
    assert main == {"name": "Computers", "link": "https://www.jbhifi.com.au/collections/computers-tablets",
                    "handle": "computers-tablets", "is_main_collection": True, "icon": None, "children": []}
    # dividers are dropped, nested sub-menus kept
    refurbished = next(c for c in computers["children"] if c["name"] == "Refurbished")
    assert all(c["name"] for c in refurbished["children"])
    assert refurbished["children"][0]["handle"] == "computers-tablets/laptops-refurbished"
    flat = parsers.flatten_nav(menus)
    assert len(flat) > 1000 and flat[0]["trail"] == ["Products", "Computers & Tablets"]


def test_nav_missing():
    with pytest.raises(ValueError):
        parsers.parse_nav("<html></html>")


def test_collection_page_tvs():
    page = parsers.parse_collection_page(load_text("collection_tvs_trimmed.html"), "tvs")
    assert page["handle"] == "tvs" and page["site_handle"] == "tvs"
    assert page["name"] == "TVs & Home Theatre"
    assert page["link"] == "https://www.jbhifi.com.au/collections/tvs"
    assert page["page_title"] == "TVs - Shop OLED, QLED, QD-OLED, Gaming, 4K Smart TVs & More - JB Hi-Fi"
    assert page["filters"] == '"category_hierarchy":"TVs LED" OR "category_hierarchy":"TVs OLED"'
    assert page["category_filter"] == '"category_hierarchy":"TVs & Home Theatre"'
    assert page["query"] is None and page["default_sort"] is None
    assert page["facets"][0] == {"name": "Price", "type": "rangeInput"}
    assert [f["name"] for f in page["facets"]][1:4] == ["TV category", "Brand", "Screen Size (Inches)"]
    assert page["breadcrumbs"] == [{"name": "TVs & Home Theatre", "link": "https://www.jbhifi.com.au/collections/tvs"}]
    assert len(page["subcategories"]) == 27
    assert page["subcategories"][0] == {"name": "Hot Deals on TVs", "handle": "hot-deals-on-tvs",
                                        "link": "https://www.jbhifi.com.au/collections/hot-deals-on-tvs"}
    assert page["subcategories"][1]["handle"] == "tvs/cheap-tvs"
    assert page["featured_skus"] == ["891981", "897175", "892001", "797344"]
    assert page["description"].startswith("Movie night looking")


def test_collection_page_subpath_and_missing():
    page = parsers.parse_collection_page(load_text("collection_android-phones_trimmed.html"),
                                         "mobile-phones/android-phones")
    assert page["name"] == "Android phones"
    assert page["site_handle"].startswith("android-phones_")
    assert page["filters"] == '"category_hierarchy":"Android phones"'
    assert [b["name"] for b in page["breadcrumbs"]] == ["Mobile Phones", "Android phones"]
    with pytest.raises(ValueError):
        parsers.parse_collection_page(load_text("collection_notfound_trimmed.html"), "televisions")


def test_collection_filter_grouping():
    assert api._group('"a":"x" OR "a":"y"') == '("a":"x" OR "a":"y")'
    assert api._group('"a":"x" AND ("b":"y" OR "c":"z")') == '"a":"x" AND ("b":"y" OR "c":"z")'
    assert api._group('"a":"x"') == '"a":"x"'
    assert api._collection_filter({"handle": "tvs/cheap-tvs", "filters": None}) == 'collectionHandles:"cheap-tvs"'
    assert api._category_filter("Mobile Phones") == 'category_hierarchy:"Mobile Phones"'
    assert api._category_filter("tvs/cheap-tvs") == \
        'category_hierarchy:"tvs/cheap-tvs" OR collectionHandles:"cheap-tvs"'
    assert api._facet_clause("Screen Size (Inches)", "65") == '"facets.Screen Size (Inches)":"65"'
    assert api._facet_clause("Brand", 'A"B') == '"facets.Brand":"A\\"B"'


def test_listing_filters():
    data = {"brand": "Samsung", "condition": "New", "seller": "JB Hi-Fi", "min_price": 100, "max_price": 500,
            "in_stock": True, "on_sale": False, "marketplace": "exclude", "filter": [("Smart OS", "Tizen")]}
    filters = api._listing_filters(data, 'onPromotion:true OR all_calculated_product_tags:"Clearance"')
    assert filters.startswith(api.VISIBLE + ' AND (onPromotion:true OR all_calculated_product_tags:"Clearance")')
    assert '"facets.Brand":"Samsung"' in filters and '"facets.Sold by":"JB Hi-Fi"' in filters
    assert "price >= 100" in filters and "price <= 500" in filters
    assert api.IN_STOCK_FILTER in filters and "onPromotion:false" in filters and "isMarketplace:false" in filters
    assert filters.endswith('"facets.Smart OS":"Tizen"')
    assert api._listing_filters({}) == api.VISIBLE


def test_subcollections_sitemap():
    rows = parsers.parse_subcollections_sitemap(load_text("sitemap_subcollections_trimmed.xml"))
    assert rows[0] == {"handle": "computers-tablets/lenovo-yoga",
                       "link": "https://www.jbhifi.com.au/collections/computers-tablets/lenovo-yoga",
                       "lastmod": "2026-10-29"}
    assert len(rows) == 30


# ---- stores -----------------------------------------------------------------------------

def test_store_record():
    store = parsers.parse_store(hit("algolia_stores_geo.json"), 1234)
    assert store["id"] == "150" and store["name"] == "City - Westfield Sydney"
    assert store["link"] == "https://www.jbhifi.com.au/pages/city-westfield-sydney"
    assert store["type"] == "Store" and store["region"] == "Metro" and store["is_public"] is True
    assert store["address"] == {"line1": "Westfield Sydney Shopping Centre", "line2": "Store 6010, Level 6",
                                "line3": "Corner Pitt & Market Streets", "suburb": "Sydney", "state": "NSW",
                                "postcode": "2000", "country": "Australia"}
    assert store["phone"] == "02 9928 7000" and store["latitude"] == -33.869667
    assert store["distance_km"] == 1.23 and store["timezone"] == "Australia/NSW"
    assert store["services"]["click_and_collect"] is True
    assert "eParcelStandard" in store["services"]["delivery_experiences"]
    assert "TVs" in store["categories_ranged"]
    assert store["trading_hours"][0] == {"day": "Monday", "is_open": True, "opens": "09:30", "closes": "19:00"}
    assert len(store["trading_hours"]) == 7 and store["trading_hours"][6]["day"] == "Sunday"
    assert len(store["this_week"]) == 7 and store["this_week"][0]["date"] == "2026-10-29"
    assert store["trading_hour_changes"][0]["reason"] == "Public Holiday"


def test_store_non_public_has_no_link():
    rows = [parsers.parse_store(h) for h in load_json("algolia_stores.json")["hits"]]
    for row in rows:
        assert (row["link"] is None) == (not row["is_public"])
        assert row["distance_km"] is None


def test_store_directory_maps_stock_ids_to_public_store_ids():
    hits = load_json("algolia_stores.json")["hits"] + load_json("algolia_stores_geo.json")["hits"]
    # Preston HOME on 2026-10-29: products list it as 9, its store page says 309
    hits.append({"shopId": 309, "databaseId": 9, "objectID": "9", "storeName": "Preston HOME",
                 "locationType": "Home", "displayOnWeb": "p"})
    directory = parsers.parse_store_directory(hits)
    assert len(directory["stores"]) == 7
    assert directory["stock_ids"] == {"99": "99", "98": "98", "150": "150", "85": "85", "9": "309"}
    # the warehouse (970) and the unlisted City - Pitt Street (shopId 731, databaseId 231) hold no public stock
    assert "970" not in directory["stock_ids"] and "231" not in directory["stock_ids"]


def test_store_page_and_postcode():
    assert parsers.parse_store_page(load_text("store_page_artarmon_trimmed.html")) == "131"
    assert parsers.parse_store_page("<html></html>") is None
    assert parsers.parse_postcode(hit("algolia_postcodes_3000.json")) == {
        "postcode": "3000", "suburb": "Melbourne", "state": "VIC", "latitude": -37.811262, "longitude": 144.964609}


def test_distance():
    assert api._distance_km(-33.8688, 151.2093, -33.8688, 151.2093) == 0
    assert 705 < api._distance_km(-33.8688, 151.2093, -37.8136, 144.9631) < 720   # Sydney -> Melbourne
    assert api._distance_km(None, 1, 2, 3) is None


# ---- reviews -----------------------------------------------------------------------------

def test_reviews_page():
    parsed = parsers.parse_reviews(load_json("bv_reviews_795454.json")["response"], "795454")
    assert parsed["total"] == 718 and len(parsed["reviews"]) == 3
    assert parsed["product_name"] == "Samsung Galaxy S25 256GB (Navy)"
    review = parsed["reviews"][0]
    assert review["id"] == "272891053" and review["title"] == "Good solid phone"
    assert review["rating"] == 5 and review["author"] == "Lethal lee"
    assert review["submitted_at"] == "2026-10-13T00:40:45.000+00:00"
    assert review["is_recommended"] is True and review["is_syndicated"] is True
    assert review["syndication_source"] == "Samsung Australia"
    assert review["secondary_ratings"] == {"Features": 4, "Performance": 5, "Design": 5, "Value": 4}
    assert review["photos"] == [] and review["responses"] == []
    assert review["product_sku"] == "795454"
    stats = parsed["statistics"]
    assert stats["count"] == 718 and stats["average"] == 4.78
    assert stats["distribution"] == {"5": 604, "4": 84, "3": 21, "2": 5, "1": 4}
    assert stats["recommended"] == 679 and stats["not_recommended"] == 27
    assert stats["secondary_averages"] == {"Quality": 4.7, "Value": 4.6}
    assert stats["first_review_at"] == "2025-02-10T05:22:10.000+00:00"


def test_reviews_empty():
    parsed = parsers.parse_reviews(load_json("bv_reviews_empty.json")["response"], "10067849")
    assert parsed == {"reviews": [], "total": 0, "statistics": None, "product_name": None}


# ---- sitemaps ----------------------------------------------------------------------------

def test_sitemap_index():
    rows = parsers.parse_sitemap_index(load_text("sitemap_index.xml"))
    assert len(rows) == 136
    assert rows[0] == {"link": "https://www.jbhifi.com.au/sitemap_agentic_discovery.xml", "type": "other", "shard": None}
    assert rows[1] == {"link": "https://www.jbhifi.com.au/sitemap_products_1.xml?from=1614264664162&to=1617675386978",
                       "type": "products", "shard": 1}
    kinds = {r["type"] for r in rows}
    assert kinds == {"other", "products", "collections", "pages", "articles"}
    assert sum(r["type"] == "products" for r in rows) == 109


def test_sitemap_products_shard():
    rows = parsers.parse_product_sitemap(load_text("sitemap_products_1_trimmed.xml"))
    assert len(rows) == 24          # the shard's leading home-page entry is dropped
    assert rows[0] == {"handle": "life-of-the-party-2018-dvd",
                       "link": "https://www.jbhifi.com.au/products/life-of-the-party-2018-dvd",
                       "title": "Life Of The Party",
                       "image": "https://cdn.shopify.com/s/files/1/0024/9803/5810/products/649764-Product-0-I.jpg?v=1572320796",
                       "lastmod": "2026-10-28T23:00:40+11:00"}


def test_sitemap_urlsets():
    pages = parsers.parse_sitemap_urlset(load_text("sitemap_pages_1_trimmed.xml"))
    assert pages[0] == {"link": "https://www.jbhifi.com.au/pages/lg", "lastmod": "2026-10-27T16:48:44+11:00",
                        "changefreq": "weekly", "image": None, "title": None}
    articles = parsers.parse_sitemap_urlset(load_text("sitemap_articles_1_trimmed.xml"))
    assert articles[0]["link"].startswith("https://www.jbhifi.com.au/blogs/")
    collections = parsers.parse_sitemap_urlset(load_text("sitemap_collections_1_trimmed.xml"))
    assert all("/collections/" in c["link"] for c in collections)
