"""The /jb-hifi/* endpoint functions (route_glue's route_table calls them
with the schema's loaded kwargs).

Caching (cache.cached_call) sits here, airbnb-style, on the upstream
pieces rather than only on responses: the Algolia record of a SKU
(jb_hifi.hit), the Shopify JSON of a handle (jb_hifi.shopify), the review
summary (jb_hifi.summary), the store directory (jb_hifi.stores), the nav
tree (jb_hifi.nav), each collection's page config (jb_hifi.collection)
and the sitemap index (jb_hifi.sitemap_index) are each fetched once per
TTL, so details / stock / reviews on the same product, or every stock and
store call, share one upstream fetch of each piece.

Every product query carries the storefront's own visibility filter
(fetch.VISIBLE) plus `facets`, which is what makes nbHits agree with the
count the site shows (Algolia reports the family-grouped total only when
faceting; 2026-10-28).
"""
import math
import re

from cache import cached_call
from jb_hifi import cache_config as ttl
from jb_hifi import parsers
from jb_hifi import refs
from jb_hifi.fetch import (JbHifiBadRequest, JbHifiNotFound, VISIBLE, algolia_query, fetch_collection_page,
                           fetch_home, fetch_review_summary, fetch_reviews, fetch_shopify_product, fetch_sitemap,
                           fetch_store_page)
from jb_hifi.refs import SITE

SITEMAP_INDEX_URL = f"{SITE}/sitemap.xml"
SUBCOLLECTIONS_SITEMAP_URL = f"{SITE}/sitemap-subcollections.xml"

# the hit attributes a listing card needs (a full hit is ~15 KB, these ~3 KB)
CARD_ATTRIBUTES = [
    "objectID", "sku", "title", "secondary_title", "handle", "product_image", "vendor", "product", "category",
    "category_hierarchy", "product_type", "productGroup", "pricing", "price", "compare_at_price", "onPromotion",
    "promotionEndDate", "availability", "in_stock_store_ids", "weighted_average_rating", "banner_tags",
    "priceBannerTag", "promo_tags", "all_calculated_product_tags", "deliveryTag", "isMarketplace", "is_family",
    "familyId", "release_date", "published_at", "facets.Sold by", "facets.Condition",
]
BASE_FACETS = [
    "facets.Brand", "facets.Sold by", "facets.Condition", "facets.Price", "category_levels.level0",
    "category_levels.level1", "category_levels.level2", "availability.overallStatus", "banner_tags.label",
    "isMarketplace", "onPromotion",
]
# page facets the base set already covers (facets.Price is only read for its stats)
_BASE_FACET_NAMES = {"Brand", "Sold by", "Condition", "Price", "Category", "Primary Category", "Availability",
                     "Display Models In-Store"}
IN_STOCK_FILTER = "(availability.overallStatus:InStock OR availability.overallStatus:LimitedStock)"
_HANDLE_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*(/[a-z0-9]+(-[a-z0-9]+)*)?$")

_esc = parsers.escape_filter_value


# ---- filters ----------------------------------------------------------------------

def _category_filter(value):
    """A category name ("Mobile Phones") or a collection handle ("tvs",
    "mobile-phones/android-phones") -> an Algolia clause matching either
    the category hierarchy label or the collection handle."""
    if not value:
        return None
    handle = value.strip("/").split("/")[-1].lower()
    clauses = [f'category_hierarchy:"{_esc(value)}"']
    if _HANDLE_RE.match(value.lower()):
        clauses.append(f'collectionHandles:"{_esc(handle)}"')
    return " OR ".join(clauses)


def _facet_clause(name, value):
    """A Facet:Value refinement. The quoted (facet) form matches numeric
    facet values too ("facets.Screen Size (Inches)":"65" -> 44 TVs on
    2026-10-28, where the numeric `= 65` form matched none)."""
    return f'"facets.{_esc(name)}":"{_esc(value)}"'


def _group(clause):
    """A clause ANDed into the filter string. Algolia allows parentheses
    only around a flat OR list and never nested, so a bare `A OR B` is
    wrapped and anything already carrying parentheses (`A AND (B OR C)`,
    a collection page's own filter) goes in as is."""
    if " OR " in clause and "(" not in clause:
        return f"({clause})"
    return clause


def _listing_filters(data, *extra):
    """The Algolia `filters` string for a listing call: the visibility
    filter, the route's own clauses and the caller's refinements."""
    parts = [VISIBLE, *[_group(e) for e in extra if e]]
    if data.get("brand"):
        parts.append(f'"facets.Brand":"{_esc(data["brand"])}"')
    if data.get("condition"):
        parts.append(f'"facets.Condition":"{_esc(data["condition"])}"')
    if data.get("seller"):
        parts.append(f'"facets.Sold by":"{_esc(data["seller"])}"')
    if data.get("min_price") is not None:
        parts.append(f"price >= {data['min_price']}")
    if data.get("max_price") is not None:
        parts.append(f"price <= {data['max_price']}")
    if data.get("in_stock") is True:
        parts.append(IN_STOCK_FILTER)
    elif data.get("in_stock") is False:
        parts.append("NOT availability.overallStatus:InStock AND NOT availability.overallStatus:LimitedStock")
    if data.get("on_sale") is True:
        parts.append("onPromotion:true")
    elif data.get("on_sale") is False:
        parts.append("onPromotion:false")
    marketplace = refs.MARKETPLACE.get(data.get("marketplace") or "include")
    if marketplace:
        parts.append(marketplace)
    for name, value in data.get("filter") or []:
        parts.append(_facet_clause(name, value))
    return " AND ".join(parts)


def _listing(data, filters, query, facet_names=(), sort=None):
    """One product listing page from Algolia -> parse_listing's shape."""
    sort = sort or data.get("sort") or "relevance"
    index = refs.SORTS.get(sort, refs.PRODUCTS_INDEX)
    page, limit = data["page"], data["limit"]
    facet_names = [n for n in facet_names if n not in _BASE_FACET_NAMES]
    facets = list(BASE_FACETS) + [f"facets.{n}" for n in facet_names]
    payload = algolia_query(index, {
        "query": query or "", "page": page - 1, "hitsPerPage": limit, "filters": filters,
        "facets": facets, "maxValuesPerFacet": 50, "attributesToRetrieve": CARD_ATTRIBUTES,
        "attributesToHighlight": [], "clickAnalytics": False,
    })
    result = parsers.parse_listing(payload, page, limit, facet_names)
    # count public stores only, as /products/details and /products/stock do
    for card, hit in zip(result["results"], payload.get("hits") or []):
        card["in_stock_store_count"] = len(_stocked_store_ids(hit))
    result["sort"] = sort
    return result


# ---- products/search ---------------------------------------------------------------

def _products_search(**data):
    filters = _listing_filters(data, _category_filter(data.get("category")))
    result = _listing(data, filters, data["query"])
    return {"query": data["query"], "category": data.get("category"), **result}


def products_search(**data):
    return cached_call("jb_hifi.search", data, _products_search, ttl.LISTING_CACHE)


# ---- products/suggestions ------------------------------------------------------------

def _suggestions(query, limit):
    payload = algolia_query(refs.PRODUCTS_INDEX + "_query_suggestions",
                            {"query": query, "hitsPerPage": limit, "attributesToHighlight": []})
    rows = parsers.parse_suggestions(payload)
    return {"query": query, "count": len(rows), "suggestions": rows}


def products_suggestions(**data):
    return cached_call("jb_hifi.suggestions", data, _suggestions, ttl.LISTING_CACHE)


# ---- the shared product pieces -------------------------------------------------------

def _fetch_hit(product_id):
    payload = algolia_query(refs.PRODUCTS_INDEX, {
        "query": "", "hitsPerPage": 1, "filters": f'objectID:"{_esc(product_id)}"', "attributesToHighlight": []})
    hits = payload.get("hits") or []
    if not hits:
        raise JbHifiNotFound(f"product {product_id} not found")
    return hits[0]


def _hit(product_id):
    """The Algolia record of a SKU / family id (cached)."""
    return cached_call("jb_hifi.hit", {"product_id": product_id}, _fetch_hit, ttl.PRODUCT_CACHE)


def _shopify(handle):
    return cached_call("jb_hifi.shopify", {"handle": handle}, fetch_shopify_product, ttl.PRODUCT_CACHE)


def _summary(sku):
    return cached_call("jb_hifi.summary", {"sku": sku}, fetch_review_summary, ttl.PRODUCT_CACHE)


def _resolve(product):
    """A resolved `product` ref -> (hit, shopify JSON or None). A SKU /
    family id goes to Algolia first; a handle goes through the Shopify
    JSON (its variant SKU is the Algolia objectID)."""
    if refs.SKU_RE.match(product) or refs.UUID_RE.match(product):
        hit = _hit(product)
        return hit, None
    shop = _shopify(product)
    sku = next((v.get("sku") for v in shop.get("variants") or [] if v.get("sku")), None)
    if not sku:
        raise JbHifiNotFound(f"product {product} carries no SKU")
    return _hit(str(sku)), shop


def _review_sku(hit):
    """The SKU whose Bazaarvoice reviews a record carries: its own, or for
    a family record its first member's (reviews live on SKUs)."""
    sku = hit.get("sku") or (None if hit.get("is_family") else hit.get("objectID"))
    if not sku:
        children = hit.get("children") or []
        sku = children[0].get("SKU") if children and isinstance(children[0], dict) else None
    return str(sku) if sku else None


def _identity(hit):
    return {"sku": hit.get("sku") or (None if hit.get("is_family") else hit.get("objectID")),
            "title": hit.get("title"), "link": refs.product_link(hit.get("handle"))}


# ---- products/details ----------------------------------------------------------------

def _product_details(product):
    hit, shop = _resolve(product)
    if shop is None and hit.get("handle"):
        try:
            shop = _shopify(hit["handle"])
        except JbHifiNotFound:
            shop = None
    sku = _review_sku(hit)
    summary = _summary(sku) if sku else None
    family_hit = None
    if hit.get("familyId") and not hit.get("is_family"):
        try:
            family_hit = _hit(hit["familyId"])
        except JbHifiNotFound:
            family_hit = None
    record = parsers.parse_product(hit, shop, summary, family_hit)
    # stock locations as the public store ids /stores/* and /products/stock return
    record["in_stock_store_ids"] = _stocked_store_ids(hit)
    record["in_stock_store_count"] = len(record["in_stock_store_ids"])
    # the storefront's own visibility rule; a family member is hidden as a
    # record of its own (isHiddenByFamily) but sold through the family page
    availability = hit.get("availability") or {}
    shown = availability.get("displayProduct") or availability.get("isHiddenByFamily")
    record["is_listed"] = bool(hit.get("product_published") and shown and (hit.get("price") or 0) > 0)
    return record


def product_details(**data):
    return cached_call("jb_hifi.details", data, _product_details, ttl.PRODUCT_CACHE)


# ---- products/reviews ----------------------------------------------------------------

def _product_reviews(product, page, limit, sort, rating):
    hit, _ = _resolve(product)
    sku = _review_sku(hit)
    if not sku:
        raise JbHifiNotFound(f"product {product} carries no SKU")
    body = fetch_reviews(sku, limit, (page - 1) * limit, sort, rating)
    parsed = parsers.parse_reviews(body, sku)
    total = parsed["total"]
    return {
        **_identity(hit),
        "sort": next((k for k, v in refs.REVIEW_SORTS.items() if v == sort), sort),
        "rating_filter": rating,
        "statistics": parsed["statistics"],
        "reviews": parsed["reviews"],
        "pagination": {"page": page, "items_per_page": limit, "total_count": total,
                       "total_pages": math.ceil(total / limit) if total else 0},
    }


def product_reviews(**data):
    return cached_call("jb_hifi.reviews", data, _product_reviews, ttl.REVIEWS_CACHE)


# ---- stores (shared directory) -------------------------------------------------------

def _fetch_store_directory():
    payload = algolia_query("shopify_store_locations", {"query": "", "hitsPerPage": 1000,
                                                        "attributesToHighlight": []}, locator=True)
    return parsers.parse_store_directory(payload.get("hits") or [])


def _store_directory():
    """The store index (cached): every location plus the map from the ids a
    product's in_stock_store_ids uses to the public store ids."""
    return cached_call("jb_hifi.store_directory", {}, _fetch_store_directory, ttl.STORES_CACHE)


def _stores():
    """Every location in the store index: public stores, JB Hi-Fi HOME
    stores, plus warehouses / fulfilment centres (is_public false)."""
    return _store_directory()["stores"]


def _stocked_store_ids(hit):
    """The ids of the public stores holding stock of a product record."""
    stock_ids = _store_directory()["stock_ids"]
    return [stock_ids[str(s)] for s in hit.get("in_stock_store_ids") or [] if str(s) in stock_ids]


def _fetch_coords(location):
    """postcode / suburb -> {lat, lng, label} through the site's postcode index."""
    query = location.get("postcode") or location.get("suburb")
    payload = algolia_query("postcodes", {"query": query, "hitsPerPage": 5, "attributesToHighlight": []},
                            locator=True)
    for hit in payload.get("hits") or []:
        geo = hit.get("_geoloc") or {}
        if location.get("postcode") and hit.get("postcode") != location["postcode"]:
            continue
        if geo.get("lat") is not None:
            return {"lat": geo["lat"], "lng": geo["lng"], "label": hit.get("description")}
    raise JbHifiBadRequest(f"location {query!r} is not an Australian postcode or suburb")


def _coords(location):
    if not location:
        return None
    if "lat" in location:
        return {"lat": location["lat"], "lng": location["lng"], "label": f"{location['lat']},{location['lng']}"}
    return cached_call("jb_hifi.postcode", {"location": location}, _fetch_coords, ttl.POSTCODE_CACHE)


def _distance_km(lat1, lng1, lat2, lng2):
    if None in (lat1, lng1, lat2, lng2):
        return None
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlam = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return round(2 * 6371.0 * math.asin(math.sqrt(a)), 2)


def _rank_stores(stores, coords, radius, state):
    rows = []
    for store in stores:
        if state and (store["address"].get("state") or "").upper() != state.upper():
            continue
        row = dict(store)
        if coords:
            row["distance_km"] = _distance_km(coords["lat"], coords["lng"], store["latitude"], store["longitude"])
            if radius and (row["distance_km"] is None or row["distance_km"] > radius):
                continue
        rows.append(row)
    if coords:
        rows.sort(key=lambda r: (r["distance_km"] is None, r["distance_km"] or 0))
    else:
        rows.sort(key=lambda r: (r["name"] or "").lower())
    return rows


# ---- products/stock -----------------------------------------------------------------

_STOCK_STORE_KEYS = ("id", "name", "link", "type", "region", "address", "phone", "latitude", "longitude",
                     "distance_km", "services")


def _product_stock(product, location, radius, state, in_stock, limit):
    hit, _ = _resolve(product)
    stocked = set(_stocked_store_ids(hit))
    coords = _coords(location)
    public = [s for s in _stores() if s["is_public"] and s["type"] in ("Store", "Home")]
    ranked = _rank_stores(public, coords, radius, state)
    rows = []
    for store in ranked:
        has = store["id"] in stocked
        if in_stock is True and not has or in_stock is False and has:
            continue
        row = {k: store.get(k) for k in _STOCK_STORE_KEYS}
        row["in_stock"] = has
        rows.append(row)
    availability = parsers._availability(hit.get("availability"))
    return {
        **_identity(hit),
        "availability": availability,
        "location": coords["label"] if coords else None,
        "radius_km": radius,
        "state": state.upper() if state else None,
        "stores_with_stock": sum(1 for s in public if s["id"] in stocked),
        "stores_total": len(public),
        "count": len(rows[:limit]),
        "stores": rows[:limit],
    }


def product_stock(**data):
    return cached_call("jb_hifi.stock", data, _product_stock, ttl.STOCK_CACHE)


# ---- categories ----------------------------------------------------------------------

def _nav():
    return cached_call("jb_hifi.nav", {}, lambda: parsers.parse_nav(fetch_home()), ttl.CATEGORIES_CACHE)


def _subcollections():
    return cached_call("jb_hifi.subcollections", {},
                       lambda: parsers.parse_subcollections_sitemap(fetch_sitemap(SUBCOLLECTIONS_SITEMAP_URL)),
                       ttl.CATEGORIES_CACHE)


def _collection(path):
    """A collection's page config (its Algolia filter, facets, browse list…), cached."""
    return cached_call("jb_hifi.collection", {"path": path},
                       lambda path: parsers.parse_collection_page(fetch_collection_page(path), path),
                       ttl.CATEGORIES_CACHE)


def _collection_filter(collection):
    """The Algolia clause a collection page lists its products with: its
    own `filters` string, else membership of the collection handle."""
    if collection.get("filters"):
        return collection["filters"]
    handle = collection["handle"].split("/")[-1]
    return f'collectionHandles:"{_esc(handle)}"'


def _categories(category):
    if category:
        collection = _collection(category)
        payload = algolia_query(refs.PRODUCTS_INDEX, {
            "query": collection.get("query") or "", "hitsPerPage": 0, "facets": ["facets.Brand"],
            "filters": f"{VISIBLE} AND {_group(_collection_filter(collection))}", "attributesToHighlight": []})
        return {**collection, "products_count": payload.get("nbHits") or 0}
    menus = _nav()
    products = next((m for m in menus if m["name"] == "Products"), None)
    categories = products["children"] if products else []
    return {
        "count": len(categories),
        "categories": categories,
        "menus": [m for m in menus if m is not products],
        "collections_count": len(_subcollections()),
    }


def categories(**data):
    return cached_call("jb_hifi.categories", data, _categories, ttl.CATEGORIES_CACHE)


# ---- categories/products -------------------------------------------------------------

def _category_products(**data):
    collection = _collection(data["category"])
    filters = _listing_filters(data, _collection_filter(collection))
    query = data.get("query") or collection.get("query") or ""
    sort = data.get("sort") if data.get("sort") and data["sort"] != "relevance" else None
    if sort is None and collection.get("default_sort") in refs.SORTS:
        sort = collection["default_sort"]
    facet_names = [f["name"] for f in collection.get("facets") or []]
    result = _listing(data, filters, query, facet_names, sort)
    return {
        "category": {k: collection.get(k) for k in ("handle", "name", "link", "breadcrumbs", "subcategories")},
        "query": data.get("query"),
        **result,
    }


def category_products(**data):
    return cached_call("jb_hifi.category_products", data, _category_products, ttl.LISTING_CACHE)


# ---- deals --------------------------------------------------------------------------

def _deals(**data):
    kind = data.get("type") or "any"
    filters = _listing_filters(data, refs.DEAL_TYPES[kind], _category_filter(data.get("category")))
    result = _listing(data, filters, data.get("query"))
    return {"type": kind, "query": data.get("query"), "category": data.get("category"), **result}


def deals(**data):
    return cached_call("jb_hifi.deals", data, _deals, ttl.LISTING_CACHE)


# ---- brands --------------------------------------------------------------------------

def _brand_counts(category):
    filters = VISIBLE
    clause = _category_filter(category)
    if clause:
        filters += f" AND {_group(clause)}"
    payload = algolia_query(refs.PRODUCTS_INDEX, {
        "query": "", "hitsPerPage": 0, "filters": filters, "facets": ["facets.Brand"],
        "maxValuesPerFacet": 1000, "attributesToHighlight": []})
    return parsers.parse_brand_facets(payload)


def _brands(query, category, sort, page, limit):
    rows = cached_call("jb_hifi.brand_counts", {"category": category}, _brand_counts, ttl.LISTING_CACHE)
    if query:
        needle = query.lower()
        rows = [r for r in rows if needle in r["name"].lower()]
    if sort == "name":
        rows = sorted(rows, key=lambda r: r["name"].lower())
    else:
        rows = sorted(rows, key=lambda r: (-r["count"], r["name"].lower()))
    total = len(rows)
    start = (page - 1) * limit
    return {
        "query": query,
        "category": category,
        "brands": rows[start:start + limit],
        "pagination": {"page": page, "items_per_page": limit, "total_count": total,
                       "total_pages": math.ceil(total / limit) if total else 0},
    }


def brands(**data):
    return cached_call("jb_hifi.brands", data, _brands, ttl.LISTING_CACHE)


# ---- stores/search -------------------------------------------------------------------

def _stores_search(query, location, radius, state, type, page, limit):
    coords = _coords(location)
    kinds = {"store": ("Store",), "home": ("Home",), "all": ("Store", "Home")}[type or "all"]
    public = [s for s in _stores() if s["is_public"] and s["type"] in kinds]
    rows = _rank_stores(public, coords, radius, state)
    if query:
        needle = query.lower()

        def matches(store):
            address = store["address"]
            hay = " ".join(str(v) for v in (store["name"], address.get("suburb"), address.get("postcode"),
                                             address.get("state"), address.get("line1")) if v).lower()
            return needle in hay
        rows = [s for s in rows if matches(s)]
    total = len(rows)
    start = (page - 1) * limit
    return {
        "query": query,
        "location": coords["label"] if coords else None,
        "radius_km": radius,
        "state": state.upper() if state else None,
        "stores": rows[start:start + limit],
        "pagination": {"page": page, "items_per_page": limit, "total_count": total,
                       "total_pages": math.ceil(total / limit) if total else 0},
    }


def stores_search(**data):
    return cached_call("jb_hifi.stores_search", data, _stores_search, ttl.STORES_CACHE)


# ---- stores/details ------------------------------------------------------------------

def _store_id_of_slug(slug):
    shop_id = parsers.parse_store_page(fetch_store_page(slug))
    if not shop_id:
        raise JbHifiNotFound(f"page {slug} is not a store page")
    return shop_id


def _store_details(store):
    if store.isdigit():
        shop_id = store
    else:
        shop_id = cached_call("jb_hifi.store_slug", {"slug": store}, _store_id_of_slug, ttl.STORES_CACHE)
    for row in _stores():
        if row["id"] == shop_id:
            return row
    raise JbHifiNotFound(f"store {store} not found")


def store_details(**data):
    return cached_call("jb_hifi.store", data, _store_details, ttl.STORES_CACHE)


# ---- sitemaps -----------------------------------------------------------------------

def _sitemap_index():
    return cached_call("jb_hifi.sitemap_index", {},
                       lambda: parsers.parse_sitemap_index(fetch_sitemap(SITEMAP_INDEX_URL)), ttl.SITEMAP_CACHE)


def _sitemap_links(type):
    rows = _sitemap_index()
    if type == "subcollections":
        rows = [{"link": SUBCOLLECTIONS_SITEMAP_URL, "type": "subcollections", "shard": None}]
    else:
        rows = [r for r in rows if not type or r["type"] == type]
        if not type:
            rows = rows + [{"link": SUBCOLLECTIONS_SITEMAP_URL, "type": "subcollections", "shard": None}]
    counts = {}
    for row in rows:
        counts[row["type"]] = counts.get(row["type"], 0) + 1
    return {"type": type, "count": len(rows), "counts_by_type": counts, "sitemaps": rows}


def sitemap_links(**data):
    return cached_call("jb_hifi.sitemap_links", data, _sitemap_links, ttl.SITEMAP_CACHE)


def _sitemap_products(page):
    shards = [r for r in _sitemap_index() if r["type"] == "products"]
    shard = next((r for r in shards if r["shard"] == page), None)
    if shard is None:
        raise JbHifiNotFound(f"product sitemap shard {page} does not exist (1-{len(shards)})")
    rows = parsers.parse_product_sitemap(fetch_sitemap(shard["link"]))
    return {
        "sitemap": shard["link"],
        "count": len(rows),
        "products": rows,
        "pagination": {"page": page, "items_per_page": len(rows), "total_pages": len(shards), "total_count": None},
    }


def sitemap_products(**data):
    return cached_call("jb_hifi.sitemap_products", data, _sitemap_products, ttl.SITEMAP_CACHE)
