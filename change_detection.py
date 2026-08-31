"""
Day-over-day price change classification. Shared by the dashboard
builder and the Sheets export so both agree on what counts as a
change and what counts as an alert worth surfacing.
"""


def classify_change(current_price, previous_price):
    if current_price is None:
        return None, "Unknown"
    if previous_price is None:
        return None, "New"
    delta = round(current_price - previous_price, 2)
    if delta == 0:
        return 0.0, "Unchanged"
    return delta, ("Increased" if delta > 0 else "Decreased")


def enrich_with_change(rows, previous_prices):
    """Adds previous_price / price_change / change_flag to each row in place."""
    for r in rows:
        key = (r.get("store", ""), r.get("product_name", ""), r.get("variant", ""))
        try:
            current = float(r["price"]) if r.get("price") not in (None, "") else None
        except (TypeError, ValueError):
            current = None

        prev = previous_prices.get(key)
        delta, flag = classify_change(current, prev)
        r["previous_price"] = prev if prev is not None else ""
        r["price_change"] = delta if delta is not None else ""
        r["change_flag"] = flag
    return rows


def select_alerts(rows):
    """
    Rows worth surfacing today: anything that changed price, or is
    undercutting your own price. Sorted with undercuts first, then by
    the size of the price move.
    """
    flagged = [
        r for r in rows
        if r.get("change_flag") not in (None, "Unchanged") or r.get("action_needed")
    ]
    flagged.sort(key=lambda r: (not r.get("action_needed"), -abs(r.get("price_change") or 0)))
    return flagged
