"""Cache TTL per /jb-hifi/* surface (cache.py, keyed on the validated
params). JB Hi-Fi's catalogue is re-indexed in Algolia continuously
(a hit's online_product_timestamp moves hourly), but prices change on
promotion boundaries (days) and stock per store moves through the day,
so listings and details sit at an hour and stock at 15 minutes. The
navigation, sub-collection sitemap, collection configs, store directory
and sitemap index move with merchandising deploys: a day.
"""
from datetime import timedelta

# products/search, categories/products, deals, brands (the brand facet
# counts), products/suggestions
LISTING_CACHE = timedelta(hours=1)
# the Algolia record + Shopify JSON + review summary behind products/details
PRODUCT_CACHE = timedelta(hours=1)
# products/stock: per-store status moves through the day
STOCK_CACHE = timedelta(minutes=15)
# products/reviews pages
REVIEWS_CACHE = timedelta(hours=6)
# the header nav tree, sitemap-subcollections.xml and each collection's
# page config (filters / facets / browse list)
CATEGORIES_CACHE = timedelta(hours=24)
# the store directory (267 records, one query) and store pages
STORES_CACHE = timedelta(hours=24)
# a postcode / suburb -> coordinates lookup
POSTCODE_CACHE = timedelta(days=7)
# sitemap.xml index and the product shards
SITEMAP_CACHE = timedelta(hours=12)
