"""
Builds a static HTML dashboard (docs/index.html) from today's scrape
results plus the accumulated price history. No build step, no JS
framework, no external dependencies beyond one Google Font — it's a
single self-contained file that GitHub Pages can serve as-is from the
/docs folder.

Design intent: a monitoring console, not a marketing page. A ticker
strip surfaces today's undercuts the moment the page loads (the thing
you're checking for), stat cards give the at-a-glance count, and the
full catalog table is client-side filterable/sortable with an inline
SVG sparkline per row so a trend is visible without opening anything.
"""
import html
import json
import os
from datetime import datetime

import history_store

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "docs", "index.html")


# ---------- small helpers ----------

def _fmt_price(p):
    if p in (None, ""):
        return "—"
    try:
        return f"₹{float(p):,.0f}"
    except (TypeError, ValueError):
        return str(p)


def _fmt_delta(p):
    if p in (None, ""):
        return ""
    try:
        v = float(p)
    except (TypeError, ValueError):
        return ""
    sign = "+" if v > 0 else ""
    return f"{sign}{v:,.0f}"


def _esc(s):
    return html.escape(str(s if s is not None else ""))


def sparkline_svg(points, width=96, height=28, color="#8791A6"):
    """points: list of (date, price). Returns an inline <svg> string."""
    prices = [p for _, p in points]
    if len(prices) < 2:
        return f'<svg width="{width}" height="{height}" class="spark"></svg>'

    lo, hi = min(prices), max(prices)
    span = (hi - lo) or 1
    n = len(prices)
    step = width / (n - 1)

    coords = []
    for i, p in enumerate(prices):
        x = i * step
        y = height - ((p - lo) / span) * (height - 4) - 2
        coords.append(f"{x:.1f},{y:.1f}")

    last_x, last_y = coords[-1].split(",")
    polyline = " ".join(coords)
    return (
        f'<svg width="{width}" height="{height}" class="spark" viewBox="0 0 {width} {height}">'
        f'<polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="1.75" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{last_x}" cy="{last_y}" r="2.4" fill="{color}"/>'
        f'</svg>'
    )


CHANGE_COLOR = {
    "Increased": "#3ED9B0",
    "Decreased": "#F5A623",
    "Unchanged": "#4A5266",
    "New": "#6C7A96",
    "Unknown": "#4A5266",
}


# ---------- section builders ----------

def _build_ticker(alerts):
    if not alerts:
        return '<span class="ticker-item ticker-quiet">No price changes or undercuts on the latest run — all quiet.</span>'
    items = []
    for r in alerts:
        if r.get("action_needed"):
            items.append(
                f'<span class="ticker-item ticker-urgent">▲ UNDERCUT · {_esc(r["product_name"])} '
                f'@ {_esc(r["store"])} now {_fmt_price(r["price"])} '
                f'(you: {_fmt_price(r.get("own_price"))}, −₹{_fmt_price(r.get("undercut_by")).lstrip("₹")})</span>'
            )
        else:
            arrow = "▲" if r.get("change_flag") == "Increased" else "▼"
            items.append(
                f'<span class="ticker-item">{arrow} {_esc(r["product_name"])} @ {_esc(r["store"])} '
                f'{_fmt_price(r.get("previous_price"))} → {_fmt_price(r["price"])}</span>'
            )
    # Duplicate the strip so the CSS marquee loops seamlessly
    strip = "<span class='ticker-sep'>&nbsp;&nbsp;•&nbsp;&nbsp;</span>".join(items)
    return strip


def _build_stat_cards(rows, alerts, own_catalog_size, store_names):
    n_products = len({(r["store"], r["product_name"], r["variant"]) for r in rows})
    n_changes = sum(1 for r in alerts if not r.get("action_needed"))
    n_undercuts = sum(1 for r in rows if r.get("action_needed"))
    n_stores = len(store_names)

    cards = [
        ("Products tracked", n_products, ""),
        ("Price changes today", n_changes, "warn" if n_changes else ""),
        ("Undercuts right now", n_undercuts, "urgent" if n_undercuts else ""),
        ("Stores monitored", n_stores, ""),
    ]
    html_cards = []
    for label, value, tone in cards:
        cls = f"stat-card {tone}".strip()
        html_cards.append(
            f'<div class="{cls}"><div class="stat-value">{value}</div>'
            f'<div class="stat-label">{_esc(label)}</div></div>'
        )
    return "\n".join(html_cards)


def _build_alert_cards(alerts):
    if not alerts:
        return '<p class="empty-state">Nothing needs a look today. Check back after the next run.</p>'

    cards = []
    for r in alerts:
        urgent = bool(r.get("action_needed"))
        tone_class = "alert-urgent" if urgent else "alert-normal"
        flag = r.get("change_flag", "")
        flag_color = CHANGE_COLOR.get(flag, "#4A5266")

        if urgent:
            headline = (
                f'<span class="badge badge-urgent">ACT NOW</span> '
                f'Competitor priced below you by <strong>{_fmt_price(r.get("undercut_by"))}</strong>'
            )
            detail = (
                f'Your price: {_fmt_price(r.get("own_price"))} '
                f'· matched to <em>{_esc(r.get("own_match",""))}</em> '
                f'(confidence {r.get("match_confidence","")})'
            )
        else:
            headline = f'<span class="badge" style="background:{flag_color}22;color:{flag_color}">{_esc(flag)}</span>'
            detail = f'{_fmt_price(r.get("previous_price"))} → {_fmt_price(r.get("price"))} ({_fmt_delta(r.get("price_change"))})'

        cards.append(f'''
        <a class="alert-card {tone_class}" href="{_esc(r.get("url","#"))}" target="_blank" rel="noopener">
          <div class="alert-top">
            <span class="alert-product">{_esc(r["product_name"])}</span>
            <span class="alert-store">{_esc(r["store"])}</span>
          </div>
          <div class="alert-headline">{headline}</div>
          <div class="alert-detail">{detail}</div>
        </a>''')
    return "\n".join(cards)


def _build_table_rows(rows, series):
    trs = []
    for r in rows:
        key = (r["store"], r["product_name"], r["variant"])
        pts = series.get(key, [])
        flag = r.get("change_flag", "")
        color = CHANGE_COLOR.get(flag, "#8791A6")
        spark = sparkline_svg(pts, color=color)
        urgent = bool(r.get("action_needed"))

        trs.append(f'''
        <tr class="{'row-urgent' if urgent else ''}"
            data-store="{_esc(r["store"])}" data-brand="{_esc(r.get("brand",""))}"
            data-search="{_esc((r["product_name"] + ' ' + r["store"] + ' ' + r.get('brand','')).lower())}">
          <td class="cell-product">
            <a href="{_esc(r.get("url","#"))}" target="_blank" rel="noopener">{_esc(r["product_name"])}</a>
            {f'<span class="variant-tag">{_esc(r["variant"])}</span>' if r.get("variant") else ''}
          </td>
          <td>{_esc(r["store"])}</td>
          <td class="mono">{_fmt_price(r["price"])}</td>
          <td class="mono" style="color:{color}">{_fmt_delta(r.get("price_change")) or "–"}</td>
          <td>{spark}</td>
          <td class="mono">{_fmt_price(r.get("own_price"))}</td>
          <td>{'<span class="badge badge-urgent">UNDERCUT</span>' if urgent else ''}</td>
        </tr>''')
    return "\n".join(trs)


# ---------- main build ----------

def build(rows, run_date, own_catalog_size=0, output_path=OUTPUT_PATH, history_path=history_store.DEFAULT_PATH):
    history_rows = history_store.load_history(history_path)
    series = history_store.get_series(history_rows + rows)

    from change_detection import select_alerts
    alerts = select_alerts(rows)
    store_names = sorted({r["store"] for r in rows})
    brand_names = sorted({r.get("brand", "") for r in rows if r.get("brand")})

    ticker_html = _build_ticker(alerts)
    stat_cards_html = _build_stat_cards(rows, alerts, own_catalog_size, store_names)
    alert_cards_html = _build_alert_cards(alerts)
    table_rows_html = _build_table_rows(sorted(rows, key=lambda r: r["product_name"]), series)

    store_options = "".join(f'<option value="{_esc(s)}">{_esc(s)}</option>' for s in store_names)
    brand_options = "".join(f'<option value="{_esc(b)}">{_esc(b)}</option>' for b in brand_names)

    generated_at = datetime.utcnow().strftime("%d %b %Y, %H:%M UTC")

    page = TEMPLATE.format(
        run_date=_esc(run_date),
        generated_at=_esc(generated_at),
        ticker_html=ticker_html,
        stat_cards_html=stat_cards_html,
        alert_cards_html=alert_cards_html,
        table_rows_html=table_rows_html,
        store_options=store_options,
        brand_options=brand_options,
    )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"[Dashboard] Wrote {output_path}")
    return output_path


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GenesisPC · Price Watch</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #0F1218;
    --surface: #171B24;
    --surface-2: #1D2230;
    --border: #262B38;
    --text: #E7E9EE;
    --muted: #8791A6;
    --urgent: #FF5C5C;
    --warn: #F5A623;
    --good: #3ED9B0;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: 'Inter', system-ui, sans-serif;
    -webkit-font-smoothing: antialiased;
  }}
  h1, h2, .display {{ font-family: 'Space Grotesk', sans-serif; }}
  .mono {{ font-family: 'IBM Plex Mono', monospace; }}

  .wrap {{ max-width: 1180px; margin: 0 auto; padding: 0 24px 64px; }}

  header {{
    display: flex; align-items: baseline; justify-content: space-between;
    padding: 32px 0 20px; border-bottom: 1px solid var(--border);
    flex-wrap: wrap; gap: 8px;
  }}
  .eyebrow {{
    font-size: 12px; letter-spacing: 0.14em; text-transform: uppercase;
    color: var(--muted); margin-bottom: 4px;
  }}
  header h1 {{ font-size: 26px; font-weight: 700; margin: 0; letter-spacing: -0.01em; }}
  header .meta {{ color: var(--muted); font-size: 13px; font-family: 'IBM Plex Mono', monospace; }}

  /* Ticker */
  .ticker-outer {{
    background: var(--surface-2); border-bottom: 1px solid var(--border);
    overflow: hidden; white-space: nowrap; position: relative;
  }}
  .ticker-inner {{
    display: inline-block; padding: 10px 0;
    animation: scroll-left 38s linear infinite;
    font-family: 'IBM Plex Mono', monospace; font-size: 13px;
  }}
  .ticker-outer:hover .ticker-inner {{ animation-play-state: paused; }}
  @keyframes scroll-left {{
    0% {{ transform: translateX(0); }}
    100% {{ transform: translateX(-50%); }}
  }}
  .ticker-item {{ padding: 0 20px; color: var(--muted); }}
  .ticker-urgent {{ color: var(--urgent); font-weight: 600; }}
  .ticker-quiet {{ color: var(--muted); padding: 0 20px; }}
  @media (prefers-reduced-motion: reduce) {{
    .ticker-inner {{ animation: none; }}
  }}

  /* Stat cards */
  .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 24px 0; }}
  .stat-card {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
    padding: 18px; text-align: left;
  }}
  .stat-card.urgent {{ border-color: var(--urgent); }}
  .stat-card.warn {{ border-color: var(--warn); }}
  .stat-value {{ font-family: 'Space Grotesk', sans-serif; font-size: 30px; font-weight: 700; }}
  .stat-card.urgent .stat-value {{ color: var(--urgent); }}
  .stat-card.warn .stat-value {{ color: var(--warn); }}
  .stat-label {{ color: var(--muted); font-size: 12.5px; margin-top: 4px; }}

  section {{ margin-top: 36px; }}
  section h2 {{
    font-size: 13px; letter-spacing: 0.1em; text-transform: uppercase;
    color: var(--muted); margin-bottom: 14px; font-weight: 600;
  }}

  /* Alert cards */
  .alerts-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 10px; }}
  .alert-card {{
    display: block; background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 14px 16px; text-decoration: none; color: var(--text);
    transition: border-color 0.15s ease;
  }}
  .alert-card:hover {{ border-color: #3A4258; }}
  .alert-card.alert-urgent {{ border-color: var(--urgent); background: linear-gradient(180deg, #201417, var(--surface)); }}
  .alert-top {{ display: flex; justify-content: space-between; font-size: 12px; color: var(--muted); margin-bottom: 8px; }}
  .alert-product {{ font-weight: 600; color: var(--text); font-size: 13.5px; }}
  .alert-headline {{ font-size: 13.5px; margin-bottom: 4px; }}
  .alert-detail {{ font-size: 12.5px; color: var(--muted); font-family: 'IBM Plex Mono', monospace; }}
  .empty-state {{ color: var(--muted); font-size: 14px; }}

  .badge {{
    display: inline-block; font-size: 10.5px; font-weight: 700; letter-spacing: 0.04em;
    padding: 2px 7px; border-radius: 5px; text-transform: uppercase;
  }}
  .badge-urgent {{ background: var(--urgent); color: #1a0d0d; }}

  /* Filters */
  .filters {{ display: flex; gap: 8px; margin-bottom: 14px; flex-wrap: wrap; }}
  .filters input, .filters select {{
    background: var(--surface); border: 1px solid var(--border); color: var(--text);
    padding: 8px 12px; border-radius: 7px; font-size: 13px; font-family: 'Inter', sans-serif;
  }}
  .filters input {{ flex: 1; min-width: 180px; }}

  /* Table */
  table {{ width: 100%; border-collapse: collapse; font-size: 13.5px; }}
  thead th {{
    text-align: left; color: var(--muted); font-weight: 600; font-size: 11.5px;
    text-transform: uppercase; letter-spacing: 0.05em; padding: 10px 12px;
    border-bottom: 1px solid var(--border);
  }}
  tbody td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); vertical-align: middle; }}
  tbody tr.row-urgent {{ background: rgba(255, 92, 92, 0.06); }}
  tbody tr:hover {{ background: var(--surface); }}
  .cell-product a {{ color: var(--text); text-decoration: none; }}
  .cell-product a:hover {{ text-decoration: underline; }}
  .variant-tag {{ color: var(--muted); font-size: 11.5px; margin-left: 6px; }}
  .spark {{ display: block; }}

  footer {{ margin-top: 48px; color: var(--muted); font-size: 12px; text-align: center; }}
</style>
</head>
<body>
  <div class="ticker-outer"><div class="ticker-inner">{ticker_html}{ticker_html}</div></div>

  <div class="wrap">
    <header>
      <div>
        <div class="eyebrow">GenesisPC · Competitive Intel</div>
        <h1>Price Watch</h1>
      </div>
      <div class="meta">Last run {run_date} &nbsp;·&nbsp; generated {generated_at}</div>
    </header>

    <div class="stats">{stat_cards_html}</div>

    <section>
      <h2>Alerts today</h2>
      <div class="alerts-grid">{alert_cards_html}</div>
    </section>

    <section>
      <h2>Full catalog</h2>
      <div class="filters">
        <input type="text" id="search" placeholder="Search product, store, or brand…">
        <select id="storeFilter"><option value="">All stores</option>{store_options}</select>
        <select id="brandFilter"><option value="">All brands</option>{brand_options}</select>
      </div>
      <table id="catalogTable">
        <thead>
          <tr>
            <th>Product</th><th>Store</th><th>Price</th><th>Δ</th><th>Trend</th><th>Your price</th><th></th>
          </tr>
        </thead>
        <tbody>{table_rows_html}</tbody>
      </table>
    </section>

    <footer>GenesisPC Price Watch · rebuilt automatically after every scrape</footer>
  </div>

<script>
  const search = document.getElementById('search');
  const storeFilter = document.getElementById('storeFilter');
  const brandFilter = document.getElementById('brandFilter');
  const rows = Array.from(document.querySelectorAll('#catalogTable tbody tr'));

  function applyFilters() {{
    const q = search.value.trim().toLowerCase();
    const store = storeFilter.value;
    const brand = brandFilter.value;
    rows.forEach(row => {{
      const matchesSearch = !q || row.dataset.search.includes(q);
      const matchesStore = !store || row.dataset.store === store;
      const matchesBrand = !brand || row.dataset.brand === brand;
      row.style.display = (matchesSearch && matchesStore && matchesBrand) ? '' : 'none';
    }});
  }}
  [search, storeFilter, brandFilter].forEach(el => el.addEventListener('input', applyFilters));
</script>
</body>
</html>
"""
