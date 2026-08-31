"""
Exports already-enriched rows to Google Sheets. This is now a pure
write-only export target — change detection and undercut flagging
happen upstream in main.py against the local history.json file, so
this module never needs to read Sheets back (which sidesteps Sheets'
automatic type coercion of numbers/dates messing with parsing).

Sheets is optional: if SHEET_ID isn't set, main.py just skips this
and the dashboard + local history still work fully.
"""
import os
import gspread
from google.oauth2.service_account import Credentials

from change_detection import select_alerts

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

HEADER = [
    "date", "store", "brand", "product_name", "variant",
    "price", "compare_at_price", "currency", "in_stock", "url",
    "previous_price", "price_change", "change_flag",
    "own_price", "own_match", "match_confidence", "undercut_by", "action_needed",
]


def _authorize(creds_path):
    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return gspread.authorize(creds)


def _get_or_create_worksheet(sh, name):
    try:
        ws = sh.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=name, rows=2000, cols=len(HEADER))
        ws.append_row(HEADER, value_input_option="USER_ENTERED")
        return ws
    if ws.row_count == 0 or not ws.row_values(1):
        ws.append_row(HEADER, value_input_option="USER_ENTERED")
    return ws


def _row_to_values(r, run_date):
    return [
        run_date, r.get("store", ""), r.get("brand", ""), r.get("product_name", ""),
        r.get("variant", ""), r.get("price", ""), r.get("compare_at_price", ""),
        r.get("currency", "INR"), r.get("in_stock", ""), r.get("url", ""),
        r.get("previous_price", ""), r.get("price_change", ""), r.get("change_flag", ""),
        r.get("own_price", ""), r.get("own_match", ""), r.get("match_confidence", ""),
        r.get("undercut_by", ""), "YES" if r.get("action_needed") else "",
    ]


def _write_alerts_tab(sh, rows, run_date):
    ws = _get_or_create_worksheet(sh, "AlertsToday")
    ws.clear()
    ws.append_row(HEADER, value_input_option="USER_ENTERED")

    flagged = select_alerts(rows)
    if not flagged:
        return 0

    values = [_row_to_values(r, run_date) for r in flagged]
    ws.append_rows(values, value_input_option="USER_ENTERED")

    urgent_row_numbers = [i + 2 for i, r in enumerate(flagged) if r.get("action_needed")]
    for row_num in urgent_row_numbers:
        ws.format(f"A{row_num}:R{row_num}", {"backgroundColor": {"red": 0.96, "green": 0.80, "blue": 0.80}})
    return len(flagged)


def write_to_sheet(rows, run_date, sheet_id=None, creds_path=None):
    sheet_id = sheet_id or os.environ.get("SHEET_ID")
    creds_path = creds_path or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json")

    if not sheet_id:
        print("[!] No SHEET_ID set — skipping Google Sheets export (dashboard + CSV still work).")
        return

    client = _authorize(creds_path)
    sh = client.open_by_key(sheet_id)

    history_ws = _get_or_create_worksheet(sh, "PriceHistory")
    values = [_row_to_values(r, run_date) for r in rows]
    for i in range(0, len(values), 500):
        history_ws.append_rows(values[i:i + 500], value_input_option="USER_ENTERED")
    print(f"[Sheets] Appended {len(rows)} rows to PriceHistory")

    n_flagged = _write_alerts_tab(sh, rows, run_date)
    n_urgent = sum(1 for r in rows if r.get("action_needed"))
    print(f"[Sheets] AlertsToday: {n_flagged} rows flagged ({n_urgent} urgent undercuts)")
