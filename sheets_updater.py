"""
sheets_updater.py — Push screener results to Google Sheets.
Reads the JSON output from screener.py and updates 5 tabs:
  MORNING BRIEF | TOP LONGS | TOP SHORTS | OI ALERTS | FULL UNIVERSE
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import date, datetime

import pandas as pd

# Google Sheets dependencies
try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False
    print("WARNING: gspread not installed. Run: pip install gspread google-auth")

from config import (
    GOOGLE_CREDENTIALS_PATH, GOOGLE_SHEET_ID, SHEET_TABS, LOGS_DIR,
)

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
Path(LOGS_DIR).mkdir(exist_ok=True)
log_file = Path(LOGS_DIR) / f"sheets_{date.today().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Google Sheets API scopes
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Color constants (RGB 0-1 scale for Sheets API)
COLOR_GREEN_STRONG = {"red": 0.18, "green": 0.55, "blue": 0.18}
COLOR_GREEN_MID    = {"red": 0.56, "green": 0.93, "blue": 0.56}
COLOR_RED_STRONG   = {"red": 0.80, "green": 0.10, "blue": 0.10}
COLOR_RED_MID      = {"red": 1.00, "green": 0.60, "blue": 0.60}
COLOR_YELLOW       = {"red": 1.00, "green": 0.95, "blue": 0.60}
COLOR_GREY_HEADER  = {"red": 0.20, "green": 0.20, "blue": 0.20}
COLOR_WHITE        = {"red": 1.00, "green": 1.00, "blue": 1.00}


# ─────────────────────────────────────────────
# GOOGLE SHEETS CONNECTION
# ─────────────────────────────────────────────

def get_google_client():
    """Authenticate and return a gspread client."""
    if not GSPREAD_AVAILABLE:
        raise ImportError("gspread not installed")

    # Support credentials from env var (GitHub Actions) or file
    creds_json_str = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json_str:
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            tmp.write(creds_json_str)
            creds_path = tmp.name
    else:
        creds_path = GOOGLE_CREDENTIALS_PATH

    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client


def get_or_create_sheet(client, spreadsheet_id: str, tab_name: str):
    """Get a worksheet by name, create it if it doesn't exist."""
    sh = client.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        logger.info(f"  Creating tab: {tab_name}")
        ws = sh.add_worksheet(title=tab_name, rows=300, cols=30)
    return ws


def clear_and_write(ws, data: list, header_row: list = None):
    """Clear worksheet and write data. data is list of lists."""
    ws.clear()
    if header_row:
        all_data = [header_row] + data
    else:
        all_data = data
    if all_data:
        ws.update("A1", all_data, value_input_option="USER_ENTERED")


def fmt_val(val, decimals=2):
    """Format a value safely."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    if isinstance(val, float):
        return round(val, decimals)
    return val


def score_to_bar(score, max_score=18):
    """Convert composite score to a visual bar string."""
    normalized = int((score + max_score) / (2 * max_score) * 10)
    filled = "█" * normalized
    empty  = "░" * (10 - normalized)
    return f"{filled}{empty} {score:+d}"


# ─────────────────────────────────────────────
# TAB WRITERS
# ─────────────────────────────────────────────

def write_morning_brief(ws, results: dict):
    """Write MORNING BRIEF tab."""
    macro = results.get("macro", {})
    top_longs  = results.get("top_longs", [])[:5]
    top_shorts = results.get("top_shorts", [])[:5]
    oi_alerts  = results.get("oi_alerts", [])
    trade_date = results.get("trade_date", "")

    now = datetime.now().strftime("%H:%M IST")
    bias = macro.get("market_bias", "NEUTRAL")
    fii_net = macro.get("fii_index_fut_net", 0)
    fii_dir = "Net LONG" if fii_net >= 0 else "Net SHORT"
    fii_display = f"{fii_dir} ({abs(fii_net):,.0f} contracts)"

    rows = [
        ["📊 F&O MORNING BRIEF", "", "", "", "", ""],
        [f"Date: {trade_date}", f"Session: Pre-market | {now}", "", "", "", ""],
        ["", "", "", "", "", ""],
        ["🌐 MACRO CONTEXT", "", "", "", "", ""],
        ["Market Bias:", bias, "", "FII Index Futures:", fii_display, ""],
        ["FII Total Net:", f"{macro.get('fii_total_net', 0):,.0f}", "", "", "", ""],
        ["", "", "", "", "", ""],
        ["🟢 TOP 5 LONG CANDIDATES", "", "", "", "", ""],
        ["Rank", "Stock", "Score", "Signal", "OI Change %", "Delivery %"],
    ]
    for i, s in enumerate(top_longs, 1):
        rows.append([
            i,
            s.get("SYMBOL", ""),
            f"{s.get('COMPOSITE_SCORE', 0)}/18",
            s.get("OI_SIGNAL", ""),
            fmt_val(s.get("OI_CHANGE_PCT"), 1),
            fmt_val(s.get("DELIVERY_PCT"), 1),
        ])

    rows += [
        ["", "", "", "", "", ""],
        ["🔴 TOP 5 SHORT CANDIDATES", "", "", "", "", ""],
        ["Rank", "Stock", "Score", "Signal", "OI Change %", "Delivery %"],
    ]
    for i, s in enumerate(top_shorts, 1):
        rows.append([
            i,
            s.get("SYMBOL", ""),
            f"{s.get('COMPOSITE_SCORE', 0)}/18",
            s.get("OI_SIGNAL", ""),
            fmt_val(s.get("OI_CHANGE_PCT"), 1),
            fmt_val(s.get("DELIVERY_PCT"), 1),
        ])

    rows += [
        ["", "", "", "", "", ""],
        [f"⚠️ OI ALERTS ({len(oi_alerts)} stocks)", "", "", "", "", ""],
    ]
    for s in oi_alerts[:10]:
        rows.append([
            s.get("SYMBOL", ""),
            f"OI {fmt_val(s.get('OI_CHANGE_PCT'), 1)}%",
            f"Price {fmt_val(s.get('PRICE_CHANGE_PCT'), 1)}%",
            s.get("OI_SIGNAL", ""),
            s.get("ALERT_SEVERITY", ""),
            "",
        ])

    clear_and_write(ws, rows)
    logger.info(f"  MORNING BRIEF tab updated ({len(rows)} rows)")


def write_top_longs(ws, results: dict):
    """Write TOP LONGS tab."""
    stocks = results.get("top_longs", [])
    header = [
        "Rank", "Stock", "Composite Score", "Technical Score", "F&O Score",
        "Signal Type", "OI Change %", "Price Change %", "Delivery %",
        "ADX", "RSI", "Supertrend", "MACD Direction", "EMA Alignment", "Volume Ratio",
    ]
    data = []
    for i, s in enumerate(stocks, 1):
        data.append([
            i,
            s.get("SYMBOL", ""),
            fmt_val(s.get("COMPOSITE_SCORE"), 0),
            fmt_val(s.get("TECHNICAL_SCORE"), 0),
            fmt_val(s.get("FO_SCORE"), 0),
            s.get("OI_SIGNAL", ""),
            fmt_val(s.get("OI_CHANGE_PCT"), 1),
            fmt_val(s.get("PRICE_CHANGE_PCT"), 2),
            fmt_val(s.get("DELIVERY_PCT"), 1),
            fmt_val(s.get("ADX"), 1),
            fmt_val(s.get("RSI"), 1),
            s.get("SUPERTREND_SIGNAL", ""),
            s.get("MACD_SIGNAL", ""),
            s.get("EMA_SIGNAL", ""),
            fmt_val(s.get("VOLUME_RATIO"), 2),
        ])
    clear_and_write(ws, data, header_row=header)
    logger.info(f"  TOP LONGS tab updated ({len(data)} rows)")


def write_top_shorts(ws, results: dict):
    """Write TOP SHORTS tab."""
    stocks = results.get("top_shorts", [])
    header = [
        "Rank", "Stock", "Composite Score", "Technical Score", "F&O Score",
        "Signal Type", "OI Change %", "Price Change %", "Delivery %",
        "ADX", "RSI", "Supertrend", "MACD Direction", "EMA Alignment", "Volume Ratio",
    ]
    data = []
    for i, s in enumerate(stocks, 1):
        data.append([
            i,
            s.get("SYMBOL", ""),
            fmt_val(s.get("COMPOSITE_SCORE"), 0),
            fmt_val(s.get("TECHNICAL_SCORE"), 0),
            fmt_val(s.get("FO_SCORE"), 0),
            s.get("OI_SIGNAL", ""),
            fmt_val(s.get("OI_CHANGE_PCT"), 1),
            fmt_val(s.get("PRICE_CHANGE_PCT"), 2),
            fmt_val(s.get("DELIVERY_PCT"), 1),
            fmt_val(s.get("ADX"), 1),
            fmt_val(s.get("RSI"), 1),
            s.get("SUPERTREND_SIGNAL", ""),
            s.get("MACD_SIGNAL", ""),
            s.get("EMA_SIGNAL", ""),
            fmt_val(s.get("VOLUME_RATIO"), 2),
        ])
    clear_and_write(ws, data, header_row=header)
    logger.info(f"  TOP SHORTS tab updated ({len(data)} rows)")


def write_oi_alerts(ws, results: dict):
    """Write OI ALERTS tab."""
    alerts = results.get("oi_alerts", [])
    header = [
        "Stock", "OI Change %", "Price Change %", "Classification",
        "Composite Score", "Alert Severity",
    ]
    data = []
    for s in sorted(alerts, key=lambda x: abs(x.get("OI_CHANGE_PCT") or 0), reverse=True):
        data.append([
            s.get("SYMBOL", ""),
            fmt_val(s.get("OI_CHANGE_PCT"), 1),
            fmt_val(s.get("PRICE_CHANGE_PCT"), 2),
            s.get("OI_SIGNAL", ""),
            fmt_val(s.get("COMPOSITE_SCORE"), 0),
            s.get("ALERT_SEVERITY", "MEDIUM"),
        ])
    clear_and_write(ws, data, header_row=header)
    logger.info(f"  OI ALERTS tab updated ({len(data)} rows)")


def write_full_universe(ws, results: dict):
    """Write FULL UNIVERSE tab with all ~180 stocks."""
    stocks = results.get("full_universe", [])
    header = [
        "Rank", "Stock", "Composite Score", "Technical Score", "F&O Score",
        "Signal", "OI Signal", "OI Change %", "Price Change %", "Delivery %",
        "RSI", "ADX", "EMA Alignment", "MACD", "Supertrend", "Volume Ratio", "Price",
    ]
    data = []
    for s in stocks:
        data.append([
            fmt_val(s.get("RANK"), 0),
            s.get("SYMBOL", ""),
            fmt_val(s.get("COMPOSITE_SCORE"), 0),
            fmt_val(s.get("TECHNICAL_SCORE"), 0),
            fmt_val(s.get("FO_SCORE"), 0),
            s.get("SIGNAL", ""),
            s.get("OI_SIGNAL", ""),
            fmt_val(s.get("OI_CHANGE_PCT"), 1),
            fmt_val(s.get("PRICE_CHANGE_PCT"), 2),
            fmt_val(s.get("DELIVERY_PCT"), 1),
            fmt_val(s.get("RSI"), 1),
            fmt_val(s.get("ADX"), 1),
            s.get("EMA_SIGNAL", ""),
            s.get("MACD_SIGNAL", ""),
            s.get("SUPERTREND_SIGNAL", ""),
            fmt_val(s.get("VOLUME_RATIO"), 2),
            fmt_val(s.get("PRICE"), 2),
        ])
    clear_and_write(ws, data, header_row=header)
    logger.info(f"  FULL UNIVERSE tab updated ({len(data)} rows)")


def apply_color_formatting(client, spreadsheet_id: str, results: dict):
    """Apply color coding to FULL UNIVERSE tab."""
    try:
        sh = client.open_by_key(spreadsheet_id)
        ws = sh.worksheet(SHEET_TABS["full_universe"])
        stocks = results.get("full_universe", [])

        requests_list = []
        ws_id = ws._properties["sheetId"]

        for i, s in enumerate(stocks):
            row_idx = i + 1  # 0-indexed, skip header row 0
            score = s.get("COMPOSITE_SCORE", 0) or 0

            if score >= 14:
                bg = COLOR_GREEN_STRONG
                fg = COLOR_WHITE
            elif score >= 8:
                bg = COLOR_GREEN_MID
                fg = {"red": 0, "green": 0, "blue": 0}
            elif score <= -14:
                bg = COLOR_RED_STRONG
                fg = COLOR_WHITE
            elif score <= -8:
                bg = COLOR_RED_MID
                fg = {"red": 0, "green": 0, "blue": 0}
            else:
                continue  # no coloring for neutral

            requests_list.append({
                "repeatCell": {
                    "range": {
                        "sheetId": ws_id,
                        "startRowIndex": row_idx,
                        "endRowIndex": row_idx + 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": 17,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": bg,
                            "textFormat": {"foregroundColor": fg},
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat)",
                }
            })

        if requests_list:
            sh.batch_update({"requests": requests_list})
            logger.info(f"  Color formatting applied to {len(requests_list)} rows")
    except Exception as e:
        logger.warning(f"  Color formatting failed (non-critical): {e}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def update_sheets(results: dict = None, json_path: str = None):
    """Main function: load results and update all Google Sheet tabs."""
    if results is None:
        # Load from JSON file
        if json_path is None:
            today = date.today().strftime("%Y%m%d")
            json_path = f"logs/screener_results_{today}.json"
        logger.info(f"Loading results from: {json_path}")
        with open(json_path) as f:
            results = json.load(f)

    if not GSPREAD_AVAILABLE:
        logger.error("gspread not available. Install with: pip install gspread google-auth")
        return False

    if GOOGLE_SHEET_ID == "YOUR_GOOGLE_SHEET_ID_HERE":
        logger.error("GOOGLE_SHEET_ID not configured in config.py or environment variable")
        return False

    logger.info("Connecting to Google Sheets...")
    try:
        client = get_google_client()
    except Exception as e:
        logger.error(f"Google auth failed: {e}")
        raise

    logger.info(f"Updating spreadsheet: {GOOGLE_SHEET_ID}")

    # Write each tab
    tab_writers = {
        "morning_brief": write_morning_brief,
        "top_longs":     write_top_longs,
        "top_shorts":    write_top_shorts,
        "oi_alerts":     write_oi_alerts,
        "full_universe": write_full_universe,
    }

    for tab_key, writer_fn in tab_writers.items():
        tab_name = SHEET_TABS[tab_key]
        try:
            ws = get_or_create_sheet(client, GOOGLE_SHEET_ID, tab_name)
            writer_fn(ws, results)
        except Exception as e:
            logger.error(f"Failed to write {tab_name}: {e}")
            raise

    # Apply color formatting
    apply_color_formatting(client, GOOGLE_SHEET_ID, results)

    sheet_url = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}"
    logger.info(f"Google Sheets updated successfully: {sheet_url}")
    return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Update Google Sheets with screener results")
    parser.add_argument("--json", help="Path to screener results JSON file")
    args = parser.parse_args()

    try:
        success = update_sheets(json_path=args.json)
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"Sheets update failed: {e}", exc_info=True)
        sys.exit(1)
