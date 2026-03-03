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

from config import (
    FO_STOCKS, NSE_MONTH_ABBR, NSE_HOLIDAYS,
    NSE_FO_BHAVCOPY_URL, NSE_CM_BHAVCOPY_URL, NSE_PARTICIPANT_OI_URL,
    NSE_HEADERS, MAX_RETRIES, RETRY_DELAY_SECONDS, REQUEST_TIMEOUT,
    EMA_SHORT, EMA_MID, EMA_LONG, RSI_PERIOD, ADX_PERIOD,
    SUPERTREND_PERIOD, SUPERTREND_MULTIPLIER,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL, VOLUME_MA_PERIOD,
    RSI_BULL_LOW, RSI_BULL_HIGH, RSI_BEAR_LOW, RSI_BEAR_HIGH,
    ADX_TREND_THRESHOLD, VOLUME_HIGH_RATIO, VOLUME_LOW_RATIO,
    OI_CHANGE_MEDIUM, OI_CHANGE_HIGH, OI_ALERT_THRESHOLD,
    DELIVERY_HIGH, DELIVERY_LOW,
    STRONG_LONG_THRESHOLD, LONG_THRESHOLD, SHORT_THRESHOLD, STRONG_SHORT_THRESHOLD,
    YFINANCE_PERIOD, YFINANCE_INTERVAL, YFINANCE_SUFFIX,
    YFINANCE_BATCH_SIZE, YFINANCE_BATCH_DELAY,
    LOGS_DIR, OUTPUT_CSV,
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

def parse_fo_bhavcopy(df: pd.DataFrame, trade_date: date) -> pd.DataFrame:
    """UDiFF format: STF=Stock Futures, TCKRSYMB, XPRYDT, STTLMPRIC, OPNINTRST"""
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

    # Pick ONE column per field by priority
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

    # Build clean single-column dataframe — no duplicate column names
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
    else:
        cc = fut2.copy()

    if cc.empty:
        logger.warning("No contracts after expiry filter!")
        return pd.DataFrame()

    agg = cc.groupby("SYMBOL").agg(FO_CLOSE=("CLOSE", "last"), OI=("OI", "sum")).reset_index()

    if "PREV_CLOSE" in cc.columns:
        agg = agg.merge(cc.groupby("SYMBOL").agg(FO_PREV_CLOSE=("PREV_CLOSE", "last")).reset_index(), on="SYMBOL", how="left")

    if "OI_CHANGE_ABS" in cc.columns:
        agg = agg.merge(cc.groupby("SYMBOL").agg(OI_CHANGE_ABS=("OI_CHANGE_ABS", "sum")).reset_index(), on="SYMBOL", how="left")
        agg["OI_PREV"] = agg["OI"] - agg["OI_CHANGE_ABS"]
    else:
        agg["OI_PREV"] = np.nan
        agg["OI_CHANGE_ABS"] = np.nan

    agg["OI_CHANGE_PCT"] = np.where(
        agg["OI_PREV"].notna() & (agg["OI_PREV"] != 0),
        ((agg["OI"] - agg["OI_PREV"]) / agg["OI_PREV"]) * 100, np.nan)

    logger.info(f"Parsed {len(agg)} stocks from F&O bhavcopy")
    return agg

    agg = current_contracts.groupby("SYMBOL").agg(**agg_dict).reset_index()

    if "PREV_CLOSE" in current_contracts.columns:
        prev = current_contracts.groupby("SYMBOL").agg(
            FO_PREV_CLOSE=("PREV_CLOSE", "last")
        ).reset_index()
        agg = agg.merge(prev, on="SYMBOL", how="left")

    if "OI_CHANGE_ABS" in current_contracts.columns:
        oi_chg = current_contracts.groupby("SYMBOL").agg(
            OI_CHANGE_ABS=("OI_CHANGE_ABS", "sum")
        ).reset_index()
        agg = agg.merge(oi_chg, on="SYMBOL", how="left")
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
    UDiFF format: TCKRSYMB, SCTYSRS, CLSPRIC, PRVSCLSGPRIC, etc.
    """
    logger.info(f"CM Bhavcopy columns: {list(df.columns)}")

    col_map = {}
    for c in df.columns:
        cu = c.upper().strip()
        if cu in ("TCKRSYMB", "SYMBOL", "SYMBOLNAME"):
            col_map[c] = "SYMBOL"
        elif cu in ("SCTYSRS", "SRIESSRS", "SERIES"):
            col_map[c] = "SERIES"
        elif cu == "STTLMPRIC":
            col_map[c] = "CM_CLOSE"
        elif cu in ("CLSPRIC", "LASTPRIC") and "CM_CLOSE" not in col_map.values():
            col_map[c] = "CM_CLOSE"
        elif cu in ("PRVSCLSGPRIC", "PREVCLOSE", "PREV_CLOSE"):
            col_map[c] = "CM_PREV_CLOSE"
        elif cu in ("DLVRYQTYPCTGOFTRADGQTY", "DELIV_PER", "DELIVERY_PCT"):
            col_map[c] = "DELIVERY_PCT"
        elif cu in ("DLVRYQTY", "DELIVERYQTY", "DELIV_QTY"):
            col_map[c] = "DELIVERY_QTY"
        elif cu in ("TTLTRADGVOL", "TTL_TRD_QNTY", "TOTTRDQTY"):
            col_map[c] = "TOTAL_QTY"

    df2 = df.rename(columns=col_map)

    # Keep EQ series only
    if "SERIES" in df2.columns:
        df2 = df2[df2["SERIES"].astype(str).str.strip().str.upper() == "EQ"].copy()

    # Compute delivery % if not present
    if "DELIVERY_PCT" not in df2.columns:
        if "DELIVERY_QTY" in df2.columns and "TOTAL_QTY" in df2.columns:
            df2["DELIVERY_PCT"] = (
                pd.to_numeric(df2["DELIVERY_QTY"].astype(str), errors="coerce") /
                pd.to_numeric(df2["TOTAL_QTY"].astype(str), errors="coerce") * 100
            )

    # Convert numeric columns
    for num_col in ("CM_CLOSE", "CM_PREV_CLOSE", "DELIVERY_PCT"):
        if num_col in df2.columns:
            df2[num_col] = pd.to_numeric(df2[num_col].astype(str), errors="coerce")

    keep = ["SYMBOL", "CM_CLOSE", "CM_PREV_CLOSE", "DELIVERY_PCT"]
    existing = [c for c in keep if c in df2.columns]
    df2 = df2[existing].copy()

    # Deduplicate — UDiFF may have multiple session rows per symbol
    if "SYMBOL" in df2.columns:
        df2 = df2.drop_duplicates(subset="SYMBOL", keep="last").reset_index(drop=True)

    logger.info(f"CM bhavcopy parsed: {len(df2)} EQ rows, columns: {existing}")
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

    indicators["PRICE"] = round(last_close, 2)
    indicators["PRICE_CHANGE_PCT"] = round(
        (last_close - close.iloc[-2]) / close.iloc[-2] * 100, 2
    ) if len(close) > 1 else 0

    return {
        "technical_score": score,
        "indicators": indicators,
        "components": components,
        "ema_signal": ema_signal,
    }


# ─────────────────────────────────────────────
# F&O SCORING
# ─────────────────────────────────────────────

def calculate_fo_score(fo_row: pd.Series, cm_row: pd.Series) -> dict:
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

    return {
        "fo_score": score,
        "fo_components": components,
        "oi_signal": oi_signal,
        "oi_change_pct": round(float(oi_chg_pct), 2) if not pd.isna(oi_chg_pct) else None,
        "delivery_pct": round(delivery_pct, 1) if not pd.isna(delivery_pct) else None,
    }


# ─────────────────────────────────────────────
# COMPOSITE SCORING & CLASSIFICATION
# ─────────────────────────────────────────────

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
    macro   = parse_participant_oi(poi_raw) if poi_raw is not None else {}

    # Create lookup dicts — deduplicate first to avoid index errors
    if not fo_data.empty and "SYMBOL" in fo_data.columns:
        fo_data = fo_data.drop_duplicates(subset="SYMBOL", keep="last").reset_index(drop=True)
        fo_lookup = fo_data.set_index("SYMBOL").to_dict(orient="index")
    else:
        fo_lookup = {}

    if not cm_data.empty and "SYMBOL" in cm_data.columns:
        cm_data = cm_data.drop_duplicates(subset="SYMBOL", keep="last").reset_index(drop=True)
        cm_lookup = cm_data.set_index("SYMBOL").to_dict(orient="index")
    else:
        cm_lookup = {}

    # ── Step 3: Fetch OHLCV data ─────────────────────
    logger.info(f"STEP 3: Fetching OHLCV for {len(FO_STOCKS)} stocks via yfinance...")
    ohlcv_data = fetch_ohlcv_batch(FO_STOCKS)
    logger.info(f"  Got data for {len(ohlcv_data)} stocks")

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
            fo = calculate_fo_score(fo_row, cm_row)

            tech_score = tech["technical_score"] if tech else 0
            fo_score   = fo["fo_score"]
            composite  = tech_score + fo_score

            row = {
                "SYMBOL": symbol,
                "COMPOSITE_SCORE": composite,
                "TECHNICAL_SCORE": tech_score,
                "FO_SCORE": fo_score,
                "SIGNAL": classify_signal(composite),
                "OI_SIGNAL": fo.get("oi_signal", "N/A"),
                "OI_CHANGE_PCT": fo.get("oi_change_pct"),
                "DELIVERY_PCT": fo.get("delivery_pct"),
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
            }
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

    top_longs  = df_results[df_results["COMPOSITE_SCORE"] >= LONG_THRESHOLD].head(10)
    top_shorts = df_results[df_results["COMPOSITE_SCORE"] <= SHORT_THRESHOLD].tail(10).iloc[::-1]
    oi_alerts  = df_results[
        df_results["OI_CHANGE_PCT"].notna() &
        (df_results["OI_CHANGE_PCT"].abs() >= OI_ALERT_THRESHOLD)
    ].copy()

    # Alert severity
    if not oi_alerts.empty:
        oi_alerts["ALERT_SEVERITY"] = oi_alerts["OI_CHANGE_PCT"].abs().apply(
            lambda x: "HIGH" if x >= 30 else "MEDIUM"
        )

    # ── Step 6: Save output ──────────────────────────
    output_path = OUTPUT_CSV.format(date=trade_date.strftime("%Y%m%d"))
    df_results.to_csv(output_path, index=False)
    logger.info(f"Output saved: {output_path}")

    # ── Step 7: Print summary ────────────────────────
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"RESULTS — {trade_date.strftime('%d %b %Y')}")
    logger.info(f"Market Bias: {macro.get('market_bias', 'N/A')} | "
                f"FII Fut Net: {macro.get('fii_index_fut_net', 0):,.0f}")
    logger.info("-" * 60)
    logger.info("TOP 10 LONG CANDIDATES:")
    for _, row in top_longs.iterrows():
        logger.info(
            f"  {row['SYMBOL']:<15} Score={row['COMPOSITE_SCORE']:+4d} "
            f"(T:{row['TECHNICAL_SCORE']:+3d} F:{row['FO_SCORE']:+2d}) "
            f"| {row['SIGNAL']:<15} | {row.get('OI_SIGNAL', 'N/A')}"
        )
    logger.info("-" * 60)
    logger.info("TOP 10 SHORT CANDIDATES:")
    for _, row in top_shorts.iterrows():
        logger.info(
            f"  {row['SYMBOL']:<15} Score={row['COMPOSITE_SCORE']:+4d} "
            f"(T:{row['TECHNICAL_SCORE']:+3d} F:{row['FO_SCORE']:+2d}) "
            f"| {row['SIGNAL']:<15} | {row.get('OI_SIGNAL', 'N/A')}"
        )
    logger.info("-" * 60)
    logger.info(f"OI ALERTS: {len(oi_alerts)} stocks with OI change >{OI_ALERT_THRESHOLD}%")
    logger.info("=" * 60)

    return {
        "trade_date": trade_date.strftime("%d %b %Y"),
        "trade_date_obj": trade_date,
        "macro": macro,
        "full_universe": df_results,
        "top_longs": top_longs,
        "top_shorts": top_shorts,
        "oi_alerts": oi_alerts,
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
                "full_universe": results["full_universe"].fillna("").to_dict(orient="records"),
            }
            json.dump(serializable, f, indent=2, default=str)
        logger.info(f"JSON results saved: {output_json}")
    except Exception as e:
        logger.error(f"Screener failed: {e}", exc_info=True)
        sys.exit(1)
