"""
Maintains the canonical scrape history as a local JSON file
(data/history.json), committed to the repo by GitHub Actions each run.

This is now the single source of truth for day-over-day change
detection AND the dashboard's trend data — Google Sheets is just one
export target off the back of it, not something we need to read back
from (which avoids Sheets' automatic type-coercion of numbers/dates
turning into a headache when parsed back out).
"""
import json
import os

DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "data", "history.json")


def load_history(path=DEFAULT_PATH):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def save_history(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, separators=(",", ":"))


def get_previous_prices(history_rows):
    """
    Returns {(store, product_name, variant): most_recent_price} from
    everything recorded BEFORE today's run.
    """
    latest_price = {}
    latest_date = {}
    for r in history_rows:
        key = (r.get("store", ""), r.get("product_name", ""), r.get("variant", ""))
        date = r.get("date", "")
        try:
            price = float(r["price"]) if r.get("price") not in (None, "") else None
        except (TypeError, ValueError):
            price = None
        if price is None:
            continue
        if key not in latest_date or date >= latest_date[key]:
            latest_date[key] = date
            latest_price[key] = price
    return latest_price


def get_series(history_rows, max_points=60):
    """
    Returns {(store, product_name, variant): [(date, price), ...]}
    sorted ascending by date, capped to the most recent `max_points` —
    used for the dashboard's trend sparklines.
    """
    series = {}
    for r in history_rows:
        key = (r.get("store", ""), r.get("product_name", ""), r.get("variant", ""))
        try:
            price = float(r["price"]) if r.get("price") not in (None, "") else None
        except (TypeError, ValueError):
            price = None
        if price is None:
            continue
        series.setdefault(key, []).append((r.get("date", ""), price))

    for key in series:
        pts = sorted(set(series[key]), key=lambda p: p[0])
        series[key] = pts[-max_points:]
    return series
