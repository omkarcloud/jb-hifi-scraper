"""Reference resolvers, link builders and the choice tables for /jb-hifi/*.

ONE param per input (tripadvisor QueryOrIdField convention): `product`
accepts a SKU, a product handle OR any jbhifi.com.au product link;
`category` a collection handle / path OR a collection link; `store` a
shopId OR a store page link. Resolvers raise ValueError with a
user-facing message (RefField turns it into a 400).

Identifier shapes (www.jbhifi.com.au, 2026-10-28):
  * SKU      5-9 digits (795454). It is the Algolia objectID, the Shopify
             variant's `sku`, the Bazaarvoice product id, and the image /
             sku-page path (/pages/sku/795454 redirects to the product).
             A product family (one listing for several colours / sizes)
             carries a UUID objectID instead; details accept that too.
  * handle   the Shopify product slug (/products/<handle>), lower-case
             words joined by "-" — never all digits.
  * category a collection path: "tvs" or "mobile-phones/android-phones"
             (/collections/<parent>/<child>; the child alone is also a
             valid collection on the site).
  * shopId   1-4 digits (131 = Artarmon); the store page lives at
             /pages/<suburb-slug>, which carries window.Jbhifi.shopId.
"""
import re
from urllib.parse import unquote, urlparse

SITE = "https://www.jbhifi.com.au"

SKU_RE = re.compile(r"^[0-9]{5,9}$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,200}$")
STORE_ID_RE = re.compile(r"^[0-9]{1,4}$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _site_path(value):
    """The path of a jbhifi.com.au link (None when the value is not a link);
    a link to another host raises ValueError."""
    if not value.startswith(("http://", "https://", "//", "www.jbhifi.com.au/", "jbhifi.com.au/")):
        return None
    url = value
    if url.startswith("//"):
        url = "https:" + url
    elif not url.startswith("http"):
        url = "https://" + url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host != "jbhifi.com.au" and not host.endswith(".jbhifi.com.au"):
        raise ValueError("Must be a jbhifi.com.au link.")
    return unquote(parsed.path or "/")


def resolve_product(value):
    """SKU / family id / handle / product link -> the SKU (or family UUID)
    when known, else the handle (never all digits), which api.py turns into
    a SKU through the Shopify product JSON."""
    value = (value or "").strip()
    if SKU_RE.match(value):
        return value
    if UUID_RE.match(value):
        return value.lower()
    path = _site_path(value)
    if path is not None:
        match = re.search(r"/products/([^/?#]+)", path)
        if match:
            handle = match.group(1).lower()
            if HANDLE_RE.match(handle):
                return handle
        match = re.search(r"/pages/sku/([0-9]{5,9})", path)
        if match:
            return match.group(1)
        raise ValueError("Must be a jbhifi.com.au product link "
                         "(https://www.jbhifi.com.au/products/<handle>).")
    handle = value.lower()
    if HANDLE_RE.match(handle) and "-" in handle:
        return handle
    raise ValueError("Must be a SKU (795454), a product handle "
                     "(samsung-galaxy-s25-256gb-navy) or a jbhifi.com.au product link.")


def resolve_category(value):
    """Collection handle / path or a collection link -> the collection path
    ("tvs", "mobile-phones/android-phones")."""
    value = (value or "").strip()
    path = _site_path(value)
    if path is None:
        path = "/collections/" + value.strip("/").lower() if not value.startswith("/") else value.lower()
    match = re.match(r"^/collections/([^?#]+)", path)
    if not match:
        raise ValueError("Must be a collection handle (tvs, mobile-phones/android-phones) "
                         "or a jbhifi.com.au collection link.")
    segments = [s for s in match.group(1).strip("/").split("/") if s]
    if not segments or len(segments) > 2 or not all(_SLUG_RE.match(s) for s in segments):
        raise ValueError("Must be a collection handle (tvs, mobile-phones/android-phones) "
                         "or a jbhifi.com.au collection link.")
    return "/".join(segments)


def resolve_store(value):
    """shopId or a store page link / slug -> the shopId when numeric, else
    the /pages/<slug> slug (api.py reads window.Jbhifi.shopId off the page)."""
    value = (value or "").strip()
    if STORE_ID_RE.match(value):
        return value
    path = _site_path(value)
    if path is not None:
        match = re.match(r"^/pages/([a-z0-9-]+)/?$", path.lower())
        if match:
            return match.group(1)
        raise ValueError("Must be a jbhifi.com.au store page link "
                         "(https://www.jbhifi.com.au/pages/<suburb>).")
    slug = value.lower()
    if _SLUG_RE.match(slug):
        return slug
    raise ValueError("Must be a store id (131), a store page slug (artarmon) "
                     "or a jbhifi.com.au store page link.")


# ---- links -------------------------------------------------------------------

def product_link(handle):
    return f"{SITE}/products/{handle}" if handle else None


def sku_link(sku):
    return f"{SITE}/pages/sku/{sku}" if sku else None


def category_link(path):
    return f"{SITE}/collections/{path}" if path else None


def store_link(slug):
    return f"{SITE}/pages/{slug}" if slug else None


def absolute_link(href):
    """A nav / breadcrumb href (absolute, site-relative or bare path) -> absolute."""
    if not href:
        return None
    if href.startswith(("http://", "https://")):
        return href
    if href.startswith("//"):
        return "https:" + href
    return SITE + ("/" if not href.startswith("/") else "") + href


# ---- choice tables ------------------------------------------------------------

# public sort name -> Algolia index (the primary index for relevance, its
# sort replicas otherwise; all eight answered 200 on 2026-10-28).
PRODUCTS_INDEX = "shopify_products_families"
SORTS = {
    "relevance": PRODUCTS_INDEX,
    "price_asc": PRODUCTS_INDEX + "_price_asc",
    "price_desc": PRODUCTS_INDEX + "_price_desc",
    "rating_desc": PRODUCTS_INDEX + "_rating_desc",
    "newest": PRODUCTS_INDEX + "_published_at_desc",
    "oldest": PRODUCTS_INDEX + "_published_at_asc",
    "title_asc": PRODUCTS_INDEX + "_title_asc",
    "title_desc": PRODUCTS_INDEX + "_title_desc",
}

# public deal type -> Algolia filter. The labels are the site's own
# banner / calculated tags (facet values on 2026-10-28: Clearance 3110,
# Pre-Order 1536, On Sale 1155, Red Hot Deal 983, New at JB! 907,
# JB Exclusive 665, Refurbished 3496, Buy 2 Get 1 Free 2532).
DEAL_TYPES = {
    "any": ('onPromotion:true OR all_calculated_product_tags:"Clearance" '
            'OR all_calculated_product_tags:"Red Hot Deal"'),
    "on_sale": "onPromotion:true",
    "clearance": 'all_calculated_product_tags:"Clearance"',
    "red_hot_deal": 'all_calculated_product_tags:"Red Hot Deal"',
    "jb_exclusive": 'all_calculated_product_tags:"JB Exclusive"',
    "new": 'all_calculated_product_tags:"New at JB!"',
    "pre_order": 'all_calculated_product_tags:"Pre-Order"',
    "coming_soon": 'all_calculated_product_tags:"Coming Soon"',
    "refurbished": 'all_calculated_product_tags:"Refurbished"',
    "buy_2_get_1_free": 'all_calculated_product_tags:"Buy 2 Get 1 Free"',
    "bundle_buy": 'all_calculated_product_tags:"Bundle Buy"',
    "bonus_offer": 'all_calculated_product_tags:"Bonus Offer"',
    "online_only": 'all_calculated_product_tags:"Online Only"',
    "in_store_only": 'all_calculated_product_tags:"In Store Only"',
}

# public condition -> the site's facets.Condition value
CONDITIONS = {
    "new": "New", "as_new": "As New", "excellent": "Excellent", "very_good": "Very Good",
    "good": "Good", "refurbished": "Refurbished", "renewed": "Renewed",
}

# public marketplace switch -> Algolia filter (None = no filter)
MARKETPLACE = {"include": None, "exclude": "isMarketplace:false", "only": "isMarketplace:true"}

# Bazaarvoice review sort names
REVIEW_SORTS = {
    "newest": "SubmissionTime:desc",
    "oldest": "SubmissionTime:asc",
    "rating_desc": "Rating:desc",
    "rating_asc": "Rating:asc",
    "helpful": "Helpfulness:desc,SubmissionTime:desc",
}

AU_STATES = ("ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA")

# sitemap/links `type` -> the sitemap_<type>_N.xml family in the index
SITEMAP_TYPES = ("products", "collections", "subcollections", "pages", "articles", "other")
