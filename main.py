"""Use the scraper straight from Python — no server needed.

    python main.py

Every call is validated by the same schema the API uses and returns the same
records; results are written to output/*.json.
"""
import json
import os

from schema_fields import load_query
from jb_hifi import api, schemas

os.makedirs("output", exist_ok=True)


def run(schema_cls, fn, **params):
    data, error = load_query(schema_cls, {k: str(v) for k, v in params.items()})
    if error:
        raise ValueError(error)
    return fn(**data)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # a SKU, a product handle or any jbhifi.com.au product link
    save("product_808380.json", run(schemas.ProductSchema, api.product_details, product="808380"))

    # 20 products per page, with facets and the price range
    save("search_iphone_17_pro.json", run(schemas.ProductsSearchSchema, api.products_search, query="iphone 17 pro"))

    # stock at every store, nearest to Sydney CBD (postcode 2000) first
    save("stock_808380.json", run(schemas.ProductStockSchema, api.product_stock,
                                  product="808380", location="2000"))
