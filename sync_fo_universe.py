"""
sync_fo_universe.py — Sync NSE F&O stock universe with config.py

Compares the live NSE F&O bhavcopy (downloaded fresh) against
the FO_STOCKS list in config.py and reports additions/removals.

Usage:
    python sync_fo_universe.py              # check only, print diff
    python sync_fo_universe.py --update     # auto-update config.py
    python sync_fo_universe.py --date 2026-03-04  # use specific date
"""

import io
import sys
import time
import zipfile
import argparse
import re
from datetime import date, timedelta

import requests

# ── Try importing config ──────────────────────────────────────────
try:
    from config import FO_STOCKS, NSE_FO_BHAVCOPY_URL, NSE_HEADERS, NSE_HOLIDAYS
except ImportError:
    print("ERROR: config.py not found. Run from project root.")
    sys.exit(1)

try:
    import pandas as pd
except ImportError:
    print("ERROR: pandas not installed. Run: pip install pandas")
    sys.exit(1)


# ── Helpers ───────────────────────────────────────────────────────

def last_trading_day(ref: date = None) -> date:
    if ref is None:
        ref = date.today()
    d = ref
    while True:
        if d.weekday() < 5 and d.isoformat() not in NSE_HOLIDAYS:
            return d
        d -= timedelta(days=1)


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(NSE_HEADERS)
    try:
        s.get("https://www.nseindia.com", timeout=15)
    except Exception:
        pass
    return s


def download_fo_bhavcopy(trade_date: date, session: requests.Session) -> bytes:
    from config import NSE_MONTH_ABBR
    mon = NSE_MONTH_ABBR[trade_date.month]
    url = NSE_FO_BHAVCOPY_URL.format(
        dd=trade_date.strftime("%d"),
        mm=trade_date.strftime("%m"),
        yyyy=trade_date.strftime("%Y"),
        MON=mon,
    )
    print(f"Downloading F&O bhavcopy: {url}")
    for attempt in range(1, 4):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 200 and len(r.content) > 500:
                return r.content
            print(f"  Attempt {attempt}: HTTP {r.status_code}")
        except Exception as e:
            print(f"  Attempt {attempt}: {e}")
        if attempt < 3:
            time.sleep(5)
    raise RuntimeError(f"Failed to download bhavcopy for {trade_date}")


def get_live_fo_stocks(trade_date: date) -> set:
    """Download live F&O bhavcopy and extract all STF (stock futures) symbols."""
    session = make_session()
    raw = download_fo_bhavcopy(trade_date, session)

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        csv_bytes = zf.read(csv_names[0])

    df = pd.read_csv(io.BytesIO(csv_bytes))
    df.columns = df.columns.str.strip().str.upper()

    # Find instrument type column
    inst_col = None
    for c in df.columns:
        if c in ("FININSTRMTP", "INSTRUMENT", "INSTTYPE"):
            inst_col = c
            break

    if inst_col is None:
        raise ValueError("Cannot find instrument type column in bhavcopy")

    # Filter stock futures
    stf = df[df[inst_col].astype(str).str.strip().str.upper().isin({"STF", "FUTSTK"})]

    # Find symbol column
    sym_col = None
    for c in df.columns:
        if c in ("TCKRSYMB", "SYMBOL", "SYMBOLNAME"):
            sym_col = c
            break

    if sym_col is None:
        raise ValueError("Cannot find symbol column in bhavcopy")

    symbols = set(stf[sym_col].astype(str).str.strip().str.upper().unique())
    print(f"Found {len(symbols)} stocks in live F&O bhavcopy")
    return symbols


def update_config(to_add: list, to_remove: list, config_path: str = "config.py"):
    """Auto-update FO_STOCKS in config.py."""
    with open(config_path, "r") as f:
        content = f.read()

    # Find current FO_STOCKS list
    current = set(FO_STOCKS)
    updated = sorted((current | set(to_add)) - set(to_remove))

    # Build new list string
    lines = []
    for i in range(0, len(updated), 6):
        chunk = updated[i:i+6]
        lines.append("    " + ", ".join(f'"{s}"' for s in chunk) + ",")
    new_list = "\n".join(lines)

    # Replace FO_STOCKS in config
    pattern = r'(FO_STOCKS\s*=\s*\[)[^\]]*(\])'
    replacement = f'FO_STOCKS = [\n{new_list}\n]'
    new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)

    if new_content == content:
        print("WARNING: Could not auto-update config.py — please update manually")
        return False

    with open(config_path, "w") as f:
        f.write(new_content)

    print(f"✅ config.py updated: +{len(to_add)} added, -{len(to_remove)} removed")
    return True


# ── Main ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Sync NSE F&O universe with config.py")
    parser.add_argument("--date", help="Trade date YYYY-MM-DD (default: last trading day)")
    parser.add_argument("--update", action="store_true", help="Auto-update config.py")
    args = parser.parse_args()

    # Resolve trade date
    if args.date:
        trade_date = date.fromisoformat(args.date)
    else:
        trade_date = last_trading_day()

    print(f"\n{'='*55}")
    print(f"NSE F&O UNIVERSE SYNC — {trade_date.strftime('%d %b %Y')}")
    print(f"{'='*55}")
    print(f"Current config.py universe: {len(FO_STOCKS)} stocks\n")

    # Get live universe
    try:
        live_stocks = get_live_fo_stocks(trade_date)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    config_stocks = set(FO_STOCKS)

    # Compare
    to_add    = sorted(live_stocks - config_stocks)
    to_remove = sorted(config_stocks - live_stocks)
    in_both   = config_stocks & live_stocks

    print(f"\n{'─'*55}")
    print(f"COMPARISON RESULTS:")
    print(f"  In both (matched):     {len(in_both)}")
    print(f"  In NSE, not config:    {len(to_add)}  ← ADD these")
    print(f"  In config, not NSE:    {len(to_remove)}  ← REMOVE these")
    print(f"{'─'*55}")

    if to_add:
        print(f"\n🟢 STOCKS TO ADD ({len(to_add)}):")
        for s in to_add:
            print(f"   + {s}")

    if to_remove:
        print(f"\n🔴 STOCKS TO REMOVE ({len(to_remove)}):")
        for s in to_remove:
            print(f"   - {s}")

    if not to_add and not to_remove:
        print("\n✅ config.py is fully in sync with NSE F&O universe!")
        return

    # Auto-update if requested
    if args.update:
        print(f"\nUpdating config.py...")
        update_config(to_add, to_remove)
    else:
        print(f"\nRun with --update to automatically update config.py")
        print(f"Example: python sync_fo_universe.py --update")


if __name__ == "__main__":
    main()
