"""Marshmallow request schemas for every /jb-hifi/* route.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair):

    product    a SKU (795454), a product handle (samsung-galaxy-s25-256gb-navy)
               OR any jbhifi.com.au product link
    category   a collection handle / path (tvs, mobile-phones/android-phones)
               OR any jbhifi.com.au collection link
    store      a store id (131), a store page slug (artarmon) OR a store page link
    location   "lat,lng", a 4-digit postcode, or a suburb ("Bondi", "Bondi NSW")

The listing routes (products/search, categories/products, deals) share the
same filter set (_ListingSchema): sort, brand, condition, seller, price
bounds, in_stock / on_sale flags, the marketplace switch and `filter`
(comma-separated "Facet:Value" refinements over the site's own facets, e.g.
"Screen Size (Inches):65,Brand:Samsung"). Algolia serves at most 12,000
hits per query (nbPages caps there), so page × limit is validated against
that window.
"""
from marshmallow import ValidationError, fields, validates_schema

from schema_fields import (BaseSchema, ChoiceField, Flag, LimitField, PageField, PositiveInt, Price,
                           QueryField, RefField, StrippedString)
from jb_hifi import refs

MAX_HITS = 12000        # Algolia paginationLimitedTo on the storefront's index (nbPages = 240 at 50/page)
MAX_LIMIT = 50          # a hit is ~3 KB after attributesToRetrieve; 50 keeps a page under 200 KB
MAX_PRODUCT_SITEMAP_SHARD = 500
MAX_RADIUS_KM = 500
MAX_LOCATION_LENGTH = 80


def _max_length(n):
    """validate.Length(max=n) that tolerates the None StrippedString returns
    for an empty value (marshmallow runs validators on it; len(None) is a 500)."""
    def check(value):
        if value is not None and len(value) > n:
            raise ValidationError(f"Longer than maximum length {n}.")
    return check


class ProductRefField(RefField):
    resolver = staticmethod(refs.resolve_product)


class CategoryRefField(RefField):
    resolver = staticmethod(refs.resolve_category)


class StoreRefField(RefField):
    resolver = staticmethod(refs.resolve_store)


class FacetFilterField(fields.Field):
    """'Facet:Value, Facet:Value' -> [(facet, value)] over the site's own
    facets (names as the site shows them, case-insensitive on the value)."""

    def __init__(self, max_items=10, **kwargs):
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)
        self.max_items = max_items

    def _deserialize(self, value, attr, data, **kwargs):
        pairs = []
        for raw in str(value).split(","):
            item = raw.strip()
            if not item:
                continue
            name, sep, val = item.partition(":")
            name, val = name.strip(), val.strip()
            if not sep or not name or not val:
                raise ValidationError(f"'{item}' must be Facet:Value (e.g. Screen Size (Inches):65).")
            if (name, val) not in pairs:
                pairs.append((name, val))
        if not pairs:
            return None
        if len(pairs) > self.max_items:
            raise ValidationError(f"At most {self.max_items} refinements.")
        return pairs


class LocationField(StrippedString):
    """'lat,lng' -> {"lat", "lng"}; a postcode -> {"postcode"}; anything
    else -> {"suburb"} (resolved through the site's postcode index)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        if value is None:
            return None
        if len(value) > MAX_LOCATION_LENGTH:
            raise ValidationError(f"Longer than maximum length {MAX_LOCATION_LENGTH}.")
        parts = [p.strip() for p in value.split(",")]
        if len(parts) == 2:
            try:
                lat, lng = float(parts[0]), float(parts[1])
            except ValueError:
                lat = lng = None
            if lat is not None:
                if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                    raise ValidationError("Latitude must be -90..90 and longitude -180..180.")
                return {"lat": lat, "lng": lng}
        if value.isdigit():
            if len(value) != 4:
                raise ValidationError("An Australian postcode has 4 digits.")
            return {"postcode": value}
        return {"suburb": value}


# ---- listings ------------------------------------------------------------------------

class _ListingSchema(BaseSchema):
    page = PageField(max_page=MAX_HITS)
    limit = LimitField(default=20, max_size=MAX_LIMIT)
    sort = ChoiceField(list(refs.SORTS), load_default="relevance")
    brand = StrippedString(load_default=None, validate=_max_length(80),
                           metadata={"description": "brand name as the site shows it (Samsung, Apple)"})
    condition = ChoiceField(dict(refs.CONDITIONS))
    seller = StrippedString(load_default=None, validate=_max_length(80),
                            metadata={"description": "seller name (JB Hi-Fi, or a marketplace seller)"})
    min_price = Price()
    max_price = Price()
    in_stock = Flag()
    on_sale = Flag()
    marketplace = ChoiceField(list(refs.MARKETPLACE), load_default="include")
    filter = FacetFilterField(metadata={"description": "comma-separated Facet:Value refinements"})

    @validates_schema
    def _window(self, data, **kwargs):
        page, limit = data.get("page") or 1, data.get("limit") or 20
        if page * limit > MAX_HITS:
            raise ValidationError(f"page × limit must stay within the first {MAX_HITS} results.", "page")
        lo, hi = data.get("min_price"), data.get("max_price")
        if lo is not None and hi is not None and lo > hi:
            raise ValidationError("min_price must not exceed max_price.", "min_price")


class ProductsSearchSchema(_ListingSchema):
    query = QueryField(metadata={"description": "search keywords"})
    category = StrippedString(load_default=None, validate=_max_length(120),
                              metadata={"description": "a name from a result's category.path (Mobile Phones, LEGO; the Department / Category / Subcategory facets list them) or a collection handle (tvs)"})


class CategoryProductsSchema(_ListingSchema):
    category = CategoryRefField(metadata={"description": "collection handle / path, or a collection link"})
    query = QueryField(required=False, load_default=None, validate=_max_length(200),
                       metadata={"description": "keywords within the category"})


class DealsSchema(_ListingSchema):
    type = ChoiceField(list(refs.DEAL_TYPES), load_default="any")
    query = QueryField(required=False, load_default=None, validate=_max_length(200))
    category = StrippedString(load_default=None, validate=_max_length(120),
                              metadata={"description": "a name from a result's category.path (TVs, Hobbies; the Department / Category / Subcategory facets list them) or a collection handle (tvs)"})


# ---- products ----------------------------------------------------------------------

class ProductSchema(BaseSchema):
    product = ProductRefField(metadata={"description": "SKU, product handle, or a product link"})


class ProductReviewsSchema(BaseSchema):
    product = ProductRefField(metadata={"description": "SKU, product handle, or a product link"})
    page = PageField(max_page=1000)
    limit = LimitField(default=20, max_size=100)   # Bazaarvoice's own Limit cap
    sort = ChoiceField(dict(refs.REVIEW_SORTS), load_default=refs.REVIEW_SORTS["newest"])
    rating = PositiveInt(max_value=5, metadata={"description": "only reviews with this star rating"})


class ProductStockSchema(BaseSchema):
    product = ProductRefField(metadata={"description": "SKU, product handle, or a product link"})
    location = LocationField(metadata={"description": "lat,lng / postcode / suburb to rank stores by distance"})
    radius = PositiveInt(max_value=MAX_RADIUS_KM, load_default=None,
                         metadata={"description": "km from `location`; stores further away are dropped"})
    state = ChoiceField(list(refs.AU_STATES))
    in_stock = Flag(metadata={"description": "true = only stores with stock, false = only without"})
    limit = LimitField(default=50, max_size=300)

    @validates_schema
    def _radius_needs_location(self, data, **kwargs):
        if data.get("radius") and not data.get("location"):
            raise ValidationError("radius needs a location.", "radius")


class ProductSuggestionsSchema(BaseSchema):
    query = QueryField(max_length=100)
    limit = LimitField(default=10, max_size=20)


# ---- categories / brands ----------------------------------------------------------------

class CategoriesSchema(BaseSchema):
    category = CategoryRefField(required=False, load_default=None,
                                metadata={"description": "a collection to describe (its filters, facets, sub-collections)"})


class BrandsSchema(BaseSchema):
    query = QueryField(required=False, load_default=None, max_length=80, validate=_max_length(80),
                       metadata={"description": "brand name fragment"})
    category = StrippedString(load_default=None, validate=_max_length(120),
                              metadata={"description": "a name from a result's category.path (TVs, Hobbies; the Department / Category / Subcategory facets list them) or a collection handle (tvs)"})
    sort = ChoiceField(["count", "name"], load_default="count")
    page = PageField(max_page=50)
    limit = LimitField(default=50, max_size=200)


# ---- stores ----------------------------------------------------------------------------

class StoresSearchSchema(BaseSchema):
    query = QueryField(required=False, load_default=None, max_length=80, validate=_max_length(80),
                       metadata={"description": "store name / suburb / postcode fragment"})
    location = LocationField(metadata={"description": "lat,lng / postcode / suburb; results sorted by distance"})
    radius = PositiveInt(max_value=MAX_RADIUS_KM, load_default=None)
    state = ChoiceField(list(refs.AU_STATES))
    type = ChoiceField(["store", "home", "all"], load_default="all",
                       metadata={"description": "store = JB Hi-Fi stores, home = JB Hi-Fi HOME stores"})
    page = PageField(max_page=30)
    limit = LimitField(default=20, max_size=300)

    @validates_schema
    def _radius_needs_location(self, data, **kwargs):
        if data.get("radius") and not data.get("location"):
            raise ValidationError("radius needs a location.", "radius")


class StoreSchema(BaseSchema):
    store = StoreRefField(metadata={"description": "store id, store page slug, or a store page link"})


# ---- sitemaps --------------------------------------------------------------------------

class SitemapLinksSchema(BaseSchema):
    type = ChoiceField(list(refs.SITEMAP_TYPES),
                       metadata={"description": "only this family of child sitemaps"})


class SitemapProductsSchema(BaseSchema):
    page = PageField(max_page=MAX_PRODUCT_SITEMAP_SHARD,
                     metadata={"description": "the product sitemap shard number (sitemap_products_<page>.xml)"})
