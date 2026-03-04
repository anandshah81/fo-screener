"""
config.py — Central configuration for F&O Morning Screener
All thresholds, URLs, credentials paths, and the full NSE F&O universe.
Edit this file to tune scoring, add/remove stocks, or update paths.
"""

import os

# ─────────────────────────────────────────────
# CREDENTIALS & EXTERNAL SERVICES
# ─────────────────────────────────────────────

# Path to Google Service Account JSON key file
# For GitHub Actions this is injected via env var GOOGLE_CREDENTIALS_JSON
GOOGLE_CREDENTIALS_PATH = os.environ.get(
    "GOOGLE_CREDENTIALS_PATH", "credentials/service_account.json"
)

# Google Sheet ID (the long alphanumeric string in the sheet URL)
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")

# Telegram Bot Token and Chat ID
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ─────────────────────────────────────────────
# GOOGLE SHEET TAB NAMES
# ─────────────────────────────────────────────
SHEET_TABS = {
    "morning_brief": "MORNING BRIEF",
    "top_longs":     "TOP LONGS",
    "top_shorts":    "TOP SHORTS",
    "oi_alerts":     "OI ALERTS",
    "full_universe": "FULL UNIVERSE",
}

# ─────────────────────────────────────────────
# NSE DATA URLs  (date placeholders: {dd}, {mm}, {yyyy}, {DDMONYYYY})
# ─────────────────────────────────────────────
NSE_BASE = "https://nsearchives.nseindia.com"

# New UDiFF format URLs (effective July 8, 2024 — old format discontinued)
NSE_FO_BHAVCOPY_URL = (
    f"{NSE_BASE}/content/fo/BhavCopy_NSE_FO_0_0_0_{{yyyy}}{{mm}}{{dd}}_F_0000.csv.zip"
)

NSE_CM_BHAVCOPY_URL = (
    f"{NSE_BASE}/content/cm/BhavCopy_NSE_CM_0_0_0_{{yyyy}}{{mm}}{{dd}}_F_0000.csv.zip"
)

NSE_PARTICIPANT_OI_URL = (
    f"{NSE_BASE}/content/nsccl/fao_participant_oi_{{dd}}{{mm}}{{yyyy}}.csv"
)

# Fallback / alternate NSE bhavcopy CDN (old format — kept for reference only)
NSE_FO_BHAVCOPY_ALT = (
    "https://www.nseindia.com/api/reports?archives=%5B%7B%22name%22%3A%22F%26O%20-%20Bhavcopy(csv)%22"
    "%2C%22type%22%3A%22archives%22%2C%22category%22%3A%22derivatives%22%2C%22section%22%3A%22equity%22%7D%5D"
    "&date={dd}-{MON}-{yyyy}&type=equity&mode=single"
)

# ─────────────────────────────────────────────
# DOWNLOAD / RETRY SETTINGS
# ─────────────────────────────────────────────
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 60          # wait between retries
REQUEST_TIMEOUT = 30              # seconds per HTTP request
NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/",
}

# ─────────────────────────────────────────────
# TECHNICAL INDICATOR PARAMETERS
# ─────────────────────────────────────────────
EMA_SHORT  = 20
EMA_MID    = 50
EMA_LONG   = 200
RSI_PERIOD = 14
ADX_PERIOD = 14
SUPERTREND_PERIOD = 10
SUPERTREND_MULTIPLIER = 3
MACD_FAST  = 12
MACD_SLOW  = 26
MACD_SIGNAL = 9
VOLUME_MA_PERIOD = 20

# Bollinger Bands
BB_PERIOD = 20
BB_STD_DEV = 2.0
BB_SQUEEZE_THRESHOLD = 0.05   # bandwidth < 5% of price → squeeze

# Breakout Detection
BREAKOUT_LOOKBACK = 52        # weeks (mapped to ~252 trading days for 1y)
BREAKOUT_NEAR_PCT = 3.0       # within 3% of 52w high/low = "near breakout"
BREAKOUT_CONFIRM_VOL = 1.5    # volume must be >1.5x avg to confirm breakout

# ─────────────────────────────────────────────
# SCORING THRESHOLDS
# ─────────────────────────────────────────────
RSI_BULL_LOW   = 45
RSI_BULL_HIGH  = 70
RSI_BEAR_LOW   = 30
RSI_BEAR_HIGH  = 55

ADX_TREND_THRESHOLD = 25

VOLUME_HIGH_RATIO = 1.5   # >1.5x avg → confirmation
VOLUME_LOW_RATIO  = 0.5   # <0.5x avg → weak

OI_CHANGE_MEDIUM = 15     # % change for +1/-1 extra
OI_CHANGE_HIGH   = 25     # % change for +2/-2 extra
OI_CHANGE_EXTREME = 40    # % change — exceptional surge, new EXTREME severity tier
OI_ALERT_THRESHOLD = 10   # % change for OI alert list

DELIVERY_HIGH = 60        # % delivery → institutional
DELIVERY_LOW  = 20        # % delivery → speculative

# Composite score classification
# Score range: +23 (max) to -22 (min) across 11 indicators
# Strong Long/Short = ~78% of max, requiring 7+ indicators aligned
# Long/Short candidate = ~43% of max, requiring 4-5 indicators aligned
STRONG_LONG_THRESHOLD  = 18
LONG_THRESHOLD         = 10
SHORT_THRESHOLD        = -10
STRONG_SHORT_THRESHOLD = -17

# ─────────────────────────────────────────────
# YFINANCE SETTINGS
# ─────────────────────────────────────────────
YFINANCE_PERIOD  = "1y"        # historical data to download
YFINANCE_INTERVAL = "1d"
YFINANCE_SUFFIX  = ".NS"       # NSE suffix for yfinance

# Batch size for yfinance downloads to avoid rate limiting
YFINANCE_BATCH_SIZE = 20
YFINANCE_BATCH_DELAY = 2       # seconds between batches

# ─────────────────────────────────────────────
# OUTPUT / LOGGING
# ─────────────────────────────────────────────
LOGS_DIR = "logs"
OUTPUT_CSV = "logs/screener_output_{date}.csv"

# ─────────────────────────────────────────────
# NSE F&O STOCK UNIVERSE  (206 stocks — synced 04 Mar 2026)
# ─────────────────────────────────────────────
FO_STOCKS = [
    "360ONE", "ABB", "ABCAPITAL", "ADANIENSOL", "ADANIENT",
    "ADANIGREEN", "ADANIPORTS", "ALKEM", "AMBER", "AMBUJACEM",
    "ANGELONE", "APLAPOLLO", "APOLLOHOSP", "ASHOKLEY", "ASIANPAINT",
    "ASTRAL", "AUBANK", "AUROPHARMA", "AXISBANK", "BAJAJ-AUTO",
    "BAJAJFINSV", "BAJAJHLDNG", "BAJFINANCE", "BANDHANBNK", "BANKBARODA",
    "BANKINDIA", "BDL", "BEL", "BHARATFORG", "BHARTIARTL",
    "BHEL", "BIOCON", "BLUESTARCO", "BOSCHLTD", "BPCL",
    "BRITANNIA", "BSE", "CAMS", "CANBK", "CDSL",
    "CGPOWER", "CHOLAFIN", "CIPLA", "COALINDIA", "COFORGE",
    "COLPAL", "CONCOR", "CROMPTON", "CUMMINSIND", "DABUR",
    "DALBHARAT", "DELHIVERY", "DIVISLAB", "DIXON", "DLF",
    "DMART", "DRREDDY", "EICHERMOT", "ETERNAL", "EXIDEIND",
    "FEDERALBNK", "FORTIS", "GAIL", "GLENMARK", "GMRAIRPORT",
    "GODREJCP", "GODREJPROP", "GRASIM", "HAL", "HAVELLS",
    "HCLTECH", "HDFCAMC", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO",
    "HINDALCO", "HINDPETRO", "HINDUNILVR", "HINDZINC", "HUDCO",
    "ICICIBANK", "ICICIGI", "ICICIPRULI", "IDEA", "IDFCFIRSTB",
    "IEX", "INDHOTEL", "INDIANB", "INDIGO", "INDUSINDBK",
    "INDUSTOWER", "INFY", "INOXWIND", "IOC", "IREDA",
    "IRFC", "ITC", "JINDALSTEL", "JIOFIN", "JSWENERGY",
    "JSWSTEEL", "JUBLFOOD", "KALYANKJIL", "KAYNES", "KEI",
    "KFINTECH", "KOTAKBANK", "KPITTECH", "LAURUSLABS", "LICHSGFIN",
    "LICI", "LODHA", "LT", "LTF", "LTM",
    "LUPIN", "M&M", "MANAPPURAM", "MANKIND", "MARICO",
    "MARUTI", "MAXHEALTH", "MAZDOCK", "MCX", "MFSL",
    "MOTHERSON", "MPHASIS", "MUTHOOTFIN", "NATIONALUM", "NAUKRI",
    "NBCC", "NESTLEIND", "NHPC", "NMDC", "NTPC",
    "NUVAMA", "NYKAA", "OBEROIRLTY", "OFSS", "OIL",
    "ONGC", "PAGEIND", "PATANJALI", "PAYTM", "PERSISTENT",
    "PETRONET", "PFC", "PGEL", "PHOENIXLTD", "PIDILITIND",
    "PIIND", "PNB", "PNBHOUSING", "POLICYBZR", "POLYCAB",
    "POWERGRID", "POWERINDIA", "PPLPHARMA", "PREMIERENE", "PRESTIGE",
    "RBLBANK", "RECLTD", "RELIANCE", "RVNL", "SAIL",
    "SAMMAANCAP", "SBICARD", "SBILIFE", "SBIN", "SHREECEM",
    "SHRIRAMFIN", "SIEMENS", "SOLARINDS", "SONACOMS", "SRF",
    "SUNPHARMA", "SUPREMEIND", "SUZLON", "SWIGGY", "SYNGENE",
    "TATACONSUM", "TATAELXSI", "TATAPOWER", "TATASTEEL", "TATATECH",
    "TCS", "TECHM", "TIINDIA", "TITAN", "TMPV",
    "TORNTPHARM", "TORNTPOWER", "TRENT", "TVSMOTOR", "ULTRACEMCO",
    "UNIONBANK", "UNITDSPR", "UNOMINDA", "UPL", "VBL",
    "VEDL", "VOLTAS", "WAAREEENER", "WIPRO", "YESBANK",
    "ZYDUSLIFE",
]

# Month abbreviations used in NSE file names
NSE_MONTH_ABBR = {
    1: "JAN", 2: "FEB", 3: "MAR", 4: "APR",
    5: "MAY", 6: "JUN", 7: "JUL", 8: "AUG",
    9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC",
}

# Known NSE market holidays (update annually)
NSE_HOLIDAYS_2025 = [
    "2025-01-26", "2025-02-26", "2025-03-14", "2025-03-31",
    "2025-04-10", "2025-04-14", "2025-04-18", "2025-05-01",
    "2025-08-15", "2025-08-27", "2025-10-02", "2025-10-02",
    "2025-10-20", "2025-10-23", "2025-11-05", "2025-12-25",
]

NSE_HOLIDAYS_2026 = [
    "2026-01-26", "2026-03-19", "2026-03-20",
    "2026-04-02", "2026-04-06", "2026-04-14", "2026-05-01",
    "2026-07-29", "2026-08-15", "2026-09-14", "2026-10-01",
    "2026-10-08", "2026-10-27", "2026-10-28", "2026-11-04",
    "2026-11-16", "2026-12-25",
]

NSE_HOLIDAYS = set(NSE_HOLIDAYS_2025 + NSE_HOLIDAYS_2026)