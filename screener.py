"""
screener.py — F&O Morning Screener for NSE Indian Markets
Downloads NSE bhavcopy data, calculates technical + F&O scores,
and produces ranked output for the full ~180 stock F&O universe.
"""

import os
import sys
import io
import time
import logging
import zipfile
import json
from datetime import date, timedelta, datetime
from pathlib import Path

import requests
import pandas as pd
import numpy as np

try:
    import yfinance as yf
except ImportError:
    yf = None

try:
    import pandas_ta as ta
except ImportError:
    ta = None

from sector_map import SECTOR_MAP
from config import (
    FO_STOCKS, NSE_MONTH_ABBR, NSE_HOLIDAYS,
    NSE_FO_BHAVCOPY_URL, NSE_CM_BHAVCOPY_URL, NSE_PARTICIPANT_OI_URL,
    NSE_HEADERS, MAX_RETRIES, RETRY_DELAY_SECONDS, REQUEST_TIMEOUT,
    EMA_SHORT, EMA_MID, EMA_LONG, RSI_PERIOD, ADX_PERIOD,
    SUPERTREND_PERIOD, SUPERTREND_MULTIPLIER,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL, VOLUME_MA_PERIOD,
    RSI_BULL_LOW, RSI_BULL_HIGH, RSI_BEAR_LOW, RSI_BEAR_HIGH,
    ADX_TREND_THRESHOLD, VOLUME_HIGH_RATIO, VOLUME_LOW_RATIO,
    OI_CHANGE_MEDIUM, OI_CHANGE_HIGH, OI_CHANGE_EXTREME, OI_ALERT_THRESHOLD,
    PCR_VERY_BULLISH, PCR_BULLISH, PCR_BEARISH, PCR_VERY_BEARISH,
    RS_PERIOD, RS_STRONG_BULL, RS_MILD_BULL, RS_MILD_BEAR, RS_STRONG_BEAR,
    DELIVERY_HIGH, DELIVERY_LOW,
    STRONG_LONG_THRESHOLD, LONG_THRESHOLD, SHORT_THRESHOLD, STRONG_SHORT_THRESHOLD,
    YFINANCE_PERIOD, YFINANCE_INTERVAL, YFINANCE_SUFFIX,
    YFINANCE_BATCH_SIZE, YFINANCE_BATCH_DELAY,
    LOGS_DIR, OUTPUT_CSV,
    BB_PERIOD, BB_STD_DEV, BB_SQUEEZE_THRESHOLD,
    BREAKOUT_LOOKBACK, BREAKOUT_NEAR_PCT, BREAKOUT_CONFIRM_VOL,
)

# ─────────────────────────────────────────────
# LOGGING SETUP
# ─────────────────────────────────────────────
Path(LOGS_DIR).mkdir(exist_ok=True)
log_file = Path(LOGS_DIR) / f"screener_{date.today().strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# DATE UTILITIES
# ─────────────────────────────────────────────

def last_trading_day(ref_date: date = None) -> date:
    """Return the most recent NSE trading day (skip weekends + holidays)."""
    if ref_date is None:
        ref_date = date.today()
    d = ref_date
    # If called in the morning before market open, look back one day
    while True:
        if d.weekday() < 5 and d.isoformat() not in NSE_HOLIDAYS:
            return d
        d -= timedelta(days=1)


def prev_trading_day(ref_date: date) -> date:
    """Return the trading day before ref_date."""
    d = ref_date - timedelta(days=1)
    while d.weekday() >= 5 or d.isoformat() in NSE_HOLIDAYS:
        d -= timedelta(days=1)
    return d


def format_nse_url(template: str, d: date) -> str:
    """Format an NSE URL template with date components."""
    mon = NSE_MONTH_ABBR[d.month]
    return template.format(
        dd=d.strftime("%d"),
        mm=d.strftime("%m"),
        yyyy=d.strftime("%Y"),
        MON=mon,
    )


# ─────────────────────────────────────────────
# HTTP DOWNLOAD HELPERS
# ─────────────────────────────────────────────

def make_session() -> requests.Session:
    """Create a requests session with NSE-friendly headers."""
    s = requests.Session()
    s.headers.update(NSE_HEADERS)
    # Prime cookies by visiting NSE homepage
    try:
        s.get("https://www.nseindia.com", timeout=REQUEST_TIMEOUT)
    except Exception:
        pass
    return s


def download_with_retry(url: str, session: requests.Session, is_zip: bool = False):
    """Download a URL with retries. Returns raw bytes or raises."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(f"  Attempt {attempt}/{MAX_RETRIES}: {url}")
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200 and len(resp.content) > 500:
                return resp.content
            logger.warning(f"  Bad response: HTTP {resp.status_code}, size={len(resp.content)}")
        except Exception as e:
            logger.warning(f"  Download error: {e}")
        if attempt < MAX_RETRIES:
            logger.info(f"  Waiting {RETRY_DELAY_SECONDS}s before retry...")
            time.sleep(RETRY_DELAY_SECONDS)
    raise RuntimeError(f"Failed to download after {MAX_RETRIES} attempts: {url}")


def unzip_csv(raw_bytes: bytes, search_pattern: str = None) -> bytes:
    """Extract CSV content from a zip file."""
    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
        names = zf.namelist()
        if search_pattern:
            names = [n for n in names if search_pattern.lower() in n.lower()] or names
        csv_names = [n for n in names if n.lower().endswith(".csv")]
        target = csv_names[0] if csv_names else names[0]
        return zf.read(target)


# ─────────────────────────────────────────────
# NSE DATA DOWNLOAD
# ─────────────────────────────────────────────

def download_fo_bhavcopy(trade_date: date, session: requests.Session) -> pd.DataFrame:
    """Download and parse F&O bhavcopy CSV."""
    url = format_nse_url(NSE_FO_BHAVCOPY_URL, trade_date)
    logger.info(f"Downloading F&O Bhavcopy: {url}")
    raw = download_with_retry(url, session, is_zip=True)
    csv_bytes = unzip_csv(raw, "bhav")
    df = pd.read_csv(io.BytesIO(csv_bytes))
    df.columns = df.columns.str.strip().str.upper()
    logger.info(f"  F&O Bhavcopy rows: {len(df)}")
    return df


def download_cm_bhavcopy(trade_date: date, session: requests.Session) -> pd.DataFrame:
    """Download and parse CM (equity) bhavcopy CSV."""
    url = format_nse_url(NSE_CM_BHAVCOPY_URL, trade_date)
    logger.info(f"Downloading CM Bhavcopy: {url}")
    raw = download_with_retry(url, session, is_zip=True)
    csv_bytes = unzip_csv(raw)
    df = pd.read_csv(io.BytesIO(csv_bytes))
    df.columns = df.columns.str.strip().str.upper()
    logger.info(f"  CM Bhavcopy rows: {len(df)}")
    return df


def download_participant_oi(trade_date: date, session: requests.Session) -> pd.DataFrame:
    """Download and parse Participant-wise OI CSV."""
    url = format_nse_url(NSE_PARTICIPANT_OI_URL, trade_date)
    logger.info(f"Downloading Participant OI: {url}")
    raw = download_with_retry(url, session)
    df = pd.read_csv(io.BytesIO(raw))
    df.columns = df.columns.str.strip().str.upper()
    logger.info(f"  Participant OI rows: {len(df)}")
    return df


# ─────────────────────────────────────────────
# PARSE NSE DATA
# ─────────────────────────────────────────────

def parse_options_pcr(df: pd.DataFrame, trade_date: date) -> pd.DataFrame:
    """
    Extract per-stock PCR (Put-Call Ratio) from the F&O bhavcopy STO rows.
    Uses the same raw bhavcopy df — no additional download needed.
    Returns DataFrame: SYMBOL, CE_OI, PE_OI, PCR
    """
    if df is None or df.empty:
        return pd.DataFrame()

    # Find instrument type column
    inst_col = None
    for c in df.columns:
        if c.upper().strip() in ("FININSTRMTP", "INSTRUMENT", "INSTTYPE"):
            inst_col = c
            break
    if inst_col is None:
        return pd.DataFrame()

    inst_series = df[inst_col].astype(str).str.strip().str.upper()
    opts = df[inst_series.isin({"STO", "OPTSTK"})].copy().reset_index(drop=True)
    if opts.empty:
        logger.warning("No stock options (STO) rows found for PCR calculation")
        return pd.DataFrame()

    logger.info(f"Stock options rows for PCR: {len(opts)}")

    def find_col(candidates):
        for name in candidates:
            if name in opts.columns:
                return name
        return None

    sym_col    = find_col(["TCKRSYMB", "SYMBOL", "SYMBOLNAME"])
    oi_col     = find_col(["OPNINTRST", "OPEN_INT", "OPENINT", "OI"])
    opt_type   = find_col(["OPTNTP", "OPTION_TYPE", "OPTTYPE", "OPTYPE"])
    expiry_col = find_col(["XPRYDT", "EXPIRY_DT", "EXPDATE"])

    if not sym_col or not oi_col or not opt_type:
        logger.warning("Missing critical columns for PCR calculation")
        return pd.DataFrame()

    opts2 = opts[[sym_col, opt_type, oi_col]].copy()
    opts2.columns = ["SYMBOL", "OPT_TYPE", "OI"]
    opts2["OI"] = pd.to_numeric(opts2["OI"], errors="coerce").fillna(0)
    opts2["OPT_TYPE"] = opts2["OPT_TYPE"].astype(str).str.strip().str.upper()

    # Filter to nearest expiry if expiry column available
    if expiry_col:
        opts["_EXPIRY"] = pd.to_datetime(opts[expiry_col], errors="coerce")
        cm = pd.Timestamp(trade_date).replace(day=1)
        nm = cm + pd.DateOffset(months=1)
        mask = (opts["_EXPIRY"] >= cm) & (opts["_EXPIRY"] < nm)
        if mask.sum() > 0:
            opts2 = opts2[mask.values]
        else:
            nearest = opts["_EXPIRY"].dropna().min()
            opts2 = opts2[opts["_EXPIRY"].values == nearest]

    # Aggregate CE and PE OI per symbol
    ce = opts2[opts2["OPT_TYPE"] == "CE"].groupby("SYMBOL")["OI"].sum().rename("CE_OI")
    pe = opts2[opts2["OPT_TYPE"] == "PE"].groupby("SYMBOL")["OI"].sum().rename("PE_OI")

    pcr_df = pd.concat([ce, pe], axis=1).fillna(0).reset_index()
    pcr_df["PCR"] = np.where(
        pcr_df["CE_OI"] > 0,
        pcr_df["PE_OI"] / pcr_df["CE_OI"],
        np.nan
    )
    pcr_df = pcr_df[pcr_df["PCR"].notna()].copy()
    logger.info(f"PCR computed for {len(pcr_df)} stocks")
    return pcr_df


def parse_fo_bhavcopy(df: pd.DataFrame, trade_date: date) -> pd.DataFrame:
    """
    Extract stock futures from F&O bhavcopy.
    UDiFF format (post July 2024): STF=Stock Futures.
    Uses find_col to pick ONE column per field — avoids duplicate column name errors.
    """
    logger.info(f"F&O Bhavcopy columns: {list(df.columns)}")

    # Find instrument type column
    inst_col = None
    for c in df.columns:
        if c.upper().strip() in ("FININSTRMTP", "INSTRUMENT", "INSTTYPE"):
            inst_col = c
            break
    if inst_col is None:
        logger.warning("No instrument type column found!")
        return pd.DataFrame()

    inst_series = df[inst_col].astype(str).str.strip().str.upper()
    logger.info(f"Unique instrument types: {inst_series.unique()}")
    fut = df[inst_series.isin({"STF", "FUTSTK"})].copy().reset_index(drop=True)
    if fut.empty:
        logger.warning("No stock futures rows found!")
        return pd.DataFrame()
    logger.info(f"Stock futures rows: {len(fut)}")

    # Pick ONE column per field by priority — no duplicate column names
    def find_col(candidates):
        for name in candidates:
            if name in fut.columns:
                return name
        return None

    sym_col    = find_col(["TCKRSYMB", "SYMBOL", "SYMBOLNAME"])
    expiry_col = find_col(["XPRYDT", "EXPIRY_DT", "EXPDATE"])
    close_col  = find_col(["STTLMPRIC", "CLSPRIC", "LASTPRIC", "CLOSE", "SETTLE_PR"])
    prev_col   = find_col(["PRVSCLSGPRIC", "PREVCLOSE", "PREV_CLOSE"])
    oi_col     = find_col(["OPNINTRST", "OPEN_INT", "OPENINT", "OI"])
    oi_chg_col = find_col(["CHNGINOPNINTRST", "CHG_IN_OI", "CHNG_IN_OI"])

    if not sym_col or not close_col or not oi_col:
        logger.warning(f"Missing critical columns. sym={sym_col}, close={close_col}, oi={oi_col}")
        return pd.DataFrame()

    cols = {sym_col: "SYMBOL", close_col: "CLOSE", oi_col: "OI"}
    if expiry_col: cols[expiry_col] = "EXPIRY_DT"
    if prev_col:   cols[prev_col]   = "PREV_CLOSE"
    if oi_chg_col: cols[oi_chg_col] = "OI_CHANGE_ABS"

    fut2 = fut[list(cols.keys())].copy().rename(columns=cols)

    for num_col in ("CLOSE", "OI", "OI_CHANGE_ABS", "PREV_CLOSE"):
        if num_col in fut2.columns:
            fut2[num_col] = pd.to_numeric(fut2[num_col], errors="coerce")

    if "EXPIRY_DT" in fut2.columns:
        fut2["EXPIRY_DT"] = pd.to_datetime(fut2["EXPIRY_DT"], errors="coerce")
        cm = pd.Timestamp(trade_date).replace(day=1)
        nm = cm + pd.DateOffset(months=1)
        cc = fut2[(fut2["EXPIRY_DT"] >= cm) & (fut2["EXPIRY_DT"] < nm)].copy()
        if cc.empty:
            nearest = fut2["EXPIRY_DT"].dropna().min()
            cc = fut2[fut2["EXPIRY_DT"] == nearest].copy()
            logger.info(f"Fallback to nearest expiry: {nearest}")
    else:
        cc = fut2.copy()

    if cc.empty:
        logger.warning("No contracts after expiry filter!")
        return pd.DataFrame()

    agg = cc.groupby("SYMBOL").agg(FO_CLOSE=("CLOSE", "last"), OI=("OI", "sum")).reset_index()

    if "PREV_CLOSE" in cc.columns:
        agg = agg.merge(
            cc.groupby("SYMBOL").agg(FO_PREV_CLOSE=("PREV_CLOSE", "last")).reset_index(),
            on="SYMBOL", how="left")

    if "OI_CHANGE_ABS" in cc.columns:
        agg = agg.merge(
            cc.groupby("SYMBOL").agg(OI_CHANGE_ABS=("OI_CHANGE_ABS", "sum")).reset_index(),
            on="SYMBOL", how="left")
        agg["OI_PREV"] = agg["OI"] - agg["OI_CHANGE_ABS"]
    else:
        agg["OI_PREV"] = np.nan
        agg["OI_CHANGE_ABS"] = np.nan

    agg["OI_CHANGE_PCT"] = np.where(
        agg["OI_PREV"].notna() & (agg["OI_PREV"] != 0),
        ((agg["OI"] - agg["OI_PREV"]) / agg["OI_PREV"]) * 100,
        np.nan,
    )

    logger.info(f"Parsed {len(agg)} stocks from F&O bhavcopy")
    return agg


def parse_cm_bhavcopy(df: pd.DataFrame) -> pd.DataFrame:
    """
    Extract equity close, prev close, and delivery % from CM bhavcopy.
    UDiFF format: TCKRSYMB, SCTYSRS, CLSPRIC, PRVSCLSGPRIC, TTLTRADGVOL, DLVRYQTY.
    Uses find_col to pick ONE column per field — avoids duplicate column name errors.
    """
    logger.info(f"CM Bhavcopy columns: {list(df.columns)}")

    def find_col(candidates):
        for name in candidates:
            if name in df.columns:
                return name
        return None

    sym_col    = find_col(["TCKRSYMB", "SYMBOL", "SYMBOLNAME"])
    series_col = find_col(["SCTYSRS", "SERIES", "SRIESSRS"])
    close_col  = find_col(["CLSPRIC", "LASTPRIC", "STTLMPRIC", "CLOSE", "CLOSE_PRICE"])
    prev_col   = find_col(["PRVSCLSGPRIC", "PREVCLOSE", "PREV_CLOSE", "PREV_CLS"])
    deliv_pct  = find_col(["DLVRYQTYPCTGOFTRADGQTY", "DELIVERY_PCT", "DELIV_PER"])
    deliv_qty  = find_col(["DLVRYQTY", "DELIVERYQTY", "DELIV_QTY"])
    total_qty  = find_col(["TTLTRADGVOL", "TTL_TRD_QNTY", "TOTTRDQTY", "TOT_TRD_QTY"])

    if not sym_col or not close_col:
        logger.warning(f"Missing critical CM columns. sym={sym_col}, close={close_col}")
        return pd.DataFrame()

    cols = {sym_col: "SYMBOL", close_col: "CM_CLOSE"}
    if series_col: cols[series_col] = "SERIES"
    if prev_col:   cols[prev_col]   = "CM_PREV_CLOSE"
    if deliv_pct:  cols[deliv_pct]  = "DELIVERY_PCT"
    if deliv_qty:  cols[deliv_qty]  = "DELIVERY_QTY"
    if total_qty:  cols[total_qty]  = "TOTAL_QTY"

    df2 = df[list(cols.keys())].copy().rename(columns=cols)

    # Keep EQ series only
    if "SERIES" in df2.columns:
        df2 = df2[df2["SERIES"].astype(str).str.strip().str.upper() == "EQ"].copy()

    # Compute delivery % if not present
    if "DELIVERY_PCT" not in df2.columns:
        if "DELIVERY_QTY" in df2.columns and "TOTAL_QTY" in df2.columns:
            df2["DELIVERY_PCT"] = (
                pd.to_numeric(df2["DELIVERY_QTY"], errors="coerce") /
                pd.to_numeric(df2["TOTAL_QTY"], errors="coerce") * 100
            )

    for num_col in ("CM_CLOSE", "CM_PREV_CLOSE", "DELIVERY_PCT"):
        if num_col in df2.columns:
            df2[num_col] = pd.to_numeric(df2[num_col], errors="coerce")

    keep = ["SYMBOL", "CM_CLOSE", "CM_PREV_CLOSE", "DELIVERY_PCT"]
    existing = [c for c in keep if c in df2.columns]
    df2 = df2[existing].drop_duplicates(subset="SYMBOL", keep="last").reset_index(drop=True)

    logger.info(f"CM parsed: {len(df2)} EQ rows, columns: {existing}")
    return df2


def parse_participant_oi(df: pd.DataFrame) -> dict:
    """
    Parse participant OI file to extract FII net positions and market bias.
    Returns a dict with macro context.
    """
    result = {
        "fii_index_fut_long": 0,
        "fii_index_fut_short": 0,
        "fii_index_fut_net": 0,
        "fii_index_opt_long": 0,
        "fii_index_opt_short": 0,
        "fii_index_opt_net": 0,
        "fii_total_net": 0,
        "dii_total_net": 0,
        "client_total_net": 0,
        "market_bias": "NEUTRAL",
        "raw_data": df.to_dict(orient="records") if not df.empty else [],
    }

    if df.empty:
        return result

    # Normalize column names
    df.columns = df.columns.str.strip().str.upper()

    # Try to find FII row
    client_col = None
    for c in df.columns:
        if "CLIENT" in c or "PARTICIPANT" in c or "TYPE" in c:
            client_col = c
            break

    if client_col is None and len(df.columns) > 0:
        client_col = df.columns[0]

    if client_col:
        for _, row in df.iterrows():
            participant = str(row.get(client_col, "")).strip().upper()

            # Try to find numeric columns
            cols = list(df.columns)
            nums = [pd.to_numeric(row.get(c, 0), errors="coerce") or 0 for c in cols]

            if "FII" in participant or "FOREIGN" in participant:
                # Heuristic: long cols have 'LONG' or are even-indexed, short are odd
                long_cols = [c for c in cols if "LONG" in c.upper()]
                short_cols = [c for c in cols if "SHORT" in c.upper()]

                if long_cols and short_cols:
                    # Index futures (first pair)
                    try:
                        idx_long_col = [c for c in long_cols if "INDEX" in c.upper() or "FUT" in c.upper()]
                        idx_short_col = [c for c in short_cols if "INDEX" in c.upper() or "FUT" in c.upper()]
                        if idx_long_col:
                            result["fii_index_fut_long"] = float(pd.to_numeric(row[idx_long_col[0]], errors="coerce") or 0)
                        if idx_short_col:
                            result["fii_index_fut_short"] = float(pd.to_numeric(row[idx_short_col[0]], errors="coerce") or 0)
                    except Exception:
                        pass

                # Fallback: use positional approach
                if result["fii_index_fut_long"] == 0:
                    numeric_vals = []
                    for c in cols[1:]:
                        try:
                            v = float(pd.to_numeric(row[c], errors="coerce") or 0)
                            numeric_vals.append(v)
                        except Exception:
                            numeric_vals.append(0)
                    if len(numeric_vals) >= 2:
                        result["fii_index_fut_long"] = numeric_vals[0]
                        result["fii_index_fut_short"] = numeric_vals[1]
                        if len(numeric_vals) >= 4:
                            result["fii_index_opt_long"] = numeric_vals[2]
                            result["fii_index_opt_short"] = numeric_vals[3]

            elif "DII" in participant or "DOMESTIC" in participant:
                long_cols = [c for c in cols if "LONG" in c.upper()]
                short_cols = [c for c in cols if "SHORT" in c.upper()]
                if long_cols and short_cols:
                    try:
                        result["dii_total_net"] += float(pd.to_numeric(row[long_cols[0]], errors="coerce") or 0)
                        result["dii_total_net"] -= float(pd.to_numeric(row[short_cols[0]], errors="coerce") or 0)
                    except Exception:
                        pass

            elif "CLIENT" in participant or "RETAIL" in participant:
                long_cols = [c for c in cols if "LONG" in c.upper()]
                short_cols = [c for c in cols if "SHORT" in c.upper()]
                if long_cols and short_cols:
                    try:
                        result["client_total_net"] += float(pd.to_numeric(row[long_cols[0]], errors="coerce") or 0)
                        result["client_total_net"] -= float(pd.to_numeric(row[short_cols[0]], errors="coerce") or 0)
                    except Exception:
                        pass

    result["fii_index_fut_net"] = result["fii_index_fut_long"] - result["fii_index_fut_short"]
    result["fii_index_opt_net"] = result["fii_index_opt_long"] - result["fii_index_opt_short"]
    result["fii_total_net"] = result["fii_index_fut_net"] + result["fii_index_opt_net"]

    # Classify market bias
    fii_net = result["fii_index_fut_net"]
    if fii_net > 10000:
        result["market_bias"] = "BULLISH"
    elif fii_net < -10000:
        result["market_bias"] = "BEARISH"
    else:
        result["market_bias"] = "NEUTRAL"

    return result


# ─────────────────────────────────────────────
# TECHNICAL ANALYSIS
# ─────────────────────────────────────────────

def fetch_ohlcv_batch(symbols: list) -> dict:
    """
    Fetch daily OHLCV for a list of NSE symbols via yfinance.
    Returns dict: symbol → DataFrame (Date, Open, High, Low, Close, Volume)
    """
    if yf is None:
        raise ImportError("yfinance not installed. Run: pip install yfinance")

    result = {}
    tickers_ns = [s + YFINANCE_SUFFIX for s in symbols]

    # Process in batches
    for i in range(0, len(tickers_ns), YFINANCE_BATCH_SIZE):
        batch = tickers_ns[i:i + YFINANCE_BATCH_SIZE]
        batch_syms = symbols[i:i + YFINANCE_BATCH_SIZE]
        logger.info(f"  Fetching batch {i//YFINANCE_BATCH_SIZE + 1}: {batch_syms[:5]}...")

        try:
            data = yf.download(
                batch,
                period=YFINANCE_PERIOD,
                interval=YFINANCE_INTERVAL,
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=True,
            )

            for sym, ticker in zip(batch_syms, batch):
                try:
                    if len(batch) == 1:
                        df_sym = data.copy()
                    else:
                        if ticker in data.columns.get_level_values(0):
                            df_sym = data[ticker].copy()
                        else:
                            logger.warning(f"    {sym}: No data in batch")
                            continue

                    df_sym = df_sym.dropna(how="all")
                    if len(df_sym) < 30:
                        logger.warning(f"    {sym}: Insufficient data ({len(df_sym)} rows)")
                        continue

                    df_sym.index = pd.to_datetime(df_sym.index)
                    df_sym.columns = [c[0] if isinstance(c, tuple) else c for c in df_sym.columns]
                    result[sym] = df_sym

                except Exception as e:
                    logger.warning(f"    {sym}: Parse error — {e}")

        except Exception as e:
            logger.error(f"  Batch download error: {e}")

        if i + YFINANCE_BATCH_SIZE < len(tickers_ns):
            time.sleep(YFINANCE_BATCH_DELAY)

    return result


def compute_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.Series:
    """Pure-pandas Supertrend implementation (no external dependency)."""
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    # True Range
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()

    hl2 = (high + low) / 2
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    supertrend = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(index=df.index, dtype=int)  # 1 = bullish, -1 = bearish

    for i in range(period, len(df)):
        idx = df.index[i]
        prev_idx = df.index[i - 1]

        # Upper band
        ub = upper_band.iloc[i]
        if prev_idx in supertrend.index and not pd.isna(supertrend[prev_idx]):
            prev_ub = upper_band.iloc[i - 1]
            if ub < prev_ub or close.iloc[i - 1] > prev_ub:
                pass  # keep new value
            else:
                upper_band.iloc[i] = prev_ub

        # Lower band
        lb = lower_band.iloc[i]
        if prev_idx in supertrend.index and not pd.isna(supertrend[prev_idx]):
            prev_lb = lower_band.iloc[i - 1]
            if lb > prev_lb or close.iloc[i - 1] < prev_lb:
                pass
            else:
                lower_band.iloc[i] = prev_lb

        # Direction
        if i == period:
            direction.iloc[i] = 1 if close.iloc[i] > upper_band.iloc[i] else -1
        else:
            prev_dir = direction.iloc[i - 1]
            if prev_dir == -1 and close.iloc[i] > upper_band.iloc[i]:
                direction.iloc[i] = 1
            elif prev_dir == 1 and close.iloc[i] < lower_band.iloc[i]:
                direction.iloc[i] = -1
            else:
                direction.iloc[i] = prev_dir

        supertrend.iloc[i] = lower_band.iloc[i] if direction.iloc[i] == 1 else upper_band.iloc[i]

    return supertrend, direction


def compute_bollinger_bands(close: pd.Series) -> dict:
    """
    Compute Bollinger Bands and detect squeeze condition.
    Returns upper, lower, mid, bandwidth, %B, and squeeze flag.
    """
    mid = close.rolling(BB_PERIOD).mean()
    std = close.rolling(BB_PERIOD).std()
    upper = mid + BB_STD_DEV * std
    lower = mid - BB_STD_DEV * std
    bandwidth = (upper - lower) / mid  # normalised bandwidth
    pct_b = (close - lower) / (upper - lower).replace(0, np.nan)

    last_bw   = bandwidth.iloc[-1]
    last_pctb = pct_b.iloc[-1]
    squeeze   = (not pd.isna(last_bw)) and (last_bw < BB_SQUEEZE_THRESHOLD)

    # Score:
    # +2 = squeeze + price above mid (coiled bullish)
    # -2 = squeeze + price below mid (coiled bearish)
    # +1 = %B > 0.8 (riding upper band, momentum)
    # -1 = %B < 0.2 (riding lower band, weakness)
    #  0 = neutral
    last_close = close.iloc[-1]
    last_mid   = mid.iloc[-1]

    if squeeze and last_close > last_mid:
        bb_score  = 2
        bb_signal = "SQUEEZE BULLISH"
    elif squeeze and last_close < last_mid:
        bb_score  = -2
        bb_signal = "SQUEEZE BEARISH"
    elif not pd.isna(last_pctb) and last_pctb > 0.8:
        bb_score  = 1
        bb_signal = "UPPER BAND RIDE"
    elif not pd.isna(last_pctb) and last_pctb < 0.2:
        bb_score  = -1
        bb_signal = "LOWER BAND RIDE"
    else:
        bb_score  = 0
        bb_signal = "MID RANGE"

    return {
        "score":     bb_score,
        "signal":    bb_signal,
        "squeeze":   squeeze,
        "bandwidth": round(float(last_bw), 4)   if not pd.isna(last_bw)   else None,
        "pct_b":     round(float(last_pctb), 3) if not pd.isna(last_pctb) else None,
        "upper":     round(float(upper.iloc[-1]), 2),
        "lower":     round(float(lower.iloc[-1]), 2),
        "mid":       round(float(last_mid), 2),
    }


def compute_breakout(df: pd.DataFrame, vol_ratio: float) -> dict:
    """
    Detect 52-week high/low breakouts and near-breakout conditions.
    Requires volume confirmation for a true breakout signal.
    """
    close  = df["Close"]
    high   = df["High"]
    low    = df["Low"]

    # Use full available history up to BREAKOUT_LOOKBACK days
    lookback = min(BREAKOUT_LOOKBACK * 5, len(df) - 1)  # ~252 trading days
    period_high = high.iloc[-lookback:-1].max()
    period_low  = low.iloc[-lookback:-1].min()

    last_close = close.iloc[-1]
    last_high  = high.iloc[-1]
    last_low   = low.iloc[-1]

    vol_confirmed = vol_ratio >= BREAKOUT_CONFIRM_VOL

    near_high = (period_high - last_close) / period_high * 100 <= BREAKOUT_NEAR_PCT
    near_low  = (last_close - period_low)  / period_low  * 100 <= BREAKOUT_NEAR_PCT

    # True breakout: price closes above/below the period range
    breakout_up   = last_close > period_high
    breakout_down = last_close < period_low

    if breakout_up and vol_confirmed:
        bo_score  = 3
        bo_signal = "52W HIGH BREAKOUT"
    elif breakout_up and not vol_confirmed:
        bo_score  = 1
        bo_signal = "52W HIGH (UNCONFIRMED)"
    elif breakout_down and vol_confirmed:
        bo_score  = -3
        bo_signal = "52W LOW BREAKDOWN"
    elif breakout_down and not vol_confirmed:
        bo_score  = -1
        bo_signal = "52W LOW (UNCONFIRMED)"
    elif near_high:
        bo_score  = 1
        bo_signal = "NEAR 52W HIGH"
    elif near_low:
        bo_score  = -1
        bo_signal = "NEAR 52W LOW"
    else:
        bo_score  = 0
        bo_signal = "NO BREAKOUT"

    dist_from_high = round((period_high - last_close) / period_high * 100, 1)
    dist_from_low  = round((last_close - period_low)  / period_low  * 100, 1)

    return {
        "score":          bo_score,
        "signal":         bo_signal,
        "period_high":    round(float(period_high), 2),
        "period_low":     round(float(period_low), 2),
        "dist_from_high": dist_from_high,
        "dist_from_low":  dist_from_low,
        "vol_confirmed":  vol_confirmed,
    }



def compute_nr7(df):
    """NR7/NR4: Narrowest range in 7/4 days — coiled spring signal."""
    high  = df["High"]
    low   = df["Low"]
    close = df["Close"]
    if len(df) < 7:
        return {"score": 0, "signal": "N/A", "is_nr7": False, "is_nr4": False, "range_pct": None}
    daily_range = high - low
    last_range  = daily_range.iloc[-1]
    is_nr7 = bool(last_range == daily_range.iloc[-7:].min())
    is_nr4 = bool(last_range == daily_range.iloc[-4:].min())
    range_pct = round(last_range / close.iloc[-1] * 100, 2)
    midpoint  = (high.iloc[-1] + low.iloc[-1]) / 2
    bull_bias = close.iloc[-1] > midpoint
    if is_nr7:
        score  = 1 if bull_bias else -1
        signal = "NR7 BULL COIL" if bull_bias else "NR7 BEAR COIL"
    elif is_nr4:
        score  = 1 if bull_bias else -1
        signal = "NR4 BULL COIL" if bull_bias else "NR4 BEAR COIL"
    else:
        score  = 0
        signal = "NO NR"
    return {"score": score, "signal": signal, "is_nr7": is_nr7, "is_nr4": is_nr4, "range_pct": range_pct}


def compute_rsi_divergence(close, rsi, lookback=14):
    """RSI Divergence: price vs RSI disagreement signals reversal."""
    if len(close) < lookback + 2 or len(rsi) < lookback + 2:
        return {"score": 0, "signal": "NO DIVERGENCE", "type": None}
    price_window = close.iloc[-(lookback + 1):]
    rsi_window   = rsi.iloc[-(lookback + 1):]
    price_lows, rsi_lows, price_highs, rsi_highs = [], [], [], []
    for i in range(1, len(price_window) - 1):
        p = price_window.iloc[i]
        r = rsi_window.iloc[i]
        if p < price_window.iloc[i-1] and p < price_window.iloc[i+1]:
            price_lows.append(p); rsi_lows.append(r)
        if p > price_window.iloc[i-1] and p > price_window.iloc[i+1]:
            price_highs.append(p); rsi_highs.append(r)
    bullish_div = (len(price_lows) >= 2 and price_lows[-1] < price_lows[-2] and rsi_lows[-1] > rsi_lows[-2])
    bearish_div = (len(price_highs) >= 2 and price_highs[-1] > price_highs[-2] and rsi_highs[-1] < rsi_highs[-2])
    if bullish_div:
        return {"score": 2, "signal": "BULLISH DIVERGENCE", "type": "BULLISH"}
    elif bearish_div:
        return {"score": -2, "signal": "BEARISH DIVERGENCE", "type": "BEARISH"}
    return {"score": 0, "signal": "NO DIVERGENCE", "type": None}


def compute_pivot_points(df):
    """Standard pivot points from previous day OHLC — entry and SL levels."""
    if len(df) < 2:
        return {}
    prev  = df.iloc[-2]
    h, l, c = float(prev["High"]), float(prev["Low"]), float(prev["Close"])
    pivot = (h + l + c) / 3
    r1 = 2 * pivot - l;  r2 = pivot + (h - l)
    s1 = 2 * pivot - h;  s2 = pivot - (h - l)
    last_close = float(df["Close"].iloc[-1])
    if last_close > r2:      position, bias = "ABOVE R2",    "VERY BULLISH"
    elif last_close > r1:    position, bias = "ABOVE R1",    "BULLISH"
    elif last_close > pivot: position, bias = "ABOVE PIVOT", "MILD BULLISH"
    elif last_close > s1:    position, bias = "BELOW PIVOT", "MILD BEARISH"
    elif last_close > s2:    position, bias = "NEAR S1",     "BEARISH"
    else:                    position, bias = "BELOW S2",    "VERY BEARISH"
    return {
        "pivot": round(pivot, 2), "r1": round(r1, 2), "r2": round(r2, 2),
        "s1": round(s1, 2), "s2": round(s2, 2),
        "position": position, "bias": bias,
        "dist_to_r1_pct": round((r1 - last_close) / last_close * 100, 2),
        "dist_to_s1_pct": round((last_close - s1) / last_close * 100, 2),
    }


def compute_candlestick_pattern(df):
    """Detect key reversal candle patterns on the last bar."""
    if len(df) < 2:
        return {"score": 0, "signal": "NONE", "pattern": None}
    o1, h1, l1, c1 = float(df["Open"].iloc[-1]), float(df["High"].iloc[-1]), float(df["Low"].iloc[-1]), float(df["Close"].iloc[-1])
    o2, h2, l2, c2 = float(df["Open"].iloc[-2]), float(df["High"].iloc[-2]), float(df["Low"].iloc[-2]), float(df["Close"].iloc[-2])
    body1 = abs(c1 - o1); full_range1 = h1 - l1
    upper_wick1 = h1 - max(o1, c1); lower_wick1 = min(o1, c1) - l1
    body2 = abs(c2 - o2)
    is_bull1 = c1 > o1; is_bear1 = c1 < o1; is_bull2 = c2 > o2
    if full_range1 == 0:
        return {"score": 0, "signal": "NONE", "pattern": None}
    body_pct  = body1 / full_range1
    upper_pct = upper_wick1 / full_range1
    lower_pct = lower_wick1 / full_range1
    if body_pct < 0.10:
        return {"score": 0, "signal": "DOJI", "pattern": "DOJI"}
    if body_pct > 0.90:
        s = 1 if is_bull1 else -1
        sig = "BULL MARUBOZU" if is_bull1 else "BEAR MARUBOZU"
        return {"score": s, "signal": sig, "pattern": sig}
    if lower_pct > 0.55 and upper_pct < 0.15:
        return {"score": 1, "signal": "HAMMER", "pattern": "HAMMER"}
    if upper_pct > 0.55 and lower_pct < 0.15:
        return {"score": -1, "signal": "SHOOTING STAR", "pattern": "SHOOTING STAR"}
    if is_bull1 and not is_bull2 and c1 > o2 and o1 < c2 and body1 > body2:
        return {"score": 1, "signal": "BULL ENGULFING", "pattern": "BULL ENGULFING"}
    if is_bear1 and is_bull2 and o1 > c2 and c1 < o2 and body1 > body2:
        return {"score": -1, "signal": "BEAR ENGULFING", "pattern": "BEAR ENGULFING"}
    return {"score": 0, "signal": "NONE", "pattern": None}


def compute_entry_signal(components, fo_signal, composite_score):
    """
    Combine NR7 + RSI Divergence + Pivot + Candlestick + BB Squeeze + OI
    into a single ENTRY_SIGNAL with confirmation count.
    STRONG ENTRY = 3+ confirmations, WATCH = 1-2, NO ENTRY = 0.
    """
    confirmations = []
    if composite_score >= 12:
        direction = "LONG"
    elif composite_score <= -12:
        direction = "SHORT"
    else:
        return {"entry_signal": "NO SIGNAL", "entry_score": 0, "entry_confirmations": []}
    nr     = components.get("NR7", {})
    div    = components.get("RSI_DIV", {})
    candle = components.get("CANDLE", {})
    pivot  = components.get("PIVOT", {})
    bb     = components.get("BOLLINGER", {})
    nr_signal = nr.get("signal", "")
    if direction == "LONG"  and "BULL COIL" in nr_signal: confirmations.append("NR7 COIL")
    if direction == "SHORT" and "BEAR COIL" in nr_signal: confirmations.append("NR7 COIL")
    div_type = div.get("type")
    if direction == "LONG"  and div_type == "BULLISH": confirmations.append("RSI DIV")
    if direction == "SHORT" and div_type == "BEARISH": confirmations.append("RSI DIV")
    candle_score = candle.get("score", 0); candle_sig = candle.get("signal", "NONE")
    if direction == "LONG"  and candle_score > 0 and candle_sig != "NONE": confirmations.append(f"CANDLE:{candle_sig}")
    if direction == "SHORT" and candle_score < 0 and candle_sig != "NONE": confirmations.append(f"CANDLE:{candle_sig}")
    pivot_bias = pivot.get("bias", "")
    if direction == "LONG"  and "BULLISH" in pivot_bias: confirmations.append("PIVOT BULL")
    if direction == "SHORT" and "BEARISH" in pivot_bias: confirmations.append("PIVOT BEAR")
    if bb.get("squeeze", False): confirmations.append("BB SQUEEZE")
    if direction == "LONG"  and fo_signal in ("LONG BUILDUP", "SHORT COVERING"):  confirmations.append(f"OI:{fo_signal}")
    if direction == "SHORT" and fo_signal in ("SHORT BUILDUP", "LONG UNWINDING"): confirmations.append(f"OI:{fo_signal}")
    n = len(confirmations)
    if n >= 3:   entry_signal = f"STRONG {direction} ENTRY"
    elif n >= 1: entry_signal = f"WATCH {direction}"
    else:        entry_signal = "NO ENTRY"
    return {"entry_signal": entry_signal, "entry_score": n, "entry_confirmations": confirmations}


def calculate_technical_indicators(df: pd.DataFrame) -> dict:
    """
    Calculate all technical indicators for a single stock.
    Returns a dict of indicator values and score components.
    """
    if df is None or len(df) < 60:
        return None

    close = df["Close"]
    volume = df["Volume"]
    high = df["High"]
    low = df["Low"]

    indicators = {}
    score = 0
    components = {}

    # ── EMA Alignment ──────────────────────────────
    ema20  = close.ewm(span=EMA_SHORT,  adjust=False).mean()
    ema50  = close.ewm(span=EMA_MID,    adjust=False).mean()
    ema200 = close.ewm(span=EMA_LONG,   adjust=False).mean()

    last_close = close.iloc[-1]
    e20 = ema20.iloc[-1]
    e50 = ema50.iloc[-1]
    e200 = ema200.iloc[-1]

    indicators.update({"EMA20": round(e20, 2), "EMA50": round(e50, 2), "EMA200": round(e200, 2)})

    if last_close > e20 > e50 > e200:
        ema_score = 2
        ema_signal = "BULLISH"
    elif last_close < e20 < e50 < e200:
        ema_score = -2
        ema_signal = "BEARISH"
    else:
        ema_score = 0
        ema_signal = "MIXED"

    score += ema_score
    components["EMA"] = {"score": ema_score, "signal": ema_signal}

    # ── RSI ─────────────────────────────────────────
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=RSI_PERIOD - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=RSI_PERIOD - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi_val = rsi.iloc[-1]
    indicators["RSI"] = round(rsi_val, 1)

    if RSI_BULL_LOW <= rsi_val <= RSI_BULL_HIGH:
        rsi_score = 2
        rsi_signal = "BULLISH"
    elif RSI_BEAR_LOW <= rsi_val <= RSI_BEAR_HIGH:
        rsi_score = -2
        rsi_signal = "BEARISH"
    else:
        rsi_score = 0
        rsi_signal = "NEUTRAL"

    score += rsi_score
    components["RSI"] = {"score": rsi_score, "signal": rsi_signal, "value": round(rsi_val, 1)}

    # ── MACD ────────────────────────────────────────
    exp1 = close.ewm(span=MACD_FAST, adjust=False).mean()
    exp2 = close.ewm(span=MACD_SLOW, adjust=False).mean()
    macd_line = exp1 - exp2
    signal_line = macd_line.ewm(span=MACD_SIGNAL, adjust=False).mean()

    # Check for crossover in last 2 bars
    macd_prev = macd_line.iloc[-2]
    macd_curr = macd_line.iloc[-1]
    sig_prev  = signal_line.iloc[-2]
    sig_curr  = signal_line.iloc[-1]

    if macd_prev <= sig_prev and macd_curr > sig_curr:
        macd_score = 2
        macd_signal = "BULLISH CROSS"
    elif macd_prev >= sig_prev and macd_curr < sig_curr:
        macd_score = -2
        macd_signal = "BEARISH CROSS"
    else:
        macd_score = 0
        macd_signal = "ABOVE SIGNAL" if macd_curr > sig_curr else "BELOW SIGNAL"

    indicators["MACD"] = round(macd_curr, 3)
    indicators["MACD_SIGNAL"] = round(sig_curr, 3)
    score += macd_score
    components["MACD"] = {"score": macd_score, "signal": macd_signal}

    # ── ADX ─────────────────────────────────────────
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr14 = tr.ewm(span=ADX_PERIOD, adjust=False).mean()

    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    dm_plus  = up_move.where((up_move > down_move) & (up_move > 0), 0)
    dm_minus = down_move.where((down_move > up_move) & (down_move > 0), 0)
    di_plus  = 100 * dm_plus.ewm(span=ADX_PERIOD, adjust=False).mean() / atr14
    di_minus = 100 * dm_minus.ewm(span=ADX_PERIOD, adjust=False).mean() / atr14
    dx = (100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)).fillna(0)
    adx = dx.ewm(span=ADX_PERIOD, adjust=False).mean()

    adx_val = adx.iloc[-1]
    dip = di_plus.iloc[-1]
    dim = di_minus.iloc[-1]
    indicators["ADX"] = round(adx_val, 1)
    indicators["DI_PLUS"] = round(dip, 1)
    indicators["DI_MINUS"] = round(dim, 1)

    if adx_val > ADX_TREND_THRESHOLD and dip > dim:
        adx_score = 2
        adx_signal = "BULL TREND"
    elif adx_val > ADX_TREND_THRESHOLD and dim > dip:
        adx_score = -2
        adx_signal = "BEAR TREND"
    else:
        adx_score = 0
        adx_signal = "NO TREND"

    score += adx_score
    components["ADX"] = {"score": adx_score, "signal": adx_signal, "value": round(adx_val, 1)}

    # ── Supertrend ──────────────────────────────────
    try:
        st_vals, st_dir = compute_supertrend(df, SUPERTREND_PERIOD, SUPERTREND_MULTIPLIER)
        st_last_dir = st_dir.iloc[-1] if not st_dir.empty else 0
        st_score = 2 if st_last_dir == 1 else (-2 if st_last_dir == -1 else 0)
        st_signal = "ABOVE" if st_last_dir == 1 else "BELOW"
        indicators["SUPERTREND"] = round(st_vals.iloc[-1], 2) if not st_vals.empty else None
    except Exception as e:
        logger.debug(f"Supertrend error: {e}")
        st_score = 0
        st_signal = "N/A"
        indicators["SUPERTREND"] = None

    score += st_score
    components["SUPERTREND"] = {"score": st_score, "signal": st_signal}

    # ── Volume ──────────────────────────────────────
    vol_ma = volume.rolling(VOLUME_MA_PERIOD).mean()
    vol_ratio = volume.iloc[-1] / vol_ma.iloc[-1] if vol_ma.iloc[-1] > 0 else 1.0
    indicators["VOLUME_RATIO"] = round(vol_ratio, 2)
    indicators["VOLUME"] = int(volume.iloc[-1])

    if vol_ratio >= VOLUME_HIGH_RATIO:
        vol_score = 1
        vol_signal = "HIGH"
    elif vol_ratio <= VOLUME_LOW_RATIO:
        vol_score = -1
        vol_signal = "LOW"
    else:
        vol_score = 0
        vol_signal = "NORMAL"

    score += vol_score
    components["VOLUME"] = {"score": vol_score, "signal": vol_signal, "ratio": round(vol_ratio, 2)}

    # ── Bollinger Bands ─────────────────────────────
    try:
        bb = compute_bollinger_bands(close)
        score += bb["score"]
        components["BOLLINGER"] = bb
        indicators["BB_UPPER"]     = bb["upper"]
        indicators["BB_LOWER"]     = bb["lower"]
        indicators["BB_MID"]       = bb["mid"]
        indicators["BB_BANDWIDTH"] = bb["bandwidth"]
        indicators["BB_PCT_B"]     = bb["pct_b"]
        indicators["BB_SQUEEZE"]   = bb["squeeze"]
    except Exception as e:
        logger.debug(f"Bollinger error: {e}")
        bb = {"score": 0, "signal": "N/A", "squeeze": False}
        components["BOLLINGER"] = bb

    # ── Breakout Detection ──────────────────────────
    try:
        bo = compute_breakout(df, vol_ratio)
        score += bo["score"]
        components["BREAKOUT"] = bo
        indicators["BREAKOUT_SIGNAL"]     = bo["signal"]
        indicators["DIST_FROM_52W_HIGH"]  = bo["dist_from_high"]
        indicators["DIST_FROM_52W_LOW"]   = bo["dist_from_low"]
        indicators["W52_HIGH"]            = bo["period_high"]
        indicators["W52_LOW"]             = bo["period_low"]
    except Exception as e:
        logger.debug(f"Breakout error: {e}")
        bo = {"score": 0, "signal": "N/A"}
        components["BREAKOUT"] = bo

    # ── NR7 / NR4 ──────────────────────────────────
    try:
        nr = compute_nr7(df)
        score += nr["score"]
        components["NR7"] = nr
        indicators["NR_SIGNAL"]   = nr["signal"]
        indicators["NR_RANGE_PCT"] = nr["range_pct"]
    except Exception as e:
        logger.debug(f"NR7 error: {e}")
        nr = {"score": 0, "signal": "N/A"}
        components["NR7"] = nr

    # ── RSI Divergence ──────────────────────────────
    try:
        rsi_div = compute_rsi_divergence(close, rsi)
        score += rsi_div["score"]
        components["RSI_DIV"] = rsi_div
        indicators["RSI_DIV_SIGNAL"] = rsi_div["signal"]
    except Exception as e:
        logger.debug(f"RSI divergence error: {e}")
        rsi_div = {"score": 0, "signal": "N/A", "type": None}
        components["RSI_DIV"] = rsi_div

    # ── Pivot Points ────────────────────────────────
    try:
        pivot = compute_pivot_points(df)
        components["PIVOT"] = pivot
        indicators["PIVOT"]          = pivot.get("pivot")
        indicators["PIVOT_R1"]       = pivot.get("r1")
        indicators["PIVOT_R2"]       = pivot.get("r2")
        indicators["PIVOT_S1"]       = pivot.get("s1")
        indicators["PIVOT_S2"]       = pivot.get("s2")
        indicators["PIVOT_POSITION"] = pivot.get("position")
        indicators["PIVOT_BIAS"]     = pivot.get("bias")
    except Exception as e:
        logger.debug(f"Pivot error: {e}")
        pivot = {}
        components["PIVOT"] = pivot

    # ── Candlestick Pattern ─────────────────────────
    try:
        candle = compute_candlestick_pattern(df)
        score += candle["score"]
        components["CANDLE"] = candle
        indicators["CANDLE_PATTERN"] = candle["signal"]
    except Exception as e:
        logger.debug(f"Candle error: {e}")
        candle = {"score": 0, "signal": "NONE"}
        components["CANDLE"] = candle

    indicators["PRICE"] = round(last_close, 2)
    indicators["PRICE_CHANGE_PCT"] = round(
        (last_close - close.iloc[-2]) / close.iloc[-2] * 100, 2
    ) if len(close) > 1 else 0

    return {
        "technical_score": score,
        "indicators": indicators,
        "components": components,
        "ema_signal": ema_signal,
        "bb_signal":  components["BOLLINGER"]["signal"],
        "bb_squeeze": components["BOLLINGER"]["squeeze"],
        "breakout_signal": components["BREAKOUT"]["signal"],
        "nr_signal":       components["NR7"]["signal"],
        "rsi_div_signal":  components["RSI_DIV"]["signal"],
        "candle_signal":   components["CANDLE"]["signal"],
    }


# ─────────────────────────────────────────────
# F&O SCORING
# ─────────────────────────────────────────────

def calculate_fo_score(fo_row: pd.Series, cm_row: pd.Series, pcr_val: float = None) -> dict:
    """
    Calculate F&O score for a single stock using bhavcopy data.
    Returns score components and total F&O score.
    """
    score = 0
    components = {}

    # ── OI + Price classification ───────────────────
    oi_chg_pct = fo_row.get("OI_CHANGE_PCT", np.nan)
    fo_close   = fo_row.get("FO_CLOSE", np.nan)
    fo_prev    = fo_row.get("FO_PREV_CLOSE", np.nan)

    # Use CM price if FO close not available
    if pd.isna(fo_prev) and "CM_PREV_CLOSE" in cm_row.index:
        fo_prev = cm_row.get("CM_PREV_CLOSE", np.nan)
    if pd.isna(fo_close) and "CM_CLOSE" in cm_row.index:
        fo_close = cm_row.get("CM_CLOSE", np.nan)

    price_up = (not pd.isna(fo_close) and not pd.isna(fo_prev) and fo_close > fo_prev)
    price_dn = (not pd.isna(fo_close) and not pd.isna(fo_prev) and fo_close < fo_prev)
    oi_up    = (not pd.isna(oi_chg_pct) and oi_chg_pct > 0)
    oi_dn    = (not pd.isna(oi_chg_pct) and oi_chg_pct < 0)

    if oi_up and price_up:
        oi_score = 3
        oi_signal = "LONG BUILDUP"
    elif oi_dn and price_up:
        oi_score = 2
        oi_signal = "SHORT COVERING"
    elif oi_up and price_dn:
        oi_score = -3
        oi_signal = "SHORT BUILDUP"
    elif oi_dn and price_dn:
        oi_score = -2
        oi_signal = "LONG UNWINDING"
    else:
        oi_score = 0
        oi_signal = "NEUTRAL"

    score += oi_score
    components["OI_PATTERN"] = {"score": oi_score, "signal": oi_signal}

    # ── OI change magnitude bonus ───────────────────
    oi_mag_score = 0
    if not pd.isna(oi_chg_pct):
        abs_oi = abs(oi_chg_pct)
        direction = 1 if oi_chg_pct > 0 else -1
        if abs_oi > OI_CHANGE_HIGH:
            oi_mag_score = 2 * direction
        elif abs_oi > OI_CHANGE_MEDIUM:
            oi_mag_score = 1 * direction

    score += oi_mag_score
    components["OI_MAGNITUDE"] = {"score": oi_mag_score}

    # ── Delivery % ──────────────────────────────────
    delivery_pct = cm_row.get("DELIVERY_PCT", np.nan)
    if not pd.isna(delivery_pct):
        delivery_pct = float(delivery_pct)
        if delivery_pct > DELIVERY_HIGH:
            del_score = 2
            del_signal = "INSTITUTIONAL"
        elif delivery_pct < DELIVERY_LOW:
            del_score = -1
            del_signal = "SPECULATIVE"
        else:
            del_score = 0
            del_signal = "NEUTRAL"
    else:
        del_score = 0
        del_signal = "N/A"
        delivery_pct = np.nan

    score += del_score
    components["DELIVERY"] = {"score": del_score, "signal": del_signal, "value": delivery_pct}

    # ── PCR (Put-Call Ratio) ────────────────────────
    if pcr_val is not None and not pd.isna(pcr_val):
        if pcr_val < PCR_VERY_BULLISH:
            pcr_score  = 2
            pcr_signal = "CALL HEAVY"
        elif pcr_val < PCR_BULLISH:
            pcr_score  = 1
            pcr_signal = "MILD CALL HEAVY"
        elif pcr_val > PCR_VERY_BEARISH:
            pcr_score  = -2
            pcr_signal = "PUT HEAVY"
        elif pcr_val > PCR_BEARISH:
            pcr_score  = -1
            pcr_signal = "MILD PUT HEAVY"
        else:
            pcr_score  = 0
            pcr_signal = "BALANCED"
    else:
        pcr_score  = 0
        pcr_signal = "N/A"
        pcr_val    = np.nan

    score += pcr_score
    components["PCR"] = {"score": pcr_score, "signal": pcr_signal,
                         "value": round(float(pcr_val), 2) if not pd.isna(pcr_val) else None}

    return {
        "fo_score": score,
        "fo_components": components,
        "oi_signal": oi_signal,
        "oi_change_pct": round(float(oi_chg_pct), 2) if not pd.isna(oi_chg_pct) else None,
        "delivery_pct": round(delivery_pct, 1) if not pd.isna(delivery_pct) else None,
        "pcr": round(float(pcr_val), 2) if not pd.isna(pcr_val) else None,
        "pcr_signal": pcr_signal,
    }


# ─────────────────────────────────────────────
# COMPOSITE SCORING & CLASSIFICATION
# ─────────────────────────────────────────────

def compute_sector_summary(df_results: pd.DataFrame) -> pd.DataFrame:
    """
    Group stocks by sector and compute:
    - Count of Long / Short / Neutral signals
    - Average composite score
    - Sector bias label (BULLISH / BEARISH / MIXED / NEUTRAL)
    """
    df = df_results.copy()
    df["SECTOR"] = df["SYMBOL"].map(SECTOR_MAP).fillna("OTHERS")

    rows = []
    for sector, grp in df.groupby("SECTOR"):
        total   = len(grp)
        longs   = int((grp["COMPOSITE_SCORE"] >= LONG_THRESHOLD).sum())
        shorts  = int((grp["COMPOSITE_SCORE"] <= SHORT_THRESHOLD).sum())
        neutral = total - longs - shorts
        avg     = round(grp["COMPOSITE_SCORE"].mean(), 1)

        long_pct  = longs  / total if total > 0 else 0
        short_pct = shorts / total if total > 0 else 0

        if long_pct >= 0.5:
            bias = "BULLISH"
        elif short_pct >= 0.5:
            bias = "BEARISH"
        elif long_pct > short_pct and long_pct >= 0.3:
            bias = "MILD BULLISH"
        elif short_pct > long_pct and short_pct >= 0.3:
            bias = "MILD BEARISH"
        else:
            bias = "NEUTRAL"

        rows.append({
            "SECTOR":    sector,
            "TOTAL":     total,
            "LONGS":     longs,
            "SHORTS":    shorts,
            "NEUTRAL":   neutral,
            "AVG_SCORE": avg,
            "BIAS":      bias,
        })

    sector_df = pd.DataFrame(rows).sort_values("AVG_SCORE", ascending=False)
    return sector_df


def classify_signal(composite_score: float) -> str:
    if composite_score >= STRONG_LONG_THRESHOLD:
        return "STRONG LONG"
    elif composite_score >= LONG_THRESHOLD:
        return "LONG CANDIDATE"
    elif composite_score <= STRONG_SHORT_THRESHOLD:
        return "STRONG SHORT"
    elif composite_score <= SHORT_THRESHOLD:
        return "SHORT CANDIDATE"
    else:
        return "NEUTRAL"


# ─────────────────────────────────────────────
# MAIN SCREENER ENGINE
# ─────────────────────────────────────────────

def run_screener(trade_date: date = None) -> dict:
    """
    Main screener function. Downloads data, calculates scores,
    and returns ranked results dict.
    """
    if trade_date is None:
        trade_date = last_trading_day()
    prev_date = prev_trading_day(trade_date)

    logger.info(f"=" * 60)
    logger.info(f"F&O MORNING SCREENER — {trade_date.strftime('%d %b %Y')}")
    logger.info(f"=" * 60)

    session = make_session()

    # ── Step 1: Download NSE data ────────────────────
    logger.info("STEP 1: Downloading NSE bhavcopy files...")
    fo_raw = None
    cm_raw = None
    poi_raw = None

    try:
        fo_raw = download_fo_bhavcopy(trade_date, session)
    except Exception as e:
        logger.error(f"F&O Bhavcopy download failed: {e}")

    try:
        cm_raw = download_cm_bhavcopy(trade_date, session)
    except Exception as e:
        logger.error(f"CM Bhavcopy download failed: {e}")

    try:
        poi_raw = download_participant_oi(trade_date, session)
    except Exception as e:
        logger.error(f"Participant OI download failed: {e}")

    # ── Step 2: Parse NSE data ───────────────────────
    logger.info("STEP 2: Parsing NSE data...")
    fo_data = parse_fo_bhavcopy(fo_raw, trade_date) if fo_raw is not None else pd.DataFrame()
    cm_data = parse_cm_bhavcopy(cm_raw) if cm_raw is not None else pd.DataFrame()
    pcr_data = parse_options_pcr(fo_raw, trade_date) if fo_raw is not None else pd.DataFrame()
    macro   = parse_participant_oi(poi_raw) if poi_raw is not None else {}

    # Create lookup dicts
    fo_lookup  = fo_data.set_index("SYMBOL").to_dict(orient="index") if not fo_data.empty else {}
    cm_lookup  = cm_data.set_index("SYMBOL").to_dict(orient="index") if not cm_data.empty else {}
    pcr_lookup = pcr_data.set_index("SYMBOL")["PCR"].to_dict() if not pcr_data.empty else {}
    logger.info(f"PCR available for {len(pcr_lookup)} stocks")

    # ── Step 3: Fetch OHLCV data ─────────────────────
    logger.info(f"STEP 3: Fetching OHLCV for {len(FO_STOCKS)} stocks via yfinance...")
    ohlcv_data = fetch_ohlcv_batch(FO_STOCKS)
    logger.info(f"  Got data for {len(ohlcv_data)} stocks")

    # ── Step 3b: Fetch Nifty and compute RS ranks ────
    logger.info("Fetching Nifty50 for relative strength calculation...")
    try:
        import yfinance as yf
        nifty_raw = yf.download("^NSEI", period=YFINANCE_PERIOD,
                                interval=YFINANCE_INTERVAL, progress=False)
        if isinstance(nifty_raw.columns, pd.MultiIndex):
            nifty_raw.columns = nifty_raw.columns.get_level_values(0)
        nifty_close = nifty_raw["Close"].dropna()
        if len(nifty_close) >= RS_PERIOD + 1:
            nifty_ret = (nifty_close.iloc[-1] / nifty_close.iloc[-(RS_PERIOD + 1)] - 1) * 100
        else:
            nifty_ret = 0.0
        logger.info(f"  Nifty {RS_PERIOD}d return: {nifty_ret:.2f}%")
    except Exception as e:
        logger.warning(f"  Nifty fetch failed: {e} — RS scores will be 0")
        nifty_ret = None

    # Compute per-stock RS ratio vs Nifty and percentile rank
    rs_ratios = {}
    for symbol, ohlcv in ohlcv_data.items():
        try:
            close = ohlcv["Close"].dropna()
            if len(close) >= RS_PERIOD + 1:
                stock_ret = (close.iloc[-1] / close.iloc[-(RS_PERIOD + 1)] - 1) * 100
                rs_ratios[symbol] = float(stock_ret)
        except Exception:
            pass

    # Percentile rank within universe
    rs_values = list(rs_ratios.values())
    rs_pct_ranks = {}
    if rs_values and nifty_ret is not None:
        # Rank relative to universe (not Nifty directly) but subtract Nifty return first
        rs_excess = {s: v - nifty_ret for s, v in rs_ratios.items()}
        sorted_vals = sorted(rs_excess.values())
        n = len(sorted_vals)
        for sym, val in rs_excess.items():
            rank = sorted_vals.index(val)
            rs_pct_ranks[sym] = round((rank / (n - 1)) * 100, 1) if n > 1 else 50.0
        logger.info(f"  RS percentile ranks computed for {len(rs_pct_ranks)} stocks")

    # ── Step 4: Score each stock ─────────────────────
    logger.info("STEP 4: Calculating scores...")
    results = []

    for symbol in FO_STOCKS:
        try:
            # Technical analysis
            ohlcv = ohlcv_data.get(symbol)
            tech = calculate_technical_indicators(ohlcv) if ohlcv is not None else None

            # F&O scoring
            fo_row = pd.Series(fo_lookup.get(symbol, {}))
            cm_row = pd.Series(cm_lookup.get(symbol, {}))
            pcr_val = pcr_lookup.get(symbol, None)
            fo = calculate_fo_score(fo_row, cm_row, pcr_val)

            tech_score = tech["technical_score"] if tech else 0
            fo_score   = fo["fo_score"]

            # ── Relative Strength score ──────────────
            rs_pct  = rs_pct_ranks.get(symbol)
            if rs_pct is not None:
                if rs_pct >= RS_STRONG_BULL:
                    rs_score  = 2
                    rs_signal = "TOP RS"
                elif rs_pct >= RS_MILD_BULL:
                    rs_score  = 1
                    rs_signal = "ABOVE AVG RS"
                elif rs_pct <= RS_STRONG_BEAR:
                    rs_score  = -2
                    rs_signal = "WEAK RS"
                elif rs_pct <= RS_MILD_BEAR:
                    rs_score  = -1
                    rs_signal = "BELOW AVG RS"
                else:
                    rs_score  = 0
                    rs_signal = "NEUTRAL RS"
            else:
                rs_score  = 0
                rs_signal = "N/A"
                rs_pct    = None

            composite = tech_score + fo_score + rs_score

            row = {
                "SYMBOL": symbol,
                "COMPOSITE_SCORE": composite,
                "TECHNICAL_SCORE": tech_score,
                "FO_SCORE": fo_score,
                "RS_SCORE": rs_score,
                "RS_PCT": rs_pct,
                "RS_SIGNAL": rs_signal,
                "SIGNAL": classify_signal(composite),
                "OI_SIGNAL": fo.get("oi_signal", "N/A"),
                "OI_CHANGE_PCT": fo.get("oi_change_pct"),
                "DELIVERY_PCT": fo.get("delivery_pct"),
                "PCR": fo.get("pcr"),
                "PCR_SIGNAL": fo.get("pcr_signal", "N/A"),
                "PRICE": tech["indicators"].get("PRICE") if tech else None,
                "PRICE_CHANGE_PCT": tech["indicators"].get("PRICE_CHANGE_PCT") if tech else None,
                "RSI": tech["indicators"].get("RSI") if tech else None,
                "ADX": tech["indicators"].get("ADX") if tech else None,
                "EMA_SIGNAL": tech.get("ema_signal", "N/A") if tech else "N/A",
                "MACD_SIGNAL": tech["components"]["MACD"]["signal"] if tech else "N/A",
                "SUPERTREND_SIGNAL": tech["components"]["SUPERTREND"]["signal"] if tech else "N/A",
                "VOLUME_RATIO": tech["indicators"].get("VOLUME_RATIO") if tech else None,
                "EMA20": tech["indicators"].get("EMA20") if tech else None,
                "EMA50": tech["indicators"].get("EMA50") if tech else None,
                "EMA200": tech["indicators"].get("EMA200") if tech else None,
                # Bollinger Bands
                "BB_SIGNAL":    tech.get("bb_signal", "N/A") if tech else "N/A",
                "BB_SQUEEZE":   tech.get("bb_squeeze", False) if tech else False,
                "BB_BANDWIDTH": tech["indicators"].get("BB_BANDWIDTH") if tech else None,
                "BB_PCT_B":     tech["indicators"].get("BB_PCT_B") if tech else None,
                # Breakout
                "BREAKOUT_SIGNAL":    tech.get("breakout_signal", "N/A") if tech else "N/A",
                "DIST_FROM_52W_HIGH": tech["indicators"].get("DIST_FROM_52W_HIGH") if tech else None,
                "DIST_FROM_52W_LOW":  tech["indicators"].get("DIST_FROM_52W_LOW") if tech else None,
                "W52_HIGH":           tech["indicators"].get("W52_HIGH") if tech else None,
                "W52_LOW":            tech["indicators"].get("W52_LOW") if tech else None,
                # NR7 / Coil
                "NR_SIGNAL":   tech.get("nr_signal", "N/A") if tech else "N/A",
                "NR_RANGE_PCT": tech["indicators"].get("NR_RANGE_PCT") if tech else None,
                # RSI Divergence
                "RSI_DIV_SIGNAL": tech.get("rsi_div_signal", "NO DIVERGENCE") if tech else "N/A",
                # Candlestick
                "CANDLE_PATTERN": tech.get("candle_signal", "NONE") if tech else "N/A",
                # Pivot Points
                "PIVOT":          tech["indicators"].get("PIVOT") if tech else None,
                "PIVOT_R1":       tech["indicators"].get("PIVOT_R1") if tech else None,
                "PIVOT_R2":       tech["indicators"].get("PIVOT_R2") if tech else None,
                "PIVOT_S1":       tech["indicators"].get("PIVOT_S1") if tech else None,
                "PIVOT_S2":       tech["indicators"].get("PIVOT_S2") if tech else None,
                "PIVOT_POSITION": tech["indicators"].get("PIVOT_POSITION") if tech else None,
                "PIVOT_BIAS":     tech["indicators"].get("PIVOT_BIAS") if tech else None,
            }

            # ── Entry Signal ─────────────────────────────
            if tech:
                entry = compute_entry_signal(
                    tech["components"],
                    fo.get("oi_signal", "N/A"),
                    composite
                )
                row["ENTRY_SIGNAL"]        = entry["entry_signal"]
                row["ENTRY_SCORE"]         = entry["entry_score"]
                row["ENTRY_CONFIRMATIONS"] = ", ".join(entry["entry_confirmations"])
            else:
                row["ENTRY_SIGNAL"]        = "NO SIGNAL"
                row["ENTRY_SCORE"]         = 0
                row["ENTRY_CONFIRMATIONS"] = ""

            results.append(row)

        except Exception as e:
            logger.warning(f"  {symbol}: Scoring error — {e}")
            results.append({
                "SYMBOL": symbol,
                "COMPOSITE_SCORE": 0,
                "TECHNICAL_SCORE": 0,
                "FO_SCORE": 0,
                "SIGNAL": "ERROR",
                "OI_SIGNAL": "N/A",
            })

    # ── Step 5: Rank and classify ────────────────────
    logger.info("STEP 5: Ranking stocks...")
    df_results = pd.DataFrame(results)
    df_results = df_results.sort_values("COMPOSITE_SCORE", ascending=False).reset_index(drop=True)
    df_results["RANK"] = df_results.index + 1
    df_results["SECTOR"] = df_results["SYMBOL"].map(SECTOR_MAP).fillna("OTHERS")

    top_longs    = df_results[df_results["COMPOSITE_SCORE"] >= LONG_THRESHOLD].head(10)
    top_shorts   = df_results[df_results["COMPOSITE_SCORE"] <= SHORT_THRESHOLD].tail(10).iloc[::-1]
    sector_summary = compute_sector_summary(df_results)
    oi_alerts  = df_results[
        df_results["OI_CHANGE_PCT"].notna() &
        (df_results["OI_CHANGE_PCT"].abs() >= OI_ALERT_THRESHOLD)
    ].copy()

    # Alert severity — 3 tiers aligned with scoring bands
    # MEDIUM: 10–24% | HIGH: 25–39% | EXTREME: >=40%
    # Cross-referenced with composite score for contextual label
    if not oi_alerts.empty:
        def oi_severity(row):
            abs_oi = abs(row["OI_CHANGE_PCT"])
            comp   = row["COMPOSITE_SCORE"]
            oi_sig = row.get("OI_SIGNAL", "")

            # Tier
            if abs_oi >= OI_CHANGE_EXTREME:
                tier = "EXTREME"
            elif abs_oi >= OI_CHANGE_HIGH:
                tier = "HIGH"
            else:
                tier = "MEDIUM"

            # Cross-reference composite score for context label
            if tier == "EXTREME":
                if comp >= LONG_THRESHOLD:
                    label = "EXTREME LONG BUILDUP"
                elif comp <= SHORT_THRESHOLD:
                    label = "EXTREME SHORT BUILDUP"
                else:
                    label = "EXTREME OI — WATCH"
            elif tier == "HIGH":
                if comp >= LONG_THRESHOLD:
                    label = "STRONG OI CONFIRMATION"
                elif comp <= SHORT_THRESHOLD:
                    label = "STRONG BEARISH OI"
                else:
                    label = "HIGH OI DIVERGENCE"
            else:  # MEDIUM
                if comp >= LONG_THRESHOLD or comp <= SHORT_THRESHOLD:
                    label = f"OI {oi_sig}" if oi_sig and oi_sig != "N/A" else "OI ALERT"
                else:
                    label = "OI DIVERGENCE — WATCH"

            return pd.Series({"ALERT_SEVERITY": tier, "ALERT_LABEL": label})

        oi_alerts[["ALERT_SEVERITY", "ALERT_LABEL"]] = oi_alerts.apply(oi_severity, axis=1)

    # ── Step 6: Save output ──────────────────────────
    output_path = OUTPUT_CSV.format(date=trade_date.strftime("%Y%m%d"))
    df_results.to_csv(output_path, index=False)
    logger.info(f"Output saved: {output_path}")

    # ── Step 6b: Update signal history & compute persistence ──
    history_path = os.path.join(os.path.dirname(output_path), "signal_history.csv")

    # Append today's signals to history
    today_signals = df_results[["SYMBOL", "COMPOSITE_SCORE", "SIGNAL", "RS_PCT"]].copy()
    today_signals.insert(0, "DATE", trade_date.strftime("%Y-%m-%d"))

    if os.path.exists(history_path):
        history = pd.read_csv(history_path)
        # Remove today if already present (re-run case)
        history = history[history["DATE"] != trade_date.strftime("%Y-%m-%d")]
        history = pd.concat([history, today_signals], ignore_index=True)
    else:
        history = today_signals.copy()

    history.to_csv(history_path, index=False)
    logger.info(f"Signal history updated: {len(history)} rows across {history['DATE'].nunique()} days")

    # Compute persistence — min 3 consecutive days
    history["DATE"] = pd.to_datetime(history["DATE"])
    history = history.sort_values(["SYMBOL", "DATE"])

    def is_directional(sig):
        return sig in ("LONG CANDIDATE", "STRONG LONG", "SHORT CANDIDATE", "STRONG SHORT")

    def signal_direction(sig):
        if sig in ("LONG CANDIDATE", "STRONG LONG"):
            return "LONG"
        elif sig in ("SHORT CANDIDATE", "STRONG SHORT"):
            return "SHORT"
        return None

    persistence = {}
    for symbol, grp in history.groupby("SYMBOL"):
        grp = grp.sort_values("DATE").tail(10)  # last 10 days max
        if len(grp) < 2:
            continue
        # Check consecutive streak ending today
        today_sig = grp.iloc[-1]["SIGNAL"]
        today_dir = signal_direction(today_sig)
        if today_dir is None:
            continue
        streak = 1
        dates = grp["DATE"].tolist()
        sigs  = grp["SIGNAL"].tolist()
        for i in range(len(dates) - 2, -1, -1):
            # Must be consecutive trading days (gap <= 4 calendar days for weekends)
            gap = (dates[i + 1] - dates[i]).days
            if gap > 4:
                break
            if signal_direction(sigs[i]) == today_dir:
                streak += 1
            else:
                break
        if streak >= 3:
            persistence[symbol] = {"streak": streak, "direction": today_dir}

    # Add persistence to df_results
    df_results["PERSISTENCE"] = df_results["SYMBOL"].map(
        lambda s: persistence.get(s, {}).get("streak", 0)
    )
    df_results["PERSIST_DIR"] = df_results["SYMBOL"].map(
        lambda s: persistence.get(s, {}).get("direction", "")
    )

    persistent_longs  = df_results[df_results["PERSIST_DIR"] == "LONG"].sort_values(
        ["PERSISTENCE", "COMPOSITE_SCORE"], ascending=[False, False])
    persistent_shorts = df_results[df_results["PERSIST_DIR"] == "SHORT"].sort_values(
        ["PERSISTENCE", "COMPOSITE_SCORE"], ascending=[False, True])

    logger.info(f"Persistent signals: {len(persistence)} stocks with 3+ day streak")

    # ── Step 6c: Sector history & rotation detection ──
    sector_history_path = os.path.join(os.path.dirname(output_path), "sector_history.csv")

    # Build today's sector history rows
    today_sector = sector_summary[["SECTOR", "AVG_SCORE", "BIAS", "LONGS", "SHORTS"]].copy()
    today_sector.insert(0, "DATE", trade_date.strftime("%Y-%m-%d"))

    if os.path.exists(sector_history_path):
        sec_history = pd.read_csv(sector_history_path)
        sec_history = sec_history[sec_history["DATE"] != trade_date.strftime("%Y-%m-%d")]
        sec_history = pd.concat([sec_history, today_sector], ignore_index=True)
    else:
        sec_history = today_sector.copy()

    sec_history.to_csv(sector_history_path, index=False)
    logger.info(f"Sector history updated: {sec_history['DATE'].nunique()} days")

    # Detect rotations vs previous trading day
    sector_rotations = []
    sec_history["DATE"] = pd.to_datetime(sec_history["DATE"])
    sec_sorted = sec_history.sort_values("DATE")
    unique_dates = sorted(sec_sorted["DATE"].unique())

    if len(unique_dates) >= 2:
        prev_date = unique_dates[-2]
        curr_date = unique_dates[-1]
        prev_sec  = sec_sorted[sec_sorted["DATE"] == prev_date].set_index("SECTOR")
        curr_sec  = sec_sorted[sec_sorted["DATE"] == curr_date].set_index("SECTOR")

        bias_rank = {
            "BEARISH": -2, "MILD BEARISH": -1, "NEUTRAL": 0,
            "MILD BULLISH": 1, "BULLISH": 2
        }

        for sector in curr_sec.index:
            if sector not in prev_sec.index:
                continue
            prev_bias = prev_sec.loc[sector, "BIAS"]
            curr_bias = curr_sec.loc[sector, "BIAS"]
            if prev_bias != curr_bias:
                prev_rank = bias_rank.get(prev_bias, 0)
                curr_rank = bias_rank.get(curr_bias, 0)
                direction = "↑" if curr_rank > prev_rank else "↓"
                sector_rotations.append({
                    "SECTOR":     sector,
                    "PREV_BIAS":  prev_bias,
                    "CURR_BIAS":  curr_bias,
                    "DIRECTION":  direction,
                })
                logger.info(f"  SECTOR ROTATION: {sector} {prev_bias} → {curr_bias} {direction}")

    if not sector_rotations:
        logger.info("  No sector rotations today")

    # ── Step 7: Print summary ────────────────────────
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"RESULTS — {trade_date.strftime('%d %b %Y')}")
    logger.info(f"Market Bias: {macro.get('market_bias', 'N/A')} | "
                f"FII Fut Net: {macro.get('fii_index_fut_net', 0):,.0f}")
    logger.info("-" * 60)
    logger.info("TOP 10 LONG CANDIDATES:")
    for _, row in top_longs.iterrows():
        bb  = row.get("BB_SIGNAL", "N/A")
        bo  = row.get("BREAKOUT_SIGNAL", "N/A")
        sq  = " [SQZ]" if row.get("BB_SQUEEZE") else ""
        pcr = f"{row.get('PCR', 'N/A')}" if row.get("PCR") else "N/A"
        rs  = f"{row.get('RS_SIGNAL','N/A')}({row.get('RS_PCT','?'):.0f}%)" if row.get("RS_PCT") is not None else "N/A"
        logger.info(
            f"  {row['SYMBOL']:<15} Score={row['COMPOSITE_SCORE']:+4d} "
            f"(T:{row['TECHNICAL_SCORE']:+3d} F:{row['FO_SCORE']:+2d} RS:{row.get('RS_SCORE',0):+2d}) "
            f"| {row['SIGNAL']:<15} | {row.get('OI_SIGNAL', 'N/A'):<18} "
            f"| BB:{bb}{sq} | BO:{bo} | PCR:{pcr} | RS:{rs}"
        )
    logger.info("-" * 60)
    logger.info("TOP 10 SHORT CANDIDATES:")
    for _, row in top_shorts.iterrows():
        bb  = row.get("BB_SIGNAL", "N/A")
        bo  = row.get("BREAKOUT_SIGNAL", "N/A")
        sq  = " [SQZ]" if row.get("BB_SQUEEZE") else ""
        pcr = f"{row.get('PCR', 'N/A')}" if row.get("PCR") else "N/A"
        rs  = f"{row.get('RS_SIGNAL','N/A')}({row.get('RS_PCT','?'):.0f}%)" if row.get("RS_PCT") is not None else "N/A"
        logger.info(
            f"  {row['SYMBOL']:<15} Score={row['COMPOSITE_SCORE']:+4d} "
            f"(T:{row['TECHNICAL_SCORE']:+3d} F:{row['FO_SCORE']:+2d} RS:{row.get('RS_SCORE',0):+2d}) "
            f"| {row['SIGNAL']:<15} | {row.get('OI_SIGNAL', 'N/A'):<18} "
            f"| BB:{bb}{sq} | BO:{bo} | PCR:{pcr} | RS:{rs}"
        )
    logger.info("-" * 60)
    logger.info(f"OI ALERTS: {len(oi_alerts)} stocks with OI change >{OI_ALERT_THRESHOLD}%")
    if not oi_alerts.empty:
        for _, row in oi_alerts.head(10).iterrows():
            severity = row.get("ALERT_SEVERITY", "")
            label    = row.get("ALERT_LABEL", "")
            logger.info(
                f"  {row['SYMBOL']:<15} OI%={row['OI_CHANGE_PCT']:+.1f}% "
                f"| {severity:<8} | {label}"
            )
    logger.info("-" * 60)
    logger.info("SECTOR SUMMARY:")
    for _, row in sector_summary.iterrows():
        bar_l = "L" * row["LONGS"]
        bar_s = "S" * row["SHORTS"]
        logger.info(
            f"  {row['SECTOR']:<18} Avg={row['AVG_SCORE']:+5.1f} "
            f"| L:{row['LONGS']:2d} S:{row['SHORTS']:2d} N:{row['NEUTRAL']:2d} "
            f"| {row['BIAS']:<14} {bar_l}{bar_s}"
        )
    logger.info("-" * 60)
    if sector_rotations:
        logger.info(f"SECTOR ROTATIONS ({len(sector_rotations)} today):")
        for r in sector_rotations:
            logger.info(f"  {r['SECTOR']:<18} {r['PREV_BIAS']:<14} → {r['CURR_BIAS']:<14} {r['DIRECTION']}")
    else:
        logger.info("SECTOR ROTATIONS: None today")
    logger.info("-" * 60)
    if len(persistence) > 0:
        logger.info(f"PERSISTENT SIGNALS (3+ consecutive days):")
        if not persistent_longs.empty:
            logger.info("  LONGS:")
            for _, row in persistent_longs.iterrows():
                logger.info(
                    f"    {row['SYMBOL']:<15} [P{int(row['PERSISTENCE'])}d] "
                    f"Score={row['COMPOSITE_SCORE']:+4d} | {row['SIGNAL']}"
                )
        if not persistent_shorts.empty:
            logger.info("  SHORTS:")
            for _, row in persistent_shorts.iterrows():
                logger.info(
                    f"    {row['SYMBOL']:<15} [P{int(row['PERSISTENCE'])}d] "
                    f"Score={row['COMPOSITE_SCORE']:+4d} | {row['SIGNAL']}"
                )
    else:
        logger.info("PERSISTENT SIGNALS: None yet — need 3+ days of history")
    logger.info("=" * 60)

    return {
        "trade_date": trade_date.strftime("%d %b %Y"),
        "trade_date_obj": trade_date,
        "macro": macro,
        "full_universe": df_results,
        "top_longs": top_longs,
        "top_shorts": top_shorts,
        "oi_alerts": oi_alerts,
        "sector_summary": sector_summary,
        "persistent_longs": persistent_longs,
        "persistent_shorts": persistent_shorts,
        "persistence": persistence,
        "sector_rotations": sector_rotations,
    }


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="F&O Morning Screener")
    parser.add_argument("--date", help="Trade date YYYY-MM-DD (default: last trading day)")
    args = parser.parse_args()

    if args.date:
        try:
            td = date.fromisoformat(args.date)
        except ValueError:
            logger.error(f"Invalid date format: {args.date}. Use YYYY-MM-DD")
            sys.exit(1)
    else:
        td = last_trading_day()

    try:
        results = run_screener(td)
        # Save results to JSON for other scripts to consume
        output_json = f"logs/screener_results_{td.strftime('%Y%m%d')}.json"
        with open(output_json, "w") as f:
            serializable = {
                "trade_date": results["trade_date"],
                "macro": {k: v for k, v in results["macro"].items() if k != "raw_data"},
                "top_longs": results["top_longs"].fillna("").to_dict(orient="records"),
                "top_shorts": results["top_shorts"].fillna("").to_dict(orient="records"),
                "oi_alerts": results["oi_alerts"].fillna("").to_dict(orient="records"),
                "sector_summary": results["sector_summary"].fillna("").to_dict(orient="records"),
                "persistent_longs": results["persistent_longs"].fillna("").to_dict(orient="records"),
                "persistent_shorts": results["persistent_shorts"].fillna("").to_dict(orient="records"),
                "sector_rotations": results.get("sector_rotations", []),
                "full_universe": results["full_universe"].fillna("").to_dict(orient="records"),
            }
            json.dump(serializable, f, indent=2, default=str)
        logger.info(f"JSON results saved: {output_json}")
    except Exception as e:
        logger.error(f"Screener failed: {e}", exc_info=True)
        sys.exit(1)
