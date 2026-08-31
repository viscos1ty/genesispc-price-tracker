# GenesisPC Competitor Price Tracker

Tracks prices for MCHOSE / ATK / Artisan / Endgame Gear / Wobkey / Xraypad /
Scyrox / GLSSWRKS / GameSir products across 4 competitor stores and renders
them as a live dashboard — hosted free on GitHub Pages, rebuilt automatically
every day via GitHub Actions. Google Sheets export is optional, off by default.

**Every run does three things automatically:**
1. **Flags price changes** — compares each product's price to the last
   time it was scraped and marks it `Increased` / `Decreased` / `New` /
   `Unchanged`, so you don't have to eyeball every line to spot a change.
2. **Flags undercuts** — pulls your own GenesisPC.in prices for the
   same products and marks anything a competitor now prices below you,
   red-highlighted, sorted to the top.
3. **Rebuilds the dashboard** (`docs/index.html`) — a ticker of today's
   changes, stat cards, an alerts section, and a filterable/searchable
   full catalog table with a price-trend sparkline per row.

The dashboard is the thing to check daily. Nothing needs opening a
spreadsheet unless you specifically want to.

**Stores tracked:**
| Store | Platform | Method |
|---|---|---|
| nmpc.in | Shopify | public `/products.json` API |
| ryugear.in | Shopify | public `/products.json` API |
| neomacro.in | Shopify | public `/products.json` API |
| meckeys.com | WooCommerce | HTML parsing of category pages |

The Shopify stores are scraped via their built-in JSON catalog feed —
this is stable and won't break from theme changes. Meckeys has no public
API, so it's scraped from rendered HTML; if Meckeys changes its theme,
`scrapers/woocommerce_scraper.py` may need its CSS selectors updated
(the row count printed in the logs will drop to 0 or look wrong — that's
your signal to check it).

---

## 1. Run it locally (test first)

```bash
cd price-scraper
pip install -r requirements.txt
python main.py --no-sheet
```

This scrapes everything, writes `data/history.json` (the running price
record) and `docs/index.html` (the dashboard), plus a CSV backup in
`output/`. Open `docs/index.html` directly in your browser to check it
before pushing anything live.

## 2. Put it on GitHub and turn on Pages hosting (~5 minutes)

1. Create a free account at github.com if you don't have one.
2. Create a **new repository** — it can be Private or Public, doesn't
   matter for Pages. Push this whole folder to it (or use GitHub's
   "uploading an existing file" option to drag the folder contents in).
3. In the repo: **Settings → Pages** → under "Build and deployment",
   set **Source** to "Deploy from a branch", **Branch** to `main`
   (or `master`) and folder to **`/docs`** → Save.
4. GitHub will give you a URL like
   `https://yourusername.github.io/your-repo-name/` — that's your
   dashboard, live on the internet, bookmark it. It'll show whatever
   was last committed to `docs/index.html`.
5. That's it for hosting — nothing else to configure. The daily
   GitHub Action (see next section) is what keeps `docs/index.html`
   updated automatically.

## 3. Automate the daily scrape (free, via GitHub Actions)

The workflow file `.github/workflows/daily-scrape.yml` is already set
up to run every day at 8:30 AM IST, scrape everything, rebuild the
dashboard, and commit the result back to the repo (which is what makes
step 2's Pages URL update automatically). You don't need to do
anything for this to work — just having pushed the repo is enough.

You can also trigger it manually anytime: go to the **Actions** tab in
your repo → "Daily competitor price scrape" → **Run workflow**.

## 4. (Optional) Also export to Google Sheets

If you'd like a raw spreadsheet copy of the data alongside the
dashboard — e.g. for pivot tables or sharing with someone who prefers
Sheets — you can turn this on, but it's entirely optional; skip this
section if the dashboard is all you need.

1. **Create a Google Cloud project**: https://console.cloud.google.com/projectcreate
2. **Enable the Sheets API**: https://console.cloud.google.com/apis/library/sheets.googleapis.com → "Enable"
3. **Create a service account**: https://console.cloud.google.com/iam-admin/serviceaccounts
   → "Create Service Account" → any name (e.g. `price-tracker`) → skip
   the optional steps → "Done"
4. **Create a JSON key**: click into the service account → "Keys" tab
   → "Add Key" → "Create new key" → JSON. Save the downloaded file as
   `service_account.json` in this folder (already in `.gitignore`).
5. **Create a Google Sheet**, copy its ID from the URL:
   `https://docs.google.com/spreadsheets/d/THIS_PART_IS_THE_ID/edit`
6. **Share the Sheet** with the service account's email (inside the
   JSON key file, looks like `price-tracker@your-project.iam.gserviceaccount.com`)
   — Editor access.
7. In your GitHub repo: **Settings → Secrets and variables → Actions →
   New repository secret**, add:
   - `SHEET_ID` — the Sheet ID from step 5
   - `GOOGLE_SERVICE_ACCOUNT_JSON` — the entire contents of `service_account.json`
8. Next scheduled or manually-triggered run will start writing to a
   `PriceHistory` tab and an `AlertsToday` tab in that Sheet.

## 5. Editing what gets tracked

- Add/remove stores in `config.json`. For a new Shopify competitor,
  just add `{"name": ..., "url": ..., "platform": "shopify"}` — no
  other setup needed. For a new WooCommerce store, you'll need to find
  its category page URLs.
- Add/remove brand keywords in `config.json`'s `brand_keywords` list to
  control which products get tracked. Set it to `[]` (empty) to track
  every product on every store instead of filtering.

## How undercut matching works (and its limits)

Competitor product names never match your own catalog word-for-word
("MCHOSE G3 V2 Wireless Gaming Mouse" vs "MCHOSE G3 V2"), so
`matching.py` uses a fuzzy name match (token overlap + string
similarity) to find your closest equivalent product, and only flags an
undercut when it's at least 55% confident in the match. Every matched
row records `own_match` (which of your products it matched) and
`match_confidence`, so you can sanity-check any flag before acting on
it. If a competitor product doesn't clear that confidence bar, it's
left unmatched rather than risking a false undercut alert — so a real
undercut can occasionally be missed if product names differ too much
(e.g. a competitor calls a mouse by its Chinese-market name), but you
won't get flagged into chasing phantom price wars. If you notice a
real match getting missed, tightening the name overlap (e.g. asking me
to add a manual alias map for tricky products) is a quick follow-up.

## Notes on reliability

- Amazon India and Flipkart are **not** included here. Both actively
  block/rate-limit automated requests and their Terms of Service
  restrict scraping — this makes marketplace scraping fragile (frequent
  IP blocks) even when technically done at low volume for personal
  competitive tracking. If you want marketplace prices tracked too, the
  more sustainable route is checking specific listings manually on a
  schedule, or using a paid marketplace-monitoring API — happy to help
  set either up if useful.
- The scraper identifies itself with a descriptive User-Agent rather
  than pretending to be a browser, and waits between requests — this
  is polite-scraper behavior, not stealth scraping.
