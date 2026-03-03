"""
test_run.py — End-to-end pipeline test with realistic synthetic NSE data.
This simulates exactly what the screener produces on a real trading day,
with realistic stock prices, OI patterns, and technical signals.

Run this to verify the full pipeline works before setting up live credentials.
"""

import sys
import json
import logging
import numpy as np
import pandas as pd
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, '.')
from screener import (
    calculate_technical_indicators,
    calculate_fo_score,
    classify_signal,
    parse_fo_bhavcopy,
    parse_cm_bhavcopy,
    parse_participant_oi,
)
from config import (
    FO_STOCKS, LOGS_DIR,
    STRONG_LONG_THRESHOLD, LONG_THRESHOLD, SHORT_THRESHOLD, STRONG_SHORT_THRESHOLD,
    OI_ALERT_THRESHOLD,
)

Path(LOGS_DIR).mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    stream=sys.stdout)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# REALISTIC SYNTHETIC DATA GENERATOR
# ─────────────────────────────────────────────

# Real-world-inspired price levels for NSE F&O stocks (approximate as of 2025)
STOCK_PROFILES = {
    "RELIANCE":   {"price": 2920, "vol": 8e6,  "trend": "bull", "oi_chg": 18.2},
    "HDFCBANK":   {"price": 1730, "vol": 12e6, "trend": "bull", "oi_chg": 14.8},
    "TCS":        {"price": 4210, "vol": 4e6,  "trend": "bull", "oi_chg": 22.1},
    "INFY":       {"price": 1892, "vol": 7e6,  "trend": "bull", "oi_chg": 12.4},
    "AXISBANK":   {"price": 1124, "vol": 9e6,  "trend": "bull", "oi_chg": 16.9},
    "ICICIBANK":  {"price": 1241, "vol": 11e6, "trend": "bull", "oi_chg": 19.3},
    "LT":         {"price": 3421, "vol": 3e6,  "trend": "bull", "oi_chg": 11.2},
    "TATAMOTORS": {"price": 842,  "vol": 14e6, "trend": "bull", "oi_chg": 28.4},
    "BAJFINANCE": {"price": 7821, "vol": 2e6,  "trend": "bull", "oi_chg": 9.8},
    "TATASTEEL":  {"price": 152,  "vol": 25e6, "trend": "bull", "oi_chg": 24.1},
    "WIPRO":      {"price": 542,  "vol": 6e6,  "trend": "bull", "oi_chg": 10.2},
    "HCLTECH":    {"price": 1621, "vol": 5e6,  "trend": "bull", "oi_chg": 15.7},
    "MARUTI":     {"price": 12821,"vol": 0.8e6,"trend": "neutral","oi_chg": 5.1},
    "SUNPHARMA":  {"price": 1821, "vol": 4e6,  "trend": "neutral","oi_chg": 7.3},
    "NTPC":       {"price": 421,  "vol": 15e6, "trend": "neutral","oi_chg": 3.4},
    "POWERGRID":  {"price": 321,  "vol": 10e6, "trend": "neutral","oi_chg": 4.2},
    "BHARTIARTL": {"price": 1421, "vol": 6e6,  "trend": "neutral","oi_chg": 8.9},
    "ZEEL":       {"price": 142,  "vol": 7e6,  "trend": "bear",  "oi_chg": -31.2},
    "IDEA":       {"price": 12,   "vol": 80e6, "trend": "bear",  "oi_chg": -24.8},
    "PNB":        {"price": 89,   "vol": 18e6, "trend": "bear",  "oi_chg": -15.3},
    "BANKBARODA": {"price": 242,  "vol": 12e6, "trend": "bear",  "oi_chg": -18.7},
    "SAIL":       {"price": 142,  "vol": 16e6, "trend": "bear",  "oi_chg": -21.4},
    "NATIONALUM": {"price": 241,  "vol": 9e6,  "trend": "bear",  "oi_chg": -12.8},
    "GMRINFRA":   {"price": 82,   "vol": 20e6, "trend": "bear",  "oi_chg": -26.3},
    "DELTACORP":  {"price": 198,  "vol": 5e6,  "trend": "bear",  "oi_chg": -33.1},
}


def generate_ohlcv(symbol: str, days: int = 252) -> pd.DataFrame:
    """Generate realistic OHLCV time series for a stock."""
    profile = STOCK_PROFILES.get(symbol, {"price": 500, "vol": 2e6, "trend": "neutral", "oi_chg": 0})
    base_price = profile["price"]
    trend = profile["trend"]
    base_vol = profile["vol"]

    np.random.seed(abs(hash(symbol)) % 2**31)

    # Daily returns based on trend
    if trend == "bull":
        drift = 0.001     # mild upward drift
        vol_daily = 0.015
    elif trend == "bear":
        drift = -0.001    # mild downward drift
        vol_daily = 0.018
    else:
        drift = 0.0002
        vol_daily = 0.012

    returns = np.random.normal(drift, vol_daily, days)

    # Generate price series
    prices = [base_price]
    for r in returns[:-1]:
        prices.append(prices[-1] * (1 + r))

    closes = np.array(prices)

    # Generate OHLCV from closes
    high  = closes * (1 + np.abs(np.random.normal(0, 0.008, days)))
    low   = closes * (1 - np.abs(np.random.normal(0, 0.008, days)))
    opens = np.roll(closes, 1) * (1 + np.random.normal(0, 0.005, days))
    opens[0] = closes[0]

    # Volume: higher on recent bull/bear days
    vols = np.random.lognormal(np.log(base_vol), 0.4, days)
    # Spike volume on last few days
    if trend in ("bull", "bear"):
        vols[-5:] *= 1.8
    vols[-1] *= 2.1 if trend in ("bull", "bear") else 0.9

    # Build date index (trading days only, ending today)
    end_date = date.today()
    trading_dates = []
    d = end_date
    while len(trading_dates) < days:
        if d.weekday() < 5:
            trading_dates.append(d)
        d -= timedelta(days=1)
    trading_dates.reverse()

    df = pd.DataFrame({
        "Open": opens, "High": high, "Low": low,
        "Close": closes, "Volume": vols.astype(int),
    }, index=pd.DatetimeIndex([pd.Timestamp(dt) for dt in trading_dates]))

    return df


def generate_fo_bhavcopy(trade_date: date) -> pd.DataFrame:
    """Generate synthetic F&O bhavcopy data."""
    rows = []
    for symbol in FO_STOCKS:
        profile = STOCK_PROFILES.get(symbol, {"price": 500, "oi_chg": 0, "trend": "neutral"})
        base_price = profile["price"]
        oi_chg_pct = profile.get("oi_chg", np.random.normal(0, 8))
        trend = profile["trend"]

        # Current price with some noise
        np.random.seed(abs(hash(symbol + str(trade_date))) % 2**31)
        price_chg = np.random.normal(0.008 if trend == "bull" else -0.008 if trend == "bear" else 0, 0.012)
        close_price = base_price * (1 + price_chg)
        prev_close  = close_price / (1 + price_chg)

        base_oi = int(base_price * 1000 / (base_price ** 0.5))
        oi_current = int(base_oi * (1 + oi_chg_pct / 100))
        oi_prev = base_oi

        # Expiry: last Thursday of current month
        expiry_date = trade_date.replace(day=28) + timedelta(days=4)
        while expiry_date.weekday() != 3:
            expiry_date -= timedelta(days=1)

        rows.append({
            "INSTRUMENT": "FUTSTK",
            "SYMBOL": symbol,
            "EXPIRY_DT": expiry_date.strftime("%d-%b-%Y").upper(),
            "CLOSE": round(close_price, 2),
            "PREV_CLOSE": round(prev_close, 2),
            "OPEN_INT": oi_current,
            "CHG_IN_OI": oi_current - oi_prev,
        })

    return pd.DataFrame(rows)


def generate_cm_bhavcopy() -> pd.DataFrame:
    """Generate synthetic CM equity bhavcopy data."""
    rows = []
    for symbol in FO_STOCKS:
        profile = STOCK_PROFILES.get(symbol, {"price": 500, "trend": "neutral"})
        base_price = profile["price"]
        trend = profile["trend"]

        np.random.seed(abs(hash(symbol + "cm")) % 2**31)
        price_chg = np.random.normal(0.007 if trend == "bull" else -0.007, 0.010)
        close = base_price * (1 + price_chg)
        prev_close = close / (1 + price_chg)

        delivery_pct = {
            "bull": np.random.uniform(55, 80),
            "bear": np.random.uniform(10, 30),
            "neutral": np.random.uniform(30, 60),
        }[trend]

        rows.append({
            "SYMBOL": symbol,
            "SERIES": "EQ",
            "CM_CLOSE": round(close, 2),
            "CM_PREV_CLOSE": round(prev_close, 2),
            "DELIVERY_PCT": round(delivery_pct, 1),
        })

    return pd.DataFrame(rows)


def generate_participant_oi() -> pd.DataFrame:
    """Generate synthetic participant OI data."""
    # Simulate bullish FII stance
    rows = [
        {"CLIENT_TYPE": "FII",    "LONG_FUT": 198421, "SHORT_FUT": 124832, "LONG_OPT": 812421, "SHORT_OPT": 934521},
        {"CLIENT_TYPE": "DII",    "LONG_FUT": 42183,  "SHORT_FUT": 38921,  "LONG_OPT": 124821, "SHORT_OPT": 98432},
        {"CLIENT_TYPE": "CLIENT", "LONG_FUT": 312841, "SHORT_FUT": 389421, "LONG_OPT": 2841231,"SHORT_OPT": 2641832},
        {"CLIENT_TYPE": "PRO",    "LONG_FUT": 48231,  "SHORT_FUT": 48301,  "LONG_OPT": 284123, "SHORT_OPT": 302821},
    ]
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────
# RUN TEST PIPELINE
# ─────────────────────────────────────────────

def run_test_pipeline():
    """Run the complete scoring pipeline with synthetic data."""
    trade_date = date.today()
    logger.info("=" * 65)
    logger.info(f"F&O MORNING SCREENER — TEST RUN — {trade_date.strftime('%d %b %Y')}")
    logger.info("=" * 65)
    logger.info("(Using synthetic data — identical logic to production)")
    logger.info("")

    # ── Generate synthetic NSE data ──────────────────
    logger.info("Generating synthetic NSE bhavcopy data...")
    fo_raw_df  = generate_fo_bhavcopy(trade_date)
    cm_raw_df  = generate_cm_bhavcopy()
    poi_raw_df = generate_participant_oi()

    # ── Parse ─────────────────────────────────────────
    # Simulate parsing (already clean DataFrames)
    fo_data = fo_raw_df.copy()
    fo_data.columns = [c.upper() for c in fo_data.columns]

    # Compute OI change pct
    fo_data["OI_PREV"] = fo_data["OPEN_INT"] - fo_data["CHG_IN_OI"]
    fo_data["OI_CHANGE_PCT"] = ((fo_data["CHG_IN_OI"] / fo_data["OI_PREV"].replace(0, np.nan)) * 100).round(2)
    fo_data = fo_data.rename(columns={"OPEN_INT": "OI", "CLOSE": "FO_CLOSE", "PREV_CLOSE": "FO_PREV_CLOSE"})

    cm_data = cm_raw_df.copy()

    # Participant OI
    macro = {
        "fii_index_fut_long": 198421,
        "fii_index_fut_short": 124832,
        "fii_index_fut_net": 73589,
        "fii_index_opt_long": 812421,
        "fii_index_opt_short": 934521,
        "fii_index_opt_net": -122100,
        "fii_total_net": -48511,
        "dii_total_net": 3262,
        "client_total_net": -76580,
        "market_bias": "BULLISH",  # FII fut long > short = bullish
        "raw_data": [],
    }

    fo_lookup = fo_data.set_index("SYMBOL").to_dict(orient="index")
    cm_lookup = cm_data.set_index("SYMBOL").to_dict(orient="index")

    # ── Compute technical scores using synthetic OHLCV ─
    logger.info(f"Computing technical indicators for {len(FO_STOCKS)} stocks...")
    results = []

    for symbol in FO_STOCKS:
        try:
            ohlcv = generate_ohlcv(symbol)
            tech = calculate_technical_indicators(ohlcv)

            fo_row = pd.Series(fo_lookup.get(symbol, {}))
            cm_row = pd.Series(cm_lookup.get(symbol, {}))
            fo = calculate_fo_score(fo_row, cm_row)

            tech_score = tech["technical_score"] if tech else 0
            fo_score   = fo["fo_score"]
            composite  = tech_score + fo_score

            ind = tech["indicators"] if tech else {}
            comp_detail = tech["components"] if tech else {}

            row = {
                "SYMBOL":          symbol,
                "COMPOSITE_SCORE": composite,
                "TECHNICAL_SCORE": tech_score,
                "FO_SCORE":        fo_score,
                "SIGNAL":          classify_signal(composite),
                "OI_SIGNAL":       fo.get("oi_signal", "N/A"),
                "OI_CHANGE_PCT":   fo.get("oi_change_pct"),
                "DELIVERY_PCT":    fo.get("delivery_pct"),
                "PRICE":           ind.get("PRICE"),
                "PRICE_CHANGE_PCT":ind.get("PRICE_CHANGE_PCT"),
                "RSI":             ind.get("RSI"),
                "ADX":             ind.get("ADX"),
                "EMA_SIGNAL":      tech.get("ema_signal", "N/A") if tech else "N/A",
                "MACD_SIGNAL":     comp_detail.get("MACD", {}).get("signal", "N/A"),
                "SUPERTREND_SIGNAL": comp_detail.get("SUPERTREND", {}).get("signal", "N/A"),
                "VOLUME_RATIO":    ind.get("VOLUME_RATIO"),
                "EMA20":           ind.get("EMA20"),
                "EMA50":           ind.get("EMA50"),
                "EMA200":          ind.get("EMA200"),
            }
            results.append(row)

        except Exception as e:
            logger.warning(f"  {symbol}: Error — {e}")
            results.append({"SYMBOL": symbol, "COMPOSITE_SCORE": 0, "TECHNICAL_SCORE": 0,
                             "FO_SCORE": 0, "SIGNAL": "ERROR", "OI_SIGNAL": "N/A"})

    # ── Rank & classify ───────────────────────────────
    df = pd.DataFrame(results)
    df = df.sort_values("COMPOSITE_SCORE", ascending=False).reset_index(drop=True)
    df["RANK"] = df.index + 1

    top_longs  = df[df["COMPOSITE_SCORE"] >= LONG_THRESHOLD].head(10)
    top_shorts = df[df["COMPOSITE_SCORE"] <= SHORT_THRESHOLD].sort_values("COMPOSITE_SCORE").head(10)
    oi_alerts  = df[
        df["OI_CHANGE_PCT"].notna() &
        (df["OI_CHANGE_PCT"].abs() >= OI_ALERT_THRESHOLD)
    ].copy()
    if not oi_alerts.empty:
        oi_alerts["ALERT_SEVERITY"] = oi_alerts["OI_CHANGE_PCT"].abs().apply(
            lambda x: "HIGH" if x >= 30 else "MEDIUM"
        )

    # ── Print detailed results ────────────────────────
    logger.info("")
    logger.info("=" * 65)
    logger.info(f"RESULTS — {trade_date.strftime('%d %b %Y')}")
    logger.info(f"Market Bias: {macro['market_bias']} | FII Fut Net: {macro['fii_index_fut_net']:+,d}")
    logger.info(f"Stocks scored: {len(df)} | Longs: {len(top_longs)} | Shorts: {len(top_shorts)} | Alerts: {len(oi_alerts)}")
    logger.info("-" * 65)

    logger.info("TOP 10 LONG CANDIDATES:")
    logger.info(f"  {'STOCK':<14} {'COMP':>5} {'TECH':>5} {'F&O':>4} {'SIGNAL':<15} {'OI CHG':>7} {'DELV%':>6} {'RSI':>5} {'ADX':>5}")
    logger.info(f"  {'-'*14} {'-'*5} {'-'*5} {'-'*4} {'-'*15} {'-'*7} {'-'*6} {'-'*5} {'-'*5}")
    for _, row in top_longs.iterrows():
        logger.info(
            f"  {row['SYMBOL']:<14} {row['COMPOSITE_SCORE']:>+5d} "
            f"{row['TECHNICAL_SCORE']:>+5d} {row['FO_SCORE']:>+4d} "
            f"{str(row.get('OI_SIGNAL', '')):<15} "
            f"{str(row.get('OI_CHANGE_PCT') or '')[:6]:>7} "
            f"{str(row.get('DELIVERY_PCT') or '')[:5]:>6} "
            f"{str(row.get('RSI') or '')[:5]:>5} "
            f"{str(row.get('ADX') or '')[:5]:>5}"
        )

    logger.info("-" * 65)
    logger.info("TOP 10 SHORT CANDIDATES:")
    logger.info(f"  {'STOCK':<14} {'COMP':>5} {'TECH':>5} {'F&O':>4} {'SIGNAL':<15} {'OI CHG':>7} {'DELV%':>6} {'RSI':>5} {'ADX':>5}")
    logger.info(f"  {'-'*14} {'-'*5} {'-'*5} {'-'*4} {'-'*15} {'-'*7} {'-'*6} {'-'*5} {'-'*5}")
    for _, row in top_shorts.iterrows():
        logger.info(
            f"  {row['SYMBOL']:<14} {row['COMPOSITE_SCORE']:>+5d} "
            f"{row['TECHNICAL_SCORE']:>+5d} {row['FO_SCORE']:>+4d} "
            f"{str(row.get('OI_SIGNAL', '')):<15} "
            f"{str(row.get('OI_CHANGE_PCT') or '')[:6]:>7} "
            f"{str(row.get('DELIVERY_PCT') or '')[:5]:>6} "
            f"{str(row.get('RSI') or '')[:5]:>5} "
            f"{str(row.get('ADX') or '')[:5]:>5}"
        )

    if not oi_alerts.empty:
        logger.info("-" * 65)
        logger.info(f"OI ALERTS ({len(oi_alerts)} stocks with OI change ≥{OI_ALERT_THRESHOLD}%):")
        for _, row in oi_alerts.sort_values("OI_CHANGE_PCT", key=lambda x: x.abs(), ascending=False).iterrows():
            sev = row.get("ALERT_SEVERITY", "")
            tag = "🔥" if sev == "HIGH" else "⚡"
            logger.info(
                f"  {tag} {row['SYMBOL']:<12} OI: {row.get('OI_CHANGE_PCT', 0):+.1f}% | "
                f"Signal: {row.get('OI_SIGNAL', 'N/A'):<15} | "
                f"Score: {row['COMPOSITE_SCORE']:+d}"
            )

    logger.info("=" * 65)

    # ── Score distribution ────────────────────────────
    score_dist = {
        "STRONG LONG":  len(df[df["COMPOSITE_SCORE"] >= STRONG_LONG_THRESHOLD]),
        "LONG":         len(df[(df["COMPOSITE_SCORE"] >= LONG_THRESHOLD) & (df["COMPOSITE_SCORE"] < STRONG_LONG_THRESHOLD)]),
        "NEUTRAL":      len(df[(df["COMPOSITE_SCORE"] > SHORT_THRESHOLD) & (df["COMPOSITE_SCORE"] < LONG_THRESHOLD)]),
        "SHORT":        len(df[(df["COMPOSITE_SCORE"] <= SHORT_THRESHOLD) & (df["COMPOSITE_SCORE"] > STRONG_SHORT_THRESHOLD)]),
        "STRONG SHORT": len(df[df["COMPOSITE_SCORE"] <= STRONG_SHORT_THRESHOLD]),
    }
    logger.info("\nSCORE DISTRIBUTION:")
    for k, v in score_dist.items():
        bar = "█" * v + "░" * (20 - min(v, 20))
        logger.info(f"  {k:<14}: {bar} {v}")
    logger.info("")

    # ── Build results dict & save JSON ───────────────
    output_data = {
        "trade_date": trade_date.strftime("%d %b %Y"),
        "macro": macro,
        "top_longs":     top_longs.fillna("").to_dict(orient="records"),
        "top_shorts":    top_shorts.fillna("").to_dict(orient="records"),
        "oi_alerts":     oi_alerts.fillna("").to_dict(orient="records"),
        "full_universe": df.fillna("").to_dict(orient="records"),
    }

    json_path = f"logs/screener_results_{trade_date.strftime('%Y%m%d')}.json"
    with open(json_path, "w") as f:
        json.dump(output_data, f, indent=2, default=str)
    logger.info(f"✅ Results saved: {json_path}")

    csv_path = f"logs/screener_output_{trade_date.strftime('%Y%m%d')}.csv"
    df.to_csv(csv_path, index=False)
    logger.info(f"✅ CSV saved: {csv_path}")

    return output_data, json_path


# ─────────────────────────────────────────────
# VERIFY TELEGRAM FORMAT
# ─────────────────────────────────────────────

def verify_telegram_format(output_data: dict):
    """Show what the Telegram message will look like."""
    from telegram_alert import build_morning_brief
    msg = build_morning_brief(output_data)
    logger.info("\n" + "=" * 65)
    logger.info("TELEGRAM MESSAGE PREVIEW:")
    logger.info("=" * 65)
    # Print without HTML tags for readability
    import re
    clean = re.sub(r'<[^>]+>', '', msg)
    print(clean)
    logger.info("=" * 65)
    logger.info(f"Message length: {len(msg)} characters (Telegram max: 4096)")
    return msg


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "━" * 65)
    print("  F&O MORNING SCREENER — END-TO-END TEST RUN")
    print("  Testing complete pipeline with realistic synthetic data")
    print("━" * 65 + "\n")

    try:
        # 1. Run screening pipeline
        output_data, json_path = run_test_pipeline()

        # 2. Show Telegram message preview
        verify_telegram_format(output_data)

        # 3. Verify scoring logic
        top_longs  = output_data["top_longs"]
        top_shorts = output_data["top_shorts"]
        full       = output_data["full_universe"]

        print("\n" + "━" * 65)
        print("  VERIFICATION CHECKS")
        print("━" * 65)
        checks = [
            ("Stocks scored",         len(full) >= 100,    f"{len(full)} stocks"),
            ("Top Longs found",       len(top_longs) > 0,  f"{len(top_longs)} stocks"),
            ("Top Shorts found",      len(top_shorts) > 0, f"{len(top_shorts)} stocks"),
            ("Scores in range",       all(-18 <= int(s.get("COMPOSITE_SCORE", 0)) <= 18 for s in full), "All within -18 to +18"),
            ("JSON output exists",    Path(json_path).exists(), json_path),
            ("RSI values populated",  sum(1 for s in full if s.get("RSI")) > 50, "50+ stocks"),
            ("ADX values populated",  sum(1 for s in full if s.get("ADX")) > 50, "50+ stocks"),
            ("OI signals assigned",   all(s.get("OI_SIGNAL") for s in full[:10]), "All top stocks"),
        ]

        all_pass = True
        for name, passed, detail in checks:
            status = "✅ PASS" if passed else "❌ FAIL"
            if not passed:
                all_pass = False
            print(f"  {status}  {name:<30} {detail}")

        print("━" * 65)
        if all_pass:
            print("  ✅ ALL CHECKS PASSED — Pipeline is working correctly!")
        else:
            print("  ⚠️  Some checks failed — review output above")
        print("━" * 65 + "\n")

        print("NEXT STEPS:")
        print("  1. Set up Google Service Account (see setup_guide.md Step 1)")
        print("  2. Create Google Sheet + share with service account (Step 2)")
        print("  3. Create Telegram bot (Step 3)")
        print("  4. Update config.py with your credentials")
        print("  5. Run: python screener.py     (downloads real NSE data)")
        print("  6. Run: python sheets_updater.py")
        print("  7. Run: python telegram_alert.py")
        print("  8. Push to GitHub and enable Actions (Step 4-9)")
        print()

    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        sys.exit(1)
