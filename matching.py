"""
Matches a competitor's product name against your own GenesisPC.in
catalog, so we can tell whether a competitor is now pricing below you.

Product names are never identical word-for-word across stores
("MCHOSE G3 V2 Wireless Gaming Mouse" vs "MCHOSE G3 V2" vs "Mchose G3
V2 Wireless Mouse"), so this uses a normalized token-overlap + fuzzy
string score rather than requiring an exact match. Every match is
reported with its confidence score and the matched own-product name/
URL so you can sanity-check it — this is a heuristic, not a guarantee.
"""
import re
import difflib

MIN_MATCH_CONFIDENCE = 0.55


def normalize(text):
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def build_own_catalog(own_rows):
    """
    own_rows: flattened Shopify rows for your own store (one row per
    variant). Collapses to one entry per product, keeping the lowest
    variant price seen (so a "From Rs. X" style product compares at
    its cheapest configuration).
    """
    catalog = {}
    for r in own_rows:
        name = r.get("product_name", "")
        if not name:
            continue
        try:
            price = float(r["price"]) if r.get("price") not in (None, "") else None
        except (TypeError, ValueError):
            price = None

        existing = catalog.get(name)
        if existing is None or (price is not None and (existing["price"] is None or price < existing["price"])):
            catalog[name] = {
                "name": name,
                "normalized": normalize(name),
                "brand": r.get("brand", ""),
                "price": price,
                "url": r.get("url", ""),
            }
    return list(catalog.values())


def find_best_match(competitor_name, own_catalog, min_confidence=MIN_MATCH_CONFIDENCE):
    """
    Returns (matched_item_or_None, confidence_score).
    Combines token-set overlap (robust to word reordering / extra
    words like "Wireless Gaming Mouse") with a sequence-similarity
    ratio (robust to minor spelling/spacing differences).
    """
    norm_target = normalize(competitor_name)
    target_tokens = set(norm_target.split())
    if not target_tokens:
        return None, 0.0

    best_item, best_score = None, 0.0
    for item in own_catalog:
        item_tokens = set(item["normalized"].split())
        if not item_tokens:
            continue
        overlap = len(target_tokens & item_tokens) / max(1, len(target_tokens | item_tokens))
        ratio = difflib.SequenceMatcher(None, norm_target, item["normalized"]).ratio()
        score = max(overlap, ratio)
        if score > best_score:
            best_score, best_item = score, item

    if best_item and best_score >= min_confidence:
        return best_item, round(best_score, 2)
    return None, round(best_score, 2)
