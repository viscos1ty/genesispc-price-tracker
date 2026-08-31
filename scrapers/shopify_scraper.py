"""
Scraper for Shopify-powered stores.

Every public Shopify storefront (unless password-protected) exposes a
JSON feed of its catalog at /products.json. This is far more reliable
than parsing HTML: it's structured, includes every variant + price,
and won't break when the store changes its theme.

Docs: https://shopify.dev/docs/api/ajax/reference/product
"""
import time
import requests

USER_AGENT = "Mozilla/5.0 (compatible; GenesisPC-PriceTracker/1.0; +https://genesispc.in)"


def fetch_all_products(base_url, delay=1.0, max_pages=40):
    """
    Paginate through {base_url}/products.json until an empty page is
    returned. Returns a list of raw Shopify product dicts.
    """
    products = []
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    for page in range(1, max_pages + 1):
        url = f"{base_url.rstrip('/')}/products.json"
        try:
            resp = session.get(url, params={"limit": 250, "page": page}, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            print(f"  [!] {base_url}: failed on page {page}: {e}")
            break

        batch = data.get("products", [])
        if not batch:
            break

        products.extend(batch)
        time.sleep(delay)  # be a polite scraper

    return products


def matches_brand(product, brand_keywords):
    """Check product title/vendor/type against a list of brand keywords."""
    haystack = " ".join([
        product.get("title", ""),
        product.get("vendor", ""),
        product.get("product_type", ""),
        " ".join(product.get("tags", [])) if isinstance(product.get("tags"), list) else str(product.get("tags", "")),
    ]).lower()
    return any(kw.lower() in haystack for kw in brand_keywords)


def flatten_products(store_name, base_url, products, brand_keywords=None):
    """
    Turn raw Shopify product dicts into flat rows: one row per variant.
    If brand_keywords is given, only products matching at least one
    keyword are kept.
    """
    rows = []
    for p in products:
        if brand_keywords and not matches_brand(p, brand_keywords):
            continue

        handle = p.get("handle", "")
        product_url = f"{base_url.rstrip('/')}/products/{handle}"
        title = p.get("title", "").strip()
        vendor = p.get("vendor", "").strip()

        for v in p.get("variants", []):
            rows.append({
                "store": store_name,
                "brand": vendor,
                "product_name": title,
                "variant": (v.get("title") or "").strip(),
                "price": v.get("price"),
                "compare_at_price": v.get("compare_at_price"),
                "currency": "INR",
                "in_stock": bool(v.get("available")),
                "url": product_url,
            })
    return rows


def scrape(store_config, brand_keywords=None):
    name = store_config["name"]
    base_url = store_config["url"]
    print(f"[Shopify] Scraping {name} ({base_url}) ...")
    products = fetch_all_products(base_url)
    print(f"  -> {len(products)} total products found")
    rows = flatten_products(name, base_url, products, brand_keywords)
    print(f"  -> {len(rows)} variant rows kept after brand filter")
    return rows
