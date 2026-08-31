#!/usr/bin/env python3
"""
GenesisPC competitor price tracker.

Each run:
  1. Scrapes your own GenesisPC.in catalog (for comparison prices).
  2. Scrapes each competitor store, filtered to your brand portfolio.
  3. Matches each competitor product to your closest own product and
     flags it if the competitor is now cheaper (action_needed).
  4. Compares today's prices against local history.json to classify
     each as Increased / Decreased / New / Unchanged.
  5. Appends today's rows to history.json (the source of truth).
  6. Rebuilds the dashboard (docs/index.html) from the full history.
  7. Optionally also exports to Google Sheets, if SHEET_ID is set.

Usage:
    python main.py                  # full run: history + dashboard (+ Sheets if configured)
    python main.py --no-sheet       # skip Google Sheets export
    python main.py --no-dashboard   # skip dashboard rebuild
    python main.py --config path/to/other_config.json
"""
import argparse
import csv
import json
import os
from datetime import datetime, timezone

from scrapers import shopify_scraper, woocommerce_scraper
import history_store
import change_detection
import matching
import dashboard_builder

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")

CSV_FIELDNAMES = [
    "date", "store", "brand", "product_name", "variant",
    "price", "compare_at_price", "currency", "in_stock", "url",
    "previous_price", "price_change", "change_flag",
    "own_price", "own_match", "match_confidence", "undercut_by", "action_needed",
]


def load_config(path):
    with open(path) as f:
        return json.load(f)


def scrape_store(store, brand_keywords=None):
    platform = store.get("platform")
    if platform == "shopify":
        return shopify_scraper.scrape(store, brand_keywords)
    elif platform == "woocommerce":
        return woocommerce_scraper.scrape(store, brand_keywords)
    print(f"[!] Unknown platform '{platform}' for {store.get('name')}, skipping.")
    return []


def attach_undercut_flags(rows, own_catalog):
    for r in rows:
        try:
            comp_price = float(r["price"]) if r.get("price") not in (None, "") else None
        except (TypeError, ValueError):
            comp_price = None

        match, confidence = matching.find_best_match(r.get("product_name", ""), own_catalog)

        if match and comp_price is not None and match["price"] is not None:
            r["own_price"] = match["price"]
            r["own_match"] = match["name"]
            r["match_confidence"] = confidence
            if comp_price < match["price"]:
                r["undercut_by"] = round(match["price"] - comp_price, 2)
                r["action_needed"] = True
            else:
                r["undercut_by"] = ""
                r["action_needed"] = False
        else:
            r["own_price"] = ""
            r["own_match"] = ""
            r["match_confidence"] = confidence
            r["undercut_by"] = ""
            r["action_needed"] = False
    return rows


def write_csv(rows, run_date):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    csv_path = os.path.join(OUTPUT_DIR, f"prices_{run_date}.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for r in rows:
            row = {"date": run_date}
            row.update({k: r.get(k, "") for k in CSV_FIELDNAMES if k != "date"})
            writer.writerow(row)
    print(f"[CSV] Wrote {len(rows)} rows to {csv_path}")


def run(config_path, use_sheet=True, use_dashboard=True):
    config = load_config(config_path)
    brand_keywords = config.get("brand_keywords")
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 1. Your own catalog
    own_catalog = []
    own_store = config.get("own_store")
    if own_store:
        own_rows = scrape_store(own_store, brand_keywords=None)
        own_catalog = matching.build_own_catalog(own_rows)
        print(f"[Own store] {len(own_catalog)} distinct products loaded for comparison")
    else:
        print("[!] No 'own_store' in config.json — undercut detection will be skipped.")

    # 2. Competitor stores
    all_rows = []
    for store in config["stores"]:
        try:
            rows = scrape_store(store, brand_keywords)
        except Exception as e:
            print(f"[!] {store.get('name')} failed entirely: {e}")
            continue
        all_rows.extend(rows)

    if not all_rows:
        print("No rows scraped this run — nothing written.")
        return

    # 3. Undercut detection
    if own_catalog:
        all_rows = attach_undercut_flags(all_rows, own_catalog)
        n_undercut = sum(1 for r in all_rows if r.get("action_needed"))
        print(f"[Undercut check] {n_undercut} products are currently priced below yours")

    # 4. Day-over-day change detection against local history
    existing_history = history_store.load_history()
    previous_prices = history_store.get_previous_prices(existing_history)
    all_rows = change_detection.enrich_with_change(all_rows, previous_prices)
    n_changed = sum(1 for r in all_rows if r.get("change_flag") not in (None, "Unchanged", "New"))
    print(f"[Change check] {n_changed} products changed price since the last run")

    # 5. Persist to local history (source of truth going forward)
    for r in all_rows:
        r["date"] = run_date
    history_store.save_history(history_store.DEFAULT_PATH, existing_history + all_rows)

    # 6. Dashboard
    if use_dashboard:
        dashboard_builder.build(all_rows, run_date, own_catalog_size=len(own_catalog))

    # 7. Optional Sheets export + local CSV backup
    if use_sheet:
        import sheets_writer
        sheets_writer.write_to_sheet(all_rows, run_date)
    write_csv(all_rows, run_date)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=os.path.join(os.path.dirname(__file__), "config.json"))
    parser.add_argument("--no-sheet", action="store_true", help="skip Google Sheets export")
    parser.add_argument("--no-dashboard", action="store_true", help="skip dashboard rebuild")
    args = parser.parse_args()
    run(args.config, use_sheet=not args.no_sheet, use_dashboard=not args.no_dashboard)
