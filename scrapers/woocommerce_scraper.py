"""
Scraper for WooCommerce-powered stores (e.g. Meckeys).

WooCommerce doesn't expose a public JSON catalog feed by default, so
this parses the rendered HTML of category/shop pages instead. Selectors
are written to match standard WooCommerce markup (li.product, span.price,
ins/del for sale pricing) with a couple of fallbacks for common themes.

NOTE: if a store's theme uses non-standard class names, extraction may
come back empty or partial. Run with --debug once after setup and check
the row counts; if a store returns 0 rows, inspect its page HTML and
adjust the selectors below.
"""
import re
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

USER_AGENT = "Mozilla/5.0 (compatible; GenesisPC-PriceTracker/1.0; +https://genesispc.in)"


def _clean_price(text):
    """'₹6,999.00' -> 6999.00"""
    if not text:
        return None
    match = re.search(r"[\d,]+\.?\d*", text.replace(",", ""))
    return float(match.group()) if match else None


def _parse_price_block(product_el):
    """
    WooCommerce renders price as either:
      <span class="price"><span class="amount">₹X</span></span>
    or, on sale:
      <span class="price"><del><span class="amount">₹X</span></del>
                           <ins><span class="amount">₹Y</span></ins></span>
    Returns (current_price, compare_at_price)
    """
    price_el = product_el.select_one("span.price")
    if not price_el:
        return None, None

    ins = price_el.select_one("ins .amount, ins")
    del_ = price_el.select_one("del .amount, del")

    if ins:
        current = _clean_price(ins.get_text())
        original = _clean_price(del_.get_text()) if del_ else None
        return current, original

    # No sale: just take the first amount found (variable products may
    # show a range like "₹6,999.00 – ₹8,700.00" — we take the low end)
    amounts = price_el.select(".amount") or [price_el]
    if amounts:
        return _clean_price(amounts[0].get_text()), None
    return None, None


def _parse_listing_page(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    products = soup.select("li.product, div.product-small, div.type-product")

    rows = []
    for el in products:
        title_el = (
            el.select_one("h2.woocommerce-loop-product__title")
            or el.select_one("h3.wd-entities-title")
            or el.select_one(".product-title")
            or el.select_one("h2")
            or el.select_one("h3")
        )
        link_el = el.select_one("a[href]")
        if not title_el or not link_el:
            continue

        current, original = _parse_price_block(el)
        rows.append({
            "product_name": title_el.get_text(strip=True),
            "price": current,
            "compare_at_price": original,
            "url": urljoin(base_url, link_el.get("href", "")),
        })
    return rows


def _find_next_page(html, current_url):
    soup = BeautifulSoup(html, "html.parser")
    next_el = soup.select_one("a.next.page-numbers, a.next")
    if next_el and next_el.get("href"):
        return urljoin(current_url, next_el["href"])
    return None


def matches_brand(row, brand_keywords):
    name = (row.get("product_name") or "").lower()
    return any(kw.lower() in name for kw in brand_keywords)


def scrape(store_config, brand_keywords=None, delay=1.5, max_pages_per_category=15):
    name = store_config["name"]
    base_url = store_config["url"]
    categories = store_config.get("categories", [base_url])

    print(f"[WooCommerce] Scraping {name} ({base_url}) ...")
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    all_rows = []
    for cat_url in categories:
        url = cat_url
        for _ in range(max_pages_per_category):
            try:
                resp = session.get(url, timeout=20)
                resp.raise_for_status()
            except requests.RequestException as e:
                print(f"  [!] {url}: {e}")
                break

            page_rows = _parse_listing_page(resp.text, base_url)
            if not page_rows:
                break
            all_rows.extend(page_rows)

            next_url = _find_next_page(resp.text, url)
            time.sleep(delay)
            if not next_url or next_url == url:
                break
            url = next_url

    print(f"  -> {len(all_rows)} products found across categories")

    if brand_keywords:
        all_rows = [r for r in all_rows if matches_brand(r, brand_keywords)]
        print(f"  -> {len(all_rows)} rows kept after brand filter")

    for r in all_rows:
        r["store"] = name
        r["brand"] = ""  # WooCommerce listings don't expose vendor directly
        r["variant"] = ""
        r["currency"] = "INR"
        r["in_stock"] = None  # not reliably available on listing pages

    return all_rows
