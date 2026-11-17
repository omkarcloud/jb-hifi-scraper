"""JB Hi-Fi transport: plain curl_cffi with browser-impersonated TLS. No
browser, no cookies, no login. Egress: the pod's own IP
(config.jb_hifi_proxy(), knob JB_HIFI_EXIT) — every surface answered 200
direct, datacenter and AU residential from the patchright pod on
2026-10-28 (tools/egress_probe.py --via-pod, 10 surfaces). A retryable
failure drops the thread's session, so the retry rides a fresh exit (and,
for Algolia, the next fallback host).

Three upstreams, all open:

  * ALGOLIA  POST https://VTVKM5URPX-dsn.algolia.net/1/indexes/<index>/query
    with the storefront's own public search key (read from the site's
    bundle; it is in every visitor's browser). Indexes:
      shopify_products_families (+ _price_asc / _price_desc / _rating_desc /
        _published_at_desc / _published_at_asc / _title_asc / _title_desc
        sort replicas) — products, one record per SKU plus one per family
      shopify_products_families_query_suggestions — search suggestions
      shopify_store_locations (locator key) — the 267 stores, geo-searchable
      postcodes (locator key) — AU postcodes / suburbs with coordinates
    The storefront hides records failing
    `price > 0 AND product_published = 1 AND availability.displayProduct = 1`
    (VISIBLE below); every product query carries it so counts match the site.

  * SHOPIFY  GET https://www.jbhifi.com.au/products/<handle>.js — the
    product JSON (description HTML, variants with barcode / weight,
    media); a wrong handle answers a real 404. Also the HTML pages read
    for embedded JSON: the home page (window.Jbhifi.headerNav…), a
    collection page (`var filters` = its Algolia filter, its facet list,
    its sub-collection browse list), a store page (window.Jbhifi.shopId)
    and the sitemaps (sitemap.xml index, sitemap_products_N.xml shards,
    sitemap-subcollections.xml). An unknown collection / page is a real
    404.

  * BAZAARVOICE GET https://apps.bazaarvoice.com/bfd/v1/clients/jbhifi/
    api-products/cv2/resources/data/reviews.json (Conversations 5.4 behind
    BV's "bfd" proxy) and .../display/0.2alpha/product/summary. The proxy
    wants the site's own `Bv-Bfd-Token: 19287,main_site,en_AU` (its
    deployment zone + locale, from the BV bundle) and an Origin of the
    storefront; without them it answers 401 / 400.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  JbHifiUpstreamError  transport failure / 5xx / non-JSON   — retryable
  JbHifiBlocked        401 / 403 / 429 / challenge page     — retryable
  JbHifiBadRequest     upstream 400 (a filter Algolia rejects) — never retried
  JbHifiNotFound       404: unknown handle / collection / store page / shard
"""
import json
import os
import re
import sys
import threading
import time
from urllib.parse import urlencode

# Allow direct execution (python jb_hifi/fetch.py): flat imports resolve
# like under the server. Idempotent when imported normally.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import egress
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from jb_hifi.refs import SITE
from scraper_utils import retry, sessions
from scraper_utils.pages import page_title as _page_title

IMPERSONATE = "chrome"
PAGE_TIMEOUT = 40      # the home page is 1.3 MB, a collection page ~0.9 MB
API_TIMEOUT = 20

# The storefront's Algolia application + its two public search-only keys
# (in every visitor's browser: window.Jbhifi / the theme bundle, 2026-10-28).
ALGOLIA_APP = "VTVKM5URPX"
ALGOLIA_SEARCH_KEY = "1d989f0839a992bbece9099e1b091f07"   # products + suggestions
ALGOLIA_LOCATOR_KEY = "ccc7212247221af0fbaccc284b434016"  # stores + postcodes
ALGOLIA_HOSTS = (f"{ALGOLIA_APP}-dsn.algolia.net", f"{ALGOLIA_APP}-1.algolianet.com",
                 f"{ALGOLIA_APP}-2.algolianet.com", f"{ALGOLIA_APP}-3.algolianet.com")
# records the storefront never shows (its own base filter)
VISIBLE = "price > 0 AND product_published = 1 AND availability.displayProduct = 1"

BV_BASE = "https://apps.bazaarvoice.com/bfd/v1/clients/jbhifi/api-products/cv2/resources"
BV_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "bv-bfd-token": "19287,main_site,en_AU",
    "origin": SITE,
    "referer": SITE + "/",
}

PAGE_HEADERS = {
    "accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "upgrade-insecure-requests": "1",
}
JSON_HEADERS = {
    "accept": "application/json, text/javascript, */*; q=0.01",
    "x-requested-with": "XMLHttpRequest",
    "referer": SITE + "/",
}

_TITLE_RE = re.compile(r"<title>([^<]*)</title>", re.I)


class JbHifiUpstreamError(UpstreamError):
    """Transport failure / 5xx / unexpected payload — retryable."""


class JbHifiBlocked(JbHifiUpstreamError, Blocked):
    """401 / 403 / 429 or a challenge page where HTML / JSON was expected — retryable."""


class JbHifiBadRequest(BadRequest):
    """Upstream 400 (Algolia rejected the filter) — never retried."""


class JbHifiNotFound(NotFound):
    """Product / collection / store page / sitemap shard does not exist — never retried."""


# One session per cheroot worker thread: a curl handle must not be shared
# across threads; these calls are stateless so thread-lifetime sessions
# with keep-alive are enough.
_local = threading.local()


def _session():
    sess = getattr(_local, "session", None)
    if sess is None:
        from curl_cffi import requests as curl_requests
        proxy = config.jb_hifi_proxy()
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
        sess.headers.update({"accept-language": egress.accept_language(proxy)})
        _local.session = sess
        _local.algolia_host = getattr(_local, "algolia_host", 0)
    return sess


def _drop_session():
    """Close the thread's session so a poisoned keep-alive connection (or
    exit) dies; the next Algolia call also moves to the next fallback host."""
    sess = getattr(_local, "session", None)
    _local.session = None
    _local.algolia_host = (getattr(_local, "algolia_host", 0) + 1) % len(ALGOLIA_HOSTS)
    sessions.close_quietly(sess)


def _retrying(fn):
    """Run fn() under the shared retry policy (JbHifiUpstreamError only;
    NotFound / BadRequest surface immediately)."""
    return retry.run(fn, config, JbHifiUpstreamError, lambda e: _drop_session())


def _classify(resp, label, not_found=(404,)):
    """Map an HTTP status to the error taxonomy."""
    status = resp.status_code
    if status in not_found:
        raise JbHifiNotFound(f"{label} not found")
    if status == 400:
        raise JbHifiBadRequest(f"upstream rejected {label}: {resp.text[:200]}")
    if status in (401, 403, 429):
        raise JbHifiBlocked(f"HTTP {status} for {label}")
    if status != 200:
        raise JbHifiUpstreamError(f"HTTP {status} for {label}")


def _get(url, label, headers, timeout=PAGE_TIMEOUT, not_found=(404,), params=None):
    def once():
        try:
            resp = _session().get(url, headers=headers, timeout=timeout, params=params)
        except Exception as e:
            raise JbHifiUpstreamError(f"request failed: {type(e).__name__}: {e}")
        _classify(resp, label, not_found)
        return resp
    return _retrying(once)


def _json_of(resp, label):
    try:
        return resp.json()
    except Exception:
        raise JbHifiBlocked(f"non-JSON response for {label}: {resp.text[:120]!r}")


# ---- Algolia -------------------------------------------------------------------

def algolia_query(index, params, locator=False):
    """POST one query to an index; `params` is the Algolia search-parameter
    dict (query, filters, facets, hitsPerPage, page, aroundLatLng, …), sent
    url-encoded in the JSON body exactly like the storefront's client does.
    Returns the raw response dict (hits, nbHits, nbPages, facets, …)."""
    key = ALGOLIA_LOCATOR_KEY if locator else ALGOLIA_SEARCH_KEY
    encoded = {}
    for name, value in params.items():
        if value is None:
            continue
        encoded[name] = json.dumps(value) if isinstance(value, (list, dict, bool)) else value
    body = {"params": urlencode(encoded)}
    label = f"algolia {index}"

    def once():
        host = ALGOLIA_HOSTS[getattr(_local, "algolia_host", 0) % len(ALGOLIA_HOSTS)]
        url = f"https://{host}/1/indexes/{index}/query"
        headers = {
            "accept": "application/json",
            "content-type": "application/x-www-form-urlencoded",
            "x-algolia-application-id": ALGOLIA_APP,
            "x-algolia-api-key": key,
            "origin": SITE,
            "referer": SITE + "/",
        }
        try:
            resp = _session().post(url, json=body, headers=headers, timeout=API_TIMEOUT)
        except Exception as e:
            raise JbHifiUpstreamError(f"request failed: {type(e).__name__}: {e}")
        if resp.status_code == 404:
            raise JbHifiUpstreamError(f"{label}: index missing: {resp.text[:120]}")
        _classify(resp, label, not_found=())
        payload = _json_of(resp, label)
        if not isinstance(payload, dict) or "hits" not in payload:
            raise JbHifiUpstreamError(f"unexpected {label} payload: {resp.text[:120]!r}")
        return payload
    return _retrying(once)


# ---- Shopify storefront ------------------------------------------------------------

def fetch_shopify_product(handle):
    """GET /products/<handle>.js -> the Shopify product JSON (404 -> NotFound)."""
    resp = _get(f"{SITE}/products/{handle}.js", f"product {handle}", JSON_HEADERS, API_TIMEOUT)
    payload = _json_of(resp, f"product {handle}")
    if not isinstance(payload, dict) or "variants" not in payload:
        raise JbHifiUpstreamError(f"unexpected product JSON for {handle}: {resp.text[:120]!r}")
    return payload


def _html(url, label, not_found=(404,)):
    resp = _get(url, label, PAGE_HEADERS, PAGE_TIMEOUT, not_found)
    text = resp.text
    title = _page_title(text)
    if title.startswith("404 Not Found"):
        raise JbHifiNotFound(f"{label} not found")
    if "window.Jbhifi" not in text:
        raise JbHifiBlocked(f"unexpected page for {label}: {title!r}")
    return text


def fetch_home():
    """GET the home page (its header-nav JSON is the category tree)."""
    return _html(SITE + "/", "home page")


def fetch_collection_page(path):
    """GET /collections/<path> -> HTML (its embedded Algolia filter, facets,
    sub-collection browse list, breadcrumbs). Unknown -> NotFound."""
    return _html(f"{SITE}/collections/{path}", f"collection {path}")


def fetch_store_page(slug):
    """GET /pages/<slug> -> HTML (window.Jbhifi.shopId). Unknown -> NotFound."""
    return _html(f"{SITE}/pages/{slug}", f"store page {slug}")


def fetch_sitemap(url):
    """GET one sitemap (the index, a shard, or sitemap-subcollections.xml)
    -> XML text. Shopify answers 400 for a shard number past the end, which
    is a NotFound for the caller."""
    label = f"sitemap {url.rsplit('/', 1)[-1][:60]}"
    resp = _get(url, label, {"accept": "application/xml,text/xml;q=0.9,*/*;q=0.8"},
                PAGE_TIMEOUT, not_found=(400, 404))
    text = resp.text
    if "<urlset" not in text and "<sitemapindex" not in text:
        raise JbHifiBlocked(f"non-XML body for {label}: {text[:120]!r}")
    return text


# ---- Bazaarvoice ---------------------------------------------------------------------

def fetch_reviews(sku, limit, offset, sort, rating=None):
    """GET reviews.json for a SKU: one page of reviews plus the product's
    review statistics (Stats=Reviews, Include=Products)."""
    filters = [f"ProductId:{sku}"]
    if rating:
        filters.append(f"Rating:eq:{rating}")
    params = {
        "apiversion": "5.4", "Filter": filters, "Limit": limit, "Offset": offset,
        "Sort": sort, "Stats": "Reviews", "Include": "Products",
    }
    resp = _get(f"{BV_BASE}/data/reviews.json", f"reviews {sku}", BV_HEADERS, API_TIMEOUT, params=params)
    payload = _json_of(resp, f"reviews {sku}")
    body = payload.get("response") if isinstance(payload, dict) else None
    if not isinstance(body, dict) or "Results" not in body:
        raise JbHifiUpstreamError(f"unexpected reviews payload for {sku}: {resp.text[:120]!r}")
    if body.get("HasErrors"):
        raise JbHifiUpstreamError(f"reviews error for {sku}: {json.dumps(body.get('Errors'))[:200]}")
    return body


def fetch_review_summary(sku):
    """GET the rating summary (count, average, star distribution, recommended
    split) for a SKU; a SKU without reviews answers zeros, never 404."""
    params = {"productid": sku, "contentType": "reviews,questions",
              "reviewDistribution": "primaryRating,recommended", "rev": "0", "contentlocale": "en*,en_AU"}
    resp = _get(f"{BV_BASE}/data/display/0.2alpha/product/summary", f"review summary {sku}",
                BV_HEADERS, API_TIMEOUT, params=params)
    payload = _json_of(resp, f"review summary {sku}")
    body = payload.get("response") if isinstance(payload, dict) else None
    if not isinstance(body, dict) or "reviewSummary" not in body:
        raise JbHifiUpstreamError(f"unexpected summary payload for {sku}: {resp.text[:120]!r}")
    return body
