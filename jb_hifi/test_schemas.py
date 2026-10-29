"""Offline tests for the /jb-hifi/* request schemas and reference resolvers.

    python -m pytest jb_hifi/test_schemas.py -q
"""
import os
import sys

import pytest
from marshmallow import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jb_hifi import refs, schemas  # noqa: E402


# ---- refs --------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("795454", "795454"),
    (" 795454 ", "795454"),
    ("FB9792BC-C965-43CD-AA94-762EEC20F20B", "fb9792bc-c965-43cd-aa94-762eec20f20b"),
    ("samsung-galaxy-s25-256gb-navy", "samsung-galaxy-s25-256gb-navy"),
    ("https://www.jbhifi.com.au/products/samsung-galaxy-s25-256gb-navy", "samsung-galaxy-s25-256gb-navy"),
    ("https://www.jbhifi.com.au/products/Samsung-Galaxy-S25-256GB-Navy?variant=1#x", "samsung-galaxy-s25-256gb-navy"),
    ("//www.jbhifi.com.au/products/jbl-flip-6-portable-bluetooth-speaker-black", "jbl-flip-6-portable-bluetooth-speaker-black"),
    ("www.jbhifi.com.au/pages/sku/795454", "795454"),
])
def test_resolve_product(value, expected):
    assert refs.resolve_product(value) == expected


@pytest.mark.parametrize("value", ["", "1", "12345678901", "samsung", "https://example.com/products/x",
                                   "https://www.jbhifi.com.au/collections/tvs", "a b-c"])
def test_resolve_product_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_product(value)


@pytest.mark.parametrize("value, expected", [
    ("tvs", "tvs"),
    ("TVs", "tvs"),
    ("/collections/tvs/", "tvs"),
    ("mobile-phones/android-phones", "mobile-phones/android-phones"),
    ("https://www.jbhifi.com.au/collections/mobile-phones/android-phones?page=2", "mobile-phones/android-phones"),
    ("https://jbhifi.com.au/collections/hot-deals-on-tvs", "hot-deals-on-tvs"),
])
def test_resolve_category(value, expected):
    assert refs.resolve_category(value) == expected


@pytest.mark.parametrize("value", ["", "a/b/c", "https://www.jbhifi.com.au/products/x",
                                   "https://example.com/collections/tvs", "tvs!"])
def test_resolve_category_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_category(value)


@pytest.mark.parametrize("value, expected", [
    ("131", "131"),
    ("artarmon", "artarmon"),
    ("City-Westfield-Sydney", "city-westfield-sydney"),
    ("https://www.jbhifi.com.au/pages/city-westfield-sydney", "city-westfield-sydney"),
    ("https://www.jbhifi.com.au/pages/artarmon/", "artarmon"),
])
def test_resolve_store(value, expected):
    assert refs.resolve_store(value) == expected


@pytest.mark.parametrize("value", ["", "https://example.com/pages/artarmon",
                                   "https://www.jbhifi.com.au/collections/tvs", "a b"])
def test_resolve_store_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_store(value)


def test_links():
    assert refs.product_link("x-y") == "https://www.jbhifi.com.au/products/x-y"
    assert refs.sku_link("795454") == "https://www.jbhifi.com.au/pages/sku/795454"
    assert refs.category_link("tvs/cheap-tvs") == "https://www.jbhifi.com.au/collections/tvs/cheap-tvs"
    assert refs.store_link("artarmon") == "https://www.jbhifi.com.au/pages/artarmon"
    assert refs.store_link(None) is None
    assert refs.absolute_link("/collections/tvs") == "https://www.jbhifi.com.au/collections/tvs"
    assert refs.absolute_link("collections/tvs") == "https://www.jbhifi.com.au/collections/tvs"
    assert refs.absolute_link("https://www.jbhifi.com.au/pages/apple") == "https://www.jbhifi.com.au/pages/apple"
    assert refs.absolute_link("") is None


def test_choice_tables_are_consistent():
    assert set(refs.SORTS) == {"relevance", "price_asc", "price_desc", "rating_desc", "newest", "oldest",
                               "title_asc", "title_desc"}
    assert all(v.startswith(refs.PRODUCTS_INDEX) for v in refs.SORTS.values())
    assert "any" in refs.DEAL_TYPES and "(" not in refs.DEAL_TYPES["any"]   # api._group adds the parentheses
    assert refs.MARKETPLACE["include"] is None


# ---- product schemas ------------------------------------------------------------------

def test_product_schema():
    assert schemas.ProductSchema().load({"product": "795454"}) == {"product": "795454"}
    loaded = schemas.ProductSchema().load({"product": "https://www.jbhifi.com.au/products/samsung-galaxy-s25-256gb-navy"})
    assert loaded == {"product": "samsung-galaxy-s25-256gb-navy"}


@pytest.mark.parametrize("value", ["", "x", "https://example.com/products/x"])
def test_product_schema_rejects(value):
    with pytest.raises(ValidationError):
        schemas.ProductSchema().load({"product": value})


def test_product_schema_rejects_sibling_params():
    with pytest.raises(ValidationError):
        schemas.ProductSchema().load({"product": "795454", "sku": "795454"})
    with pytest.raises(ValidationError):
        schemas.ProductSchema().load({"product": "795454", "url": "https://www.jbhifi.com.au/products/x"})


def test_reviews_schema():
    loaded = schemas.ProductReviewsSchema().load({"product": "795454"})
    assert loaded == {"product": "795454", "page": 1, "limit": 20, "sort": "SubmissionTime:desc", "rating": None}
    loaded = schemas.ProductReviewsSchema().load({"product": "795454", "sort": "Helpful", "rating": "5", "page": "3"})
    assert loaded["sort"] == refs.REVIEW_SORTS["helpful"]
    assert loaded["rating"] == 5 and loaded["page"] == 3
    for bad in ({"product": "795454", "rating": "6"}, {"product": "795454", "limit": "101"},
                {"product": "795454", "sort": "best"}):
        with pytest.raises(ValidationError):
            schemas.ProductReviewsSchema().load(bad)


def test_stock_schema_and_location_field():
    loaded = schemas.ProductStockSchema().load({"product": "795454"})
    assert loaded == {"product": "795454", "location": None, "radius": None, "state": None, "in_stock": None,
                      "limit": 50}
    assert schemas.ProductStockSchema().load({"product": "795454", "location": "2000"})["location"] == {"postcode": "2000"}
    assert schemas.ProductStockSchema().load({"product": "795454", "location": "-33.87, 151.21"})["location"] == \
        {"lat": -33.87, "lng": 151.21}
    assert schemas.ProductStockSchema().load({"product": "795454", "location": "Bondi  Junction"})["location"] == \
        {"suburb": "Bondi Junction"}
    loaded = schemas.ProductStockSchema().load({"product": "795454", "location": "3000", "radius": "25",
                                                "state": "Vic", "in_stock": "yes"})
    assert loaded["radius"] == 25 and loaded["state"] == "vic" and loaded["in_stock"] is True
    for bad in ({"product": "795454", "location": "99999"}, {"product": "795454", "location": "91,200"},
                {"product": "795454", "radius": "10"}, {"product": "795454", "radius": "501", "location": "2000"},
                {"product": "795454", "state": "XX"}, {"product": "795454", "in_stock": "maybe"}):
        with pytest.raises(ValidationError):
            schemas.ProductStockSchema().load(bad)


def test_suggestions_schema():
    assert schemas.ProductSuggestionsSchema().load({"query": " iph "}) == {"query": "iph", "limit": 10}
    with pytest.raises(ValidationError):
        schemas.ProductSuggestionsSchema().load({})
    with pytest.raises(ValidationError):
        schemas.ProductSuggestionsSchema().load({"query": "x", "limit": "21"})


# ---- listing schemas ------------------------------------------------------------------

def test_search_schema_defaults():
    loaded = schemas.ProductsSearchSchema().load({"query": "iphone 17"})
    assert loaded == {
        "query": "iphone 17", "category": None, "page": 1, "limit": 20, "sort": "relevance", "brand": None,
        "condition": None, "seller": None, "min_price": None, "max_price": None, "in_stock": None,
        "on_sale": None, "marketplace": "include", "filter": None,
    }


def test_search_schema_filters():
    loaded = schemas.ProductsSearchSchema().load({
        "query": "tv", "sort": "Price_Desc", "brand": "Samsung", "condition": "As_New", "seller": "JB Hi-Fi",
        "min_price": "100", "max_price": "2500.5", "in_stock": "true", "on_sale": "0", "marketplace": "Exclude",
        "filter": "Screen Size (Inches):65, Smart OS:Tizen,Screen Size (Inches):65", "page": "3", "limit": "50",
        "category": "Mobile Phones",
    })
    assert loaded["sort"] == "price_desc"
    assert loaded["condition"] == "As New"
    assert loaded["min_price"] == 100 and loaded["max_price"] == 2500.5
    assert loaded["in_stock"] is True and loaded["on_sale"] is False
    assert loaded["marketplace"] == "exclude"
    assert loaded["filter"] == [("Screen Size (Inches)", "65"), ("Smart OS", "Tizen")]
    assert loaded["page"] == 3 and loaded["limit"] == 50


@pytest.mark.parametrize("bad", [
    {},                                              # query required
    {"query": ""},
    {"query": "tv", "page": "0"},
    {"query": "tv", "limit": "51"},
    {"query": "tv", "page": "241", "limit": "50"},   # past Algolia's 12,000-hit window
    {"query": "tv", "sort": "cheapest"},
    {"query": "tv", "condition": "mint"},
    {"query": "tv", "marketplace": "maybe"},
    {"query": "tv", "min_price": "-1"},
    {"query": "tv", "min_price": "500", "max_price": "100"},
    {"query": "tv", "filter": "nocolon"},
    {"query": "tv", "filter": "Brand:"},
    {"query": "tv", "filter": ",".join(f"F{i}:v" for i in range(11))},
    {"query": "tv", "url": "x"},
])
def test_search_schema_rejects(bad):
    with pytest.raises(ValidationError):
        schemas.ProductsSearchSchema().load(bad)


def test_optional_strings_accept_empty():
    # an empty optional string is "not given" (None), never a len(None) 500
    loaded = schemas.ProductsSearchSchema().load({"query": "tv", "brand": "", "seller": " ", "category": ""})
    assert loaded["brand"] is None and loaded["seller"] is None and loaded["category"] is None
    assert schemas.DealsSchema().load({"category": ""})["category"] is None
    assert schemas.BrandsSchema().load({"category": ""})["category"] is None
    assert schemas.ProductStockSchema().load({"product": "795454", "location": ""})["location"] is None
    # optional QueryFields too (QueryField defaults to Length(min=1), which also len()s the None)
    assert schemas.CategoryProductsSchema().load({"category": "tvs", "query": ""})["query"] is None
    assert schemas.DealsSchema().load({"query": " "})["query"] is None
    assert schemas.BrandsSchema().load({"query": ""})["query"] is None
    assert schemas.StoresSearchSchema().load({"query": ""})["query"] is None
    with pytest.raises(ValidationError):
        schemas.StoresSearchSchema().load({"query": "x" * 81})
    with pytest.raises(ValidationError):
        schemas.ProductsSearchSchema().load({"query": "tv", "brand": "x" * 81})
    with pytest.raises(ValidationError):
        schemas.ProductStockSchema().load({"product": "795454", "location": "x" * 81})


def test_search_schema_window_allows_last_page():
    loaded = schemas.ProductsSearchSchema().load({"query": "tv", "page": "240", "limit": "50"})
    assert loaded["page"] == 240


def test_category_products_schema():
    loaded = schemas.CategoryProductsSchema().load({"category": "https://www.jbhifi.com.au/collections/tvs/cheap-tvs"})
    assert loaded["category"] == "tvs/cheap-tvs" and loaded["query"] is None and loaded["sort"] == "relevance"
    with pytest.raises(ValidationError):
        schemas.CategoryProductsSchema().load({})
    with pytest.raises(ValidationError):
        schemas.CategoryProductsSchema().load({"category": "a/b/c"})


def test_deals_schema():
    loaded = schemas.DealsSchema().load({})
    assert loaded["type"] == "any" and loaded["query"] is None and loaded["category"] is None
    assert schemas.DealsSchema().load({"type": "Red_Hot_Deal"})["type"] == "red_hot_deal"
    with pytest.raises(ValidationError):
        schemas.DealsSchema().load({"type": "cheap"})


# ---- categories / brands / stores / sitemaps -------------------------------------------

def test_categories_schema():
    assert schemas.CategoriesSchema().load({}) == {"category": None}
    assert schemas.CategoriesSchema().load({"category": "/collections/tvs"}) == {"category": "tvs"}
    with pytest.raises(ValidationError):
        schemas.CategoriesSchema().load({"category": "https://example.com/collections/tvs"})


def test_brands_schema():
    loaded = schemas.BrandsSchema().load({})
    assert loaded == {"query": None, "category": None, "sort": "count", "page": 1, "limit": 50}
    assert schemas.BrandsSchema().load({"sort": "Name", "limit": "200"})["sort"] == "name"
    with pytest.raises(ValidationError):
        schemas.BrandsSchema().load({"sort": "popular"})
    with pytest.raises(ValidationError):
        schemas.BrandsSchema().load({"limit": "201"})


def test_stores_search_schema():
    loaded = schemas.StoresSearchSchema().load({})
    assert loaded == {"query": None, "location": None, "radius": None, "state": None, "type": "all",
                      "page": 1, "limit": 20}
    loaded = schemas.StoresSearchSchema().load({"location": "Bondi", "radius": "20", "type": "Home", "state": "nsw"})
    assert loaded["location"] == {"suburb": "Bondi"} and loaded["type"] == "home" and loaded["state"] == "nsw"
    with pytest.raises(ValidationError):
        schemas.StoresSearchSchema().load({"radius": "20"})          # radius needs a location
    with pytest.raises(ValidationError):
        schemas.StoresSearchSchema().load({"type": "warehouse"})


def test_store_schema():
    assert schemas.StoreSchema().load({"store": "131"}) == {"store": "131"}
    assert schemas.StoreSchema().load({"store": "https://www.jbhifi.com.au/pages/artarmon"}) == {"store": "artarmon"}
    with pytest.raises(ValidationError):
        schemas.StoreSchema().load({})
    with pytest.raises(ValidationError):
        schemas.StoreSchema().load({"store": "131", "id": "131"})


def test_sitemap_schemas():
    assert schemas.SitemapLinksSchema().load({}) == {"type": None}
    assert schemas.SitemapLinksSchema().load({"type": "Products"}) == {"type": "products"}
    with pytest.raises(ValidationError):
        schemas.SitemapLinksSchema().load({"type": "images"})
    assert schemas.SitemapProductsSchema().load({}) == {"page": 1}
    assert schemas.SitemapProductsSchema().load({"page": "109"}) == {"page": 109}
    with pytest.raises(ValidationError):
        schemas.SitemapProductsSchema().load({"page": "0"})
    with pytest.raises(ValidationError):
        schemas.SitemapProductsSchema().load({"page": "501"})
