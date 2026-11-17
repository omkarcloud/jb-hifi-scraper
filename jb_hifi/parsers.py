"""Pure parsers for the JB Hi-Fi surfaces (no I/O; fixtures/ has one raw
capture per shape, test_parsers.py pins every function to them).

Product records come from Algolia `shopify_products_families` hits: one
record per SKU (objectID = SKU) plus one "family" record per multi-variant
listing (objectID = UUID, is_family = true, `children` = its SKUs). A hit
carries the storefront's full merchandising view: `pricing` (inc / ex GST,
was price, save amount), `availability` (overall / delivery / click &
collect / in-store status), `in_stock_store_ids` (locations by databaseId,
see parse_store_directory), `facets` (every spec as
"Name": [values] — also the filter facets), `display` (images, key
features, graphic attributes, offer messages, tracklist for music),
`product` (model, supplier EAN, dimensions, limits, seller), the tags that
drive the site's badges and the Shopify ids. The Shopify /products/<h>.js
JSON adds the long description HTML, barcode, media; Bazaarvoice adds the
review summary and the reviews themselves.
"""
import html as html_lib
import fastjson
import re
from datetime import datetime, timezone
from urllib.parse import unquote
from xml.etree import ElementTree

from jb_hifi import refs

CURRENCY = "AUD"

# facets that are the storefront's filter plumbing, not product specs
_META_FACETS = {"Brand", "Sold by", "Category", "Primary Category", "Price", "Condition",
                "Availability", "Display Models In-Store"}
_MEDIA_DEPARTMENTS = {"MUSIC", "MOVIES", "GAMES SOFTWARE"}
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


# ---- small helpers -------------------------------------------------------------------

def _text(value):
    """HTML fragment -> collapsed plain text (None for empty)."""
    if not value:
        return None
    text = _TAG_RE.sub(" ", str(value).replace("<br>", "\n").replace("</p>", "\n").replace("</li>", "\n"))
    text = html_lib.unescape(text)
    lines = [_WS_RE.sub(" ", line).strip() for line in text.split("\n")]
    text = "\n".join(line for line in lines if line)
    return text or None


def _clean(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = _WS_RE.sub(" ", value).strip()
        return value or None
    return value


def _num(value):
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number == int(number) else round(number, 2)


def _cm(metres):
    """The site stores packaged dimensions in metres (0.0286) -> cm (2.9)."""
    try:
        return round(float(metres) * 100, 1) if metres not in (None, "", 0) else None
    except (TypeError, ValueError):
        return None


def _kg(value):
    try:
        return round(float(value), 3) if value not in (None, "", 0) else None
    except (TypeError, ValueError):
        return None


def _iso(value):
    """Epoch seconds or an ISO string -> ISO-8601 (UTC for epochs)."""
    if value in (None, "", 0):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    value = str(value)
    return None if value.startswith("0001-01-01") else value


def _pct(price, was):
    if not price or not was or was <= price:
        return None
    return round((was - price) / was * 100, 1)


def _image_url(url):
    if not url:
        return None
    return "https:" + url if url.startswith("//") else url


def slugify(value):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (value or "").lower())).strip("-")


def escape_filter_value(value):
    """A user value inside an Algolia filter string ("facets.Brand":"…")."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


# ---- products: Algolia hits ------------------------------------------------------------

def _pricing(pricing, price, compare_at):
    pricing = pricing or {}
    inc = _num(pricing.get("displayPriceInc"))
    if inc is None:
        inc = _num(price)
    was = _num(pricing.get("wasPrice")) if pricing.get("displayWasPrice") else None
    if was is None and compare_at and _num(compare_at) and inc and _num(compare_at) > inc:
        was = _num(compare_at)
    save = _num(pricing.get("saveAmount")) if pricing.get("displayWasPrice") else None
    if save is None and was and inc:
        save = round(was - inc, 2)
    cashback = _num(pricing.get("cashbackAmount")) or None
    return {
        "currency": CURRENCY,
        "price": inc,
        "price_ex_gst": _num(pricing.get("displayPriceEx")),
        "gst": _num(pricing.get("displayPriceTax")),
        "was_price": was,
        "save_amount": save,
        "discount_percent": _pct(inc, was),
        "cashback": cashback,
        "price_after_cashback": _num(pricing.get("priceAfterCashback")) if cashback else None,
        "ticket_price": _num(pricing.get("coreTicketPrice")),
    }


def _availability(avail):
    avail = avail or {}
    return {
        "status": _clean(avail.get("overallStatus")),
        "statement": _clean(avail.get("availabilityStatement")),
        "delivery": _clean(avail.get("deliveryStatus")),
        "click_and_collect": _clean(avail.get("clickNCollectStatus")),
        "in_store": _clean(avail.get("cashNCarryStatus")),
        "can_buy_online": avail.get("canBuyOnline"),
        "can_pre_order": avail.get("canPreOrder"),
        "delivery_only": avail.get("deliveryOnly"),
        "online_warehouse_only": avail.get("deliveryFromOnlineWarehouseOnly"),
        "delivery_constraint": _clean(avail.get("deliveryConstraint")),
        "fulfilment": _clean(avail.get("fulfilment")),
        "lifecycle": _clean(avail.get("productLifecycle") or avail.get("productLifeCycle")),
    }


def _labels(items):
    out = []
    for item in items or []:
        label = item.get("label") if isinstance(item, dict) else item
        label = _clean(label)
        if label and label not in out:
            out.append(label)
    return out


def _images(hit):
    urls = []
    for image in ((hit.get("display") or {}).get("images") or []):
        url = _image_url(image.get("ImageUrl")) if isinstance(image, dict) else None
        if url and url not in urls:
            urls.append(url)
    main = _image_url(hit.get("product_image"))
    if main and main not in urls:
        urls.insert(0, main)
    return urls


def _family_block(hit):
    """The variant family of a hit: the family record's own `children` /
    `options`, or just the id for a child SKU (api.py fills in the rest)."""
    family_id = hit.get("familyId") or None
    if not hit.get("is_family") and not hit.get("children"):
        return {"id": family_id, "options": None, "members": None} if family_id else None
    members = []
    for child in hit.get("children") or []:
        if not isinstance(child, dict):
            continue
        handle = child.get("handle")
        members.append({
            "sku": str(child.get("SKU")) if child.get("SKU") is not None else None,
            "handle": handle,
            "link": refs.product_link(handle),
            "image": _image_url(child.get("Image")),
            "values": child.get("Values") or [],
            "button": _clean(child.get("Button")),
            "is_displayed": child.get("Display"),
            "variant_id": child.get("variant_id"),
        })
    options = [{"name": o.get("SpecificationName"), "values": o.get("Values") or [],
                "render": o.get("SpecRender")} for o in hit.get("options") or [] if isinstance(o, dict)]
    return {"id": family_id or hit.get("objectID"), "options": options, "members": members}


def parse_product_card(hit):
    """One Algolia hit -> the listing card (search / category / deals rows)."""
    product = hit.get("product") or {}
    seller = product.get("seller") or {}
    sold_by = (hit.get("facets") or {}).get("Sold by") or []
    handle = hit.get("handle")
    sku = hit.get("sku") or (hit.get("objectID") if not hit.get("is_family") else None)
    rating = _num(hit.get("weighted_average_rating"))
    return {
        "sku": str(sku) if sku is not None else None,
        "id": hit.get("objectID"),
        "title": _clean(hit.get("title")),
        "link": refs.product_link(handle),
        "handle": handle,
        "brand": _clean(product.get("brand") or hit.get("vendor")),
        "model": _clean(product.get("model")),
        "image": _image_url(hit.get("product_image")) or (_images(hit) or [None])[0],
        "category": {
            "name": _clean(hit.get("category")),
            "path": hit.get("category_hierarchy") or [],
            "department": _clean(hit.get("product_type")),
            "group": _clean((hit.get("productGroup") or {}).get("description")),
        },
        "pricing": _pricing(hit.get("pricing"), hit.get("price"), hit.get("compare_at_price")),
        "is_on_sale": bool(hit.get("onPromotion")),
        "promotion_ends": _iso(hit.get("promotionEndDate")),
        "availability": _availability(hit.get("availability")),
        "in_stock_store_count": len(hit.get("in_stock_store_ids") or []),
        "rating": rating if rating else None,
        "reviews_count": product.get("numberOfProductReviews"),
        "badges": {
            "banner": _clean((hit.get("banner_tags") or {}).get("label")),
            "price_banner": _clean((hit.get("priceBannerTag") or {}).get("label")),
            "promotions": _labels(hit.get("promo_tags")),
            "all": hit.get("all_calculated_product_tags") or [],
            "delivery": _clean(hit.get("deliveryTag")),
        },
        "seller": {"id": seller.get("id"), "name": _clean(seller.get("name") or (sold_by[0] if sold_by else None))},
        "is_marketplace": bool(hit.get("isMarketplace")),
        "is_family": bool(hit.get("is_family")),
        "family_id": hit.get("familyId") or None,
        "release_date": _iso((product.get("releaseDate")) or hit.get("release_date")),
        "published_at": _iso(hit.get("published_at")),
    }


def _specifications(facets):
    specs = []
    for name, values in (facets or {}).items():
        if name in _META_FACETS or not values:
            continue
        clean = [v for v in values if v not in (None, "")]
        if not clean:
            continue
        specs.append({"name": name, "value": clean[0] if len(clean) == 1 else clean})
    return specs


def _messages(display):
    out = []
    for msg in (display or {}).get("messages") or []:
        if not isinstance(msg, dict):
            continue
        out.append({
            "type": _clean(msg.get("Type")),
            "subtype": _clean(msg.get("SubType")),
            "heading": _clean(msg.get("Heading")),
            "short_description": _clean(msg.get("ShortDescription")),
            "description": _text(msg.get("Description")),
            "tag": _clean(msg.get("OnlineTag")),
            "starts": _iso(msg.get("Start")),
            "ends": _iso(msg.get("Finish")),
        })
    return out


def _marketplace_offers(hit):
    offers = []
    for tier in hit.get("tieredDetails") or []:
        if not isinstance(tier, dict):
            continue
        seller = tier.get("seller") or {}
        pricing = tier.get("pricing") or {}
        offers.append({
            "rank": tier.get("ranking"),
            "seller": {"id": seller.get("id"), "name": _clean(seller.get("name"))},
            "pricing": _pricing(pricing, pricing.get("displayPriceInc"), None),
            "availability": _availability(tier.get("availability")),
            "shipping_min": _num(tier.get("minShippingPrice")),
            "shipping_max": _num(tier.get("maxShippingPrice")),
        })
    return offers


def parse_shopify_product(data):
    """The Shopify /products/<handle>.js JSON -> description + variant facts."""
    if not data:
        return None
    variants = []
    for variant in data.get("variants") or []:
        variants.append({
            "id": variant.get("id"),
            "sku": variant.get("sku"),
            "title": None if variant.get("title") == "Default Title" else _clean(variant.get("title")),
            "options": [o for o in variant.get("options") or [] if o != "Default Title"],
            "price": _num((variant.get("price") or 0) / 100) if variant.get("price") is not None else None,
            "compare_at_price": _num(variant.get("compare_at_price") / 100) if variant.get("compare_at_price") else None,
            "available": variant.get("available"),
            "barcode": _clean(variant.get("barcode")),
            "weight_grams": variant.get("weight"),
            "requires_shipping": variant.get("requires_shipping"),
            "inventory_management": variant.get("inventory_management"),
            "quantity_rule": variant.get("quantity_rule"),
        })
    media = []
    for item in data.get("media") or []:
        media.append({
            "type": item.get("media_type"),
            "src": _image_url(item.get("src")),
            "alt": _clean(item.get("alt")),
            "width": item.get("width"),
            "height": item.get("height"),
            "position": item.get("position"),
        })
    return {
        "product_id": data.get("id"),
        "handle": data.get("handle"),
        "title": _clean(data.get("title")),
        "vendor": _clean(data.get("vendor")),
        "type": _clean(data.get("type")),
        "tags": data.get("tags") or [],
        "available": data.get("available"),
        "description_html": data.get("description") or None,
        "description": _text(data.get("description")),
        "images": [_image_url(u) for u in data.get("images") or []],
        "media": media,
        "options": [{"name": o.get("name"), "values": o.get("values") or []}
                    for o in data.get("options") or [] if o.get("name") != "Title"],
        "variants": variants,
        "created_at": data.get("created_at"),
        "published_at": data.get("published_at"),
    }


def parse_review_summary(body):
    """Bazaarvoice product summary -> {count, average, distribution, recommended}."""
    summary = (body or {}).get("reviewSummary") or {}
    primary = summary.get("primaryRating") or {}
    distribution = {str(d.get("key")): d.get("count") for d in primary.get("distribution") or []}
    recommended = {str(d.get("key")).lower(): d.get("count") for d in (summary.get("recommended") or {}).get("distribution") or []}
    questions = (body or {}).get("questionSummary") or {}
    count = summary.get("numReviews") or 0
    return {
        "count": count,
        "average": _num(primary.get("average")) if count else None,
        "rating_range": primary.get("ratingRange"),
        "distribution": distribution,
        "recommended": recommended.get("true"),
        "not_recommended": recommended.get("false"),
        "questions": questions.get("numQuestions"),
        "answers": questions.get("numAnswers"),
    }


def parse_product(hit, shopify=None, summary=None, family_hit=None):
    """The full details record: the listing card plus every spec, image,
    offer, variant, supplier and shipping fact on the Algolia hit, the
    Shopify JSON (description, barcode, media) and the review summary."""
    card = parse_product_card(hit)
    product = hit.get("product") or {}
    display = hit.get("display") or {}
    facets = hit.get("facets") or {}
    dims = product.get("packagedDimensions") or {}
    supplier = (product.get("supplierProductDetails") or [{}])[0] or {}
    shop = parse_shopify_product(shopify) if shopify else None
    family = _family_block(family_hit) if family_hit else _family_block(hit)
    rating_summary = parse_review_summary(summary) if summary else None
    review_count = (rating_summary or {}).get("count") or card["reviews_count"]
    graphic = [{"name": g.get("Name"), "value": g.get("Text"), "type": g.get("ContentType"),
                "icon": _image_url(g.get("URI"))} for g in display.get("graphicAttributes") or []
               if isinstance(g, dict)]
    record = dict(card)
    record.update({
        "links": {"product": card["link"], "sku_page": refs.sku_link(card["sku"]) if card["sku"] else None},
        "subtitle": _clean(hit.get("secondary_title")),
        "condition": (facets.get("Condition") or [None])[0],
        "description": (shop or {}).get("description"),
        "description_html": (shop or {}).get("description_html"),
        "key_features": display.get("keyFeatures") or [],
        "specifications": _specifications(facets),
        "graphic_attributes": graphic,
        "images": _images(hit) or (shop or {}).get("images") or [],
        "media": (shop or {}).get("media") or [],
        "offers": _messages(display),
        "marketplace_offers": _marketplace_offers(hit),
        "rating": card["rating"] or (rating_summary or {}).get("average"),
        "reviews_count": review_count,
        "review_summary": rating_summary,
        "family": family,
        "variants": (shop or {}).get("variants") or [],
        "barcode": _clean(supplier.get("supplierEAN13")) or next(
            (v["barcode"] for v in ((shop or {}).get("variants") or []) if v.get("barcode")), None),
        "supplier": {
            "number": supplier.get("supplierNumber"),
            "name": _clean(supplier.get("supplierName")),
            "stock_code": _clean(supplier.get("supplierStockCode")),
        } if supplier else None,
        "packaged_dimensions": {
            "height_cm": _cm(dims.get("height")), "width_cm": _cm(dims.get("width")),
            "depth_cm": _cm(dims.get("depth")), "weight_kg": _kg(dims.get("weight") or hit.get("weight")),
        } if (dims or hit.get("weight")) else None,
        "limit_per_order": product.get("limitPerOrder"),
        "freight_price": _num(product.get("freightPrice")),
        "free_delivery": hit.get("freeDelivery"),
        "release_date_text": _clean(product.get("releaseDateText")),
        "eligible_for_services": product.get("eligibleForServices"),
        # the artist / cast / tracklist slots are only meaningful for media
        # (a phone carries its model name in `artist`)
        "media_info": {
            "artist": _clean(display.get("artist")),
            "actors": _clean(display.get("actors")),
            "directors": _clean(display.get("directors")),
            "tracklist": display.get("tracklist") or [],
        } if (hit.get("product_type") in _MEDIA_DEPARTMENTS or display.get("tracklist")) else None,
        "collections": hit.get("collectionHandles") or [],
        "tags": [t for t in (hit.get("tags") or "").split(",") if t],
        "shopify": {
            "product_id": hit.get("product_id") or (shop or {}).get("product_id"),
            "variant_id": hit.get("variant_id"),
            "handle": card["handle"],
            "options": (shop or {}).get("options") or [],
            "type": (shop or {}).get("type") or _clean(hit.get("product_type")),
            "tags": (shop or {}).get("tags") or [],
        },
        "in_stock_store_ids": [int(s) for s in hit.get("in_stock_store_ids") or []],
        "created_at": _iso(hit.get("created_at")),
        "updated_at": _iso(hit.get("updated_at")),
    })
    return record


def parse_facets(payload, extra_names=()):
    """The Algolia facet counts of a listing -> a list of readable facet
    blocks {name, key, values: [{value, count}]} (+ price stats)."""
    facets = payload.get("facets") or {}
    stats = payload.get("facets_stats") or {}
    names = {
        "facets.Brand": "Brand", "facets.Sold by": "Seller", "facets.Condition": "Condition",
        "category_levels.level0": "Department", "category_levels.level1": "Category",
        "category_levels.level2": "Subcategory", "availability.overallStatus": "Availability",
        "banner_tags.label": "Badge", "isMarketplace": "Marketplace", "onPromotion": "On sale",
    }
    for name in extra_names:
        names.setdefault(f"facets.{name}", name)
    out = []
    for key, label in names.items():
        values = facets.get(key)
        if not values:
            continue
        block = {"name": label, "key": key.split(".")[-1] if key.startswith("facets.") else key,
                 "values": [{"value": v, "count": c} for v, c in values.items()]}
        if key in stats:
            block["stats"] = stats[key]
        out.append(block)
    price_stats = stats.get("facets.Price") or stats.get("price")
    return {"facets": out, "price_range": {"min": _num(price_stats.get("min")), "max": _num(price_stats.get("max"))}
            if price_stats else None}


def parse_listing(payload, page, limit, extra_facets=()):
    """A product query response -> {results, facets, price_range, pagination}."""
    hits = payload.get("hits") or []
    total = payload.get("nbHits") or 0
    total_pages = payload.get("nbPages") or 0
    facets = parse_facets(payload, extra_facets)
    return {
        "results": [parse_product_card(h) for h in hits],
        "facets": facets["facets"],
        "price_range": facets["price_range"],
        "pagination": {
            "page": page,
            "items_per_page": limit,
            "total_pages": total_pages,
            "total_count": total,
            "is_count_exact": bool(payload.get("exhaustiveNbHits", True)),
        },
    }


def parse_suggestions(payload):
    """Query-suggestions hits -> [{query, popularity, results_count}]."""
    out = []
    for hit in payload.get("hits") or []:
        stats = hit.get(refs.PRODUCTS_INDEX) or {}
        exact = stats.get("exact_nb_hits")
        out.append({"query": hit.get("query"), "popularity": hit.get("popularity"), "results_count": exact})
    return out


def parse_brand_facets(payload):
    """facets.Brand counts -> [{name, count, link}] (display case as the site shows it)."""
    values = (payload.get("facets") or {}).get("facets.Brand") or {}
    return [{"name": name, "count": count, "slug": slugify(name)} for name, count in values.items()]


# ---- navigation / categories -------------------------------------------------------

_NAV_RE = re.compile(r"window\.Jbhifi\.headerNavTransformedDataString\s*=\s*`([^`]*)`")


def _nav_item(item):
    href = item.get("href") or None
    link = refs.absolute_link(href)
    children = [_nav_item(c) for c in (item.get("subMenu") or item.get("menuItems") or [])
                if isinstance(c, dict) and c.get("type", "item") == "item" and (c.get("label") or "").strip()]
    handle = None
    if link:
        match = re.search(r"/collections/([^?#]+)", link)
        if match:
            handle = match.group(1).strip("/")
    return {
        "name": _clean(item.get("label")),
        "link": link,
        "handle": handle,
        "is_main_collection": bool(item.get("isMainCollection")),
        "icon": _clean(item.get("icon")) or None,
        "children": children,
    }


def parse_nav(html):
    """The home page -> the header mega-menu as a tree (top menus such as
    Products / Brands / Deals, each with their sections and links)."""
    match = _NAV_RE.search(html or "")
    if not match:
        raise ValueError("header navigation not found in page")
    data = fastjson.loads(unquote(match.group(1)))
    menus = []
    for menu in data.get("menuItems") or []:
        if not isinstance(menu, dict) or not (menu.get("label") or "").strip():
            continue
        menus.append(_nav_item(menu))
    return menus


def flatten_nav(menus):
    """Every collection link in the nav tree, depth-first, with its trail."""
    out = []

    def walk(node, trail):
        here = trail + [node["name"]]
        if node.get("handle"):
            out.append({"name": node["name"], "handle": node["handle"], "link": node["link"], "trail": here[:-1]})
        for child in node.get("children") or []:
            walk(child, here)
    for menu in menus:
        walk(menu, [])
    return out


def _js_string(html, name):
    """`var <name> = '…';` (single or double quoted, backslash escapes) -> str."""
    match = re.search(r"\b(?:var|let|const)\s+" + re.escape(name) + r"\s*=\s*('((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\")", html)
    if not match:
        return None
    raw = match.group(2) if match.group(2) is not None else match.group(3)
    return re.sub(r"\\(.)", r"\1", raw)


def _js_json(html, name):
    match = re.search(r"\b(?:var|let|const)\s+" + re.escape(name) + r"\s*=\s*([\[{].*?[\]}])\s*;", html, re.S)
    if not match:
        return None
    # `var hero = [891981,897175,];` — a JS literal with a trailing comma
    literal = re.sub(r",\s*([\]}])", r"\1", match.group(1))
    try:
        return fastjson.loads(literal)
    except ValueError:
        return None


def _browse_list(html):
    """`var browse = [{ handle: 'x', parentHandle: 'y', title: 'Z' }, …]` — a
    JS literal with bare keys; read the key/value pairs directly."""
    match = re.search(r"\bvar\s+browse\s*=\s*\[(.*?)\];", html, re.S)
    if not match:
        return []
    out = []
    for block in re.findall(r"\{(.*?)\}", match.group(1), re.S):
        item = {}
        for key, value in re.findall(r"(\w+)\s*:\s*'((?:[^'\\]|\\.)*)'", block):
            item[key] = re.sub(r"\\(.)", r"\1", value)
        if item.get("handle"):
            parent = item.get("parentHandle")
            path = f"{parent}/{item['handle']}" if parent else item["handle"]
            out.append({"name": _clean(item.get("title")), "handle": path, "link": refs.category_link(path)})
    return out


def _decoded_js_text(html, name):
    match = re.search(r"\b(?:var|let|const)\s+" + re.escape(name) + r"\s*=\s*decodeURIComponent\(`([^`]*)`\)", html)
    return _text(unquote(match.group(1))) if match else None


def parse_collection_page(html, path):
    """A /collections/<path> page -> its Algolia filter + facet list, title,
    breadcrumbs, sub-collection browse list and SEO copy."""
    handle = _js_string(html, "handle")
    if handle is None:
        raise ValueError("collection config not found in page")
    title_tag = re.search(r"<title>([^<]*)</title>", html)
    facets = [{"name": f.get("facet"), "type": f.get("type")} for f in _js_json(html, "facets") or [] if f.get("facet")]
    crumbs = []
    match = re.search(r"breadcrumbs:\s*(\[.*?\])\s*,", html, re.S)
    if match:
        try:
            crumbs = [{"name": _clean(c.get("label")), "link": refs.absolute_link(c.get("url"))}
                      for c in fastjson.loads(match.group(1)) if isinstance(c, dict)]
        except ValueError:
            crumbs = []
    sort = _js_string(html, "sortMethod") or None
    return {
        "handle": path,
        "site_handle": handle,
        "name": _clean(_js_string(html, "title")),
        "link": refs.category_link(path),
        "page_title": html_lib.unescape(title_tag.group(1)).strip() if title_tag else None,
        "filters": _js_string(html, "filters") or None,
        "category_filter": _js_string(html, "category") or None,
        "query": _js_string(html, "query") or None,
        "default_sort": sort,
        "facets": facets,
        "breadcrumbs": crumbs,
        "subcategories": _browse_list(html),
        "featured_skus": [str(s) for s in _js_json(html, "hero") or []],
        "description": _decoded_js_text(html, "seoTextA"),
    }


def parse_subcollections_sitemap(xml_text):
    """sitemap-subcollections.xml -> [{handle, link, lastmod}] for every
    /collections/<parent>/<child> URL."""
    out = []
    for entry in parse_sitemap_urlset(xml_text):
        match = re.search(r"/collections/([^?#]+)", entry["link"])
        if match:
            out.append({"handle": match.group(1).strip("/"), "link": entry["link"], "lastmod": entry.get("lastmod")})
    return out


# ---- stores ------------------------------------------------------------------------

_DAYS = {0: "Sunday", 1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday", 7: "Sunday"}


def _hours(rows):
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        out.append({"day": _DAYS.get(row.get("DayOfWeek"), row.get("DayOfWeek")), "is_open": row.get("IsOpen"),
                    "opens": row.get("OpeningTime"), "closes": row.get("ClosingTime")})
    return out


def parse_store(hit, distance_m=None):
    """One shopify_store_locations hit -> the store record."""
    address = hit.get("storeAddress") or {}
    name = _clean(hit.get("storeName"))
    public = hit.get("displayOnWeb") == "p"
    slug = slugify(name) if public else None
    geo = hit.get("_geoloc") or {}
    ranged = []
    for group in hit.get("categoriesRanged") or []:
        if isinstance(group, dict):
            ranged.extend(group.get("LevelTwoCategories") or [])
    week = []
    for row in hit.get("scheduledTradingHoursForTheComingWeek") or []:
        if isinstance(row, dict):
            week.append({"date": (row.get("Date") or "")[:10] or None, "opens": row.get("OpeningDateTime"),
                         "closes": row.get("ClosingDateTime"), "is_open": row.get("IsOpen"),
                         "is_normal": row.get("AreNormalTradingHours"), "reason": _clean(row.get("Reason"))})
    changes = []
    for row in hit.get("scheduledTradingHourChanges") or []:
        if isinstance(row, dict):
            changes.append({"date": (row.get("Date") or "")[:10] or None, "reason": _clean(row.get("Reason")),
                            "is_open": row.get("IsOpen"), "opens": row.get("OpeningTime"), "closes": row.get("ClosingTime")})
    return {
        "id": str(hit.get("shopId") if hit.get("shopId") is not None else hit.get("objectID")),
        "name": name,
        "link": refs.store_link(slug),
        "type": _clean(hit.get("locationType")),
        "region": _clean(hit.get("regionType")),
        "is_public": public,
        "is_active": hit.get("isActive"),
        "address": {
            "line1": _clean(address.get("Line1")), "line2": _clean(address.get("Line2")),
            "line3": _clean(address.get("Line3")), "suburb": _clean(address.get("Suburb")),
            "state": _clean(address.get("State")), "postcode": _clean(address.get("Postcode")),
            "country": _clean(address.get("Country")) or "Australia",
        },
        "phone": _clean(hit.get("phone")),
        "fax": _clean(hit.get("fax")),
        "latitude": geo.get("lat"),
        "longitude": geo.get("lng"),
        "distance_km": round(distance_m / 1000, 2) if distance_m is not None else None,
        "timezone": _clean(hit.get("timeZoneId")),
        "services": {
            "click_and_collect": hit.get("isAvailableForClickAndCollect"),
            "in_store_purchase": hit.get("isAvailableForCashAndCarry"),
            "delivery": hit.get("isIsAvailableForDelivery"),
            "delivery_experiences": hit.get("availableDeliveryExperiences") or [],
            "is_metro_hub": hit.get("isMetroHub"),
            "is_regional_hub": hit.get("isRegionalHub"),
        },
        "categories_ranged": ranged,
        "trading_hours": _hours(hit.get("normalTradingHours")),
        "this_week": week,
        "trading_hour_changes": changes,
    }


def parse_store_directory(hits):
    """Every shopify_store_locations hit -> {"stores": [store records],
    "stock_ids": {stock id: store id}}.

    A product's `in_stock_store_ids` lists locations by `databaseId`
    (= objectID; the storefront's own store picker keys stores on it), while
    a store page carries `shopId`, which is the `id` every store record here
    returns. The two differ for 139 of the 267 locations (Preston HOME is
    databaseId 9, shopId 309 on 2026-10-29), so stock is joined through
    `stock_ids`, which covers the public stores and HOME stores only (the
    head office, warehouses and unlisted stores hold stock too)."""
    stores, stock_ids = [], {}
    for hit in hits or []:
        store = parse_store(hit)
        stores.append(store)
        if store["is_public"] and store["type"] in ("Store", "Home"):
            key = hit.get("databaseId") if hit.get("databaseId") is not None else hit.get("objectID")
            stock_ids[str(key)] = store["id"]
    return {"stores": stores, "stock_ids": stock_ids}


def parse_store_page(html):
    """A /pages/<slug> store page -> its shopId (None when the page is not a store)."""
    match = re.search(r'window\.Jbhifi\.shopId\s*=\s*"?(\d+)"?', html or "")
    return match.group(1) if match else None


def parse_postcode(hit):
    geo = hit.get("_geoloc") or {}
    return {"postcode": hit.get("postcode"), "suburb": _clean((hit.get("locality") or "").title()),
            "state": hit.get("state"), "latitude": geo.get("lat"), "longitude": geo.get("lng")}


# ---- reviews -----------------------------------------------------------------------

def _review(row):
    secondary = {}
    for name in row.get("SecondaryRatingsOrder") or []:
        rating = (row.get("SecondaryRatings") or {}).get(name) or {}
        secondary[name] = rating.get("Value")
    responses = []
    for resp in row.get("ClientResponses") or []:
        if isinstance(resp, dict):
            responses.append({"name": _clean(resp.get("Name")), "department": _clean(resp.get("Department")),
                              "text": _clean(resp.get("Response")), "date": resp.get("Date")})
    source = row.get("SyndicationSource") or {}
    context = {k: (v or {}).get("Value") for k, v in (row.get("ContextDataValues") or {}).items()}
    return {
        "id": row.get("Id"),
        "title": _clean(row.get("Title")),
        "text": _clean(row.get("ReviewText")),
        "rating": row.get("Rating"),
        "rating_range": row.get("RatingRange"),
        "author": _clean(row.get("UserNickname")),
        "author_location": _clean(row.get("UserLocation")),
        "submitted_at": row.get("SubmissionTime"),
        "last_modified_at": row.get("LastModificationTime"),
        "is_recommended": row.get("IsRecommended"),
        "is_ratings_only": row.get("IsRatingsOnly"),
        "is_featured": row.get("IsFeatured"),
        "is_syndicated": row.get("IsSyndicated"),
        "syndication_source": _clean(source.get("Name")),
        "pros": _clean(row.get("Pros")),
        "cons": _clean(row.get("Cons")),
        "secondary_ratings": secondary,
        "context": context,
        "badges": list((row.get("Badges") or {}).keys()),
        "helpful_votes": row.get("TotalPositiveFeedbackCount"),
        "unhelpful_votes": row.get("TotalNegativeFeedbackCount"),
        "comments_count": row.get("TotalCommentCount"),
        "photos": [((p.get("Sizes") or {}).get("normal") or {}).get("Url") for p in row.get("Photos") or [] if isinstance(p, dict)],
        "videos": [v.get("VideoUrl") for v in row.get("Videos") or [] if isinstance(v, dict)],
        "responses": responses,
        "product_sku": row.get("ProductId"),
        "original_product_name": _clean(row.get("OriginalProductName")),
    }


def parse_reviews(body, sku):
    """reviews.json -> {reviews, total, statistics}; statistics come from the
    included product (Stats=Reviews) and are None for a SKU without reviews."""
    rows = body.get("Results") or []
    product = ((body.get("Includes") or {}).get("Products") or {}).get(str(sku)) or {}
    stats = product.get("ReviewStatistics") or {}
    statistics = None
    if stats:
        secondary = {k: _num((v or {}).get("AverageRating")) for k, v in (stats.get("SecondaryRatingsAverages") or {}).items()}
        statistics = {
            "count": stats.get("TotalReviewCount"),
            "average": _num(stats.get("AverageOverallRating")),
            "distribution": {str(d.get("RatingValue")): d.get("Count") for d in stats.get("RatingDistribution") or []},
            "recommended": stats.get("RecommendedCount"),
            "not_recommended": stats.get("NotRecommendedCount"),
            "secondary_averages": secondary,
            "helpful_votes": stats.get("HelpfulVoteCount"),
            "first_review_at": stats.get("FirstSubmissionTime"),
            "last_review_at": stats.get("LastSubmissionTime"),
        }
    return {
        "reviews": [_review(r) for r in rows if isinstance(r, dict)],
        "total": body.get("TotalResults") or 0,
        "statistics": statistics,
        "product_name": _clean(product.get("Name")),
    }


# ---- sitemaps -----------------------------------------------------------------------

def _strip_ns(tag):
    return tag.rsplit("}", 1)[-1]


def parse_sitemap_index(xml_text):
    """sitemap.xml -> [{link, type, shard}] for every child sitemap
    (type from the file name: products / collections / pages / articles /
    other)."""
    root = ElementTree.fromstring(xml_text.strip())
    out = []
    for node in root.iter():
        if _strip_ns(node.tag) != "sitemap":
            continue
        loc = next((c.text for c in node if _strip_ns(c.tag) == "loc"), None)
        if not loc:
            continue
        loc = html_lib.unescape(loc.strip())
        match = re.search(r"/sitemap[_-]([a-z]+)(?:_(\d+))?\.xml", loc)
        kind = match.group(1) if match else "other"
        if kind not in refs.SITEMAP_TYPES:
            kind = "other"
        out.append({"link": loc, "type": kind, "shard": int(match.group(2)) if match and match.group(2) else None})
    return out


def parse_sitemap_urlset(xml_text):
    """A urlset sitemap -> [{link, lastmod, changefreq, image, title}]."""
    root = ElementTree.fromstring(xml_text.strip().lstrip("\ufeff"))
    out = []
    for node in root.iter():
        if _strip_ns(node.tag) != "url":
            continue
        row = {"link": None, "lastmod": None, "changefreq": None, "image": None, "title": None}
        for child in node:
            tag = _strip_ns(child.tag)
            if tag == "loc":
                row["link"] = (child.text or "").strip() or None
            elif tag in ("lastmod", "changefreq"):
                row[tag] = (child.text or "").strip() or None
            elif tag == "image":
                for sub in child:
                    if _strip_ns(sub.tag) == "loc":
                        row["image"] = (sub.text or "").strip() or None
                    elif _strip_ns(sub.tag) == "title":
                        row["title"] = _clean(sub.text)
        if row["link"]:
            out.append(row)
    return out


def parse_product_sitemap(xml_text):
    """A sitemap_products_N.xml shard -> [{handle, link, title, image, lastmod}]
    (the shard's leading home-page entry is dropped)."""
    out = []
    for row in parse_sitemap_urlset(xml_text):
        match = re.search(r"/products/([^/?#]+)", row["link"])
        if not match:
            continue
        out.append({"handle": match.group(1), "link": row["link"], "title": row["title"],
                    "image": row["image"], "lastmod": row["lastmod"]})
    return out
