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
OI_ALERT_THRESHOLD = 20   # % change for OI alert list

DELIVERY_HIGH = 60        # % delivery → institutional
DELIVERY_LOW  = 20        # % delivery → speculative

# Composite score classification
STRONG_LONG_THRESHOLD  = 14
LONG_THRESHOLD         = 8
SHORT_THRESHOLD        = -8
STRONG_SHORT_THRESHOLD = -14

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
# NSE F&O STOCK UNIVERSE  (~182 stocks as of 2025)
# ─────────────────────────────────────────────
FO_STOCKS = [
    "AARTIIND", "ABB", "ABBOTINDIA", "ABCAPITAL", "ABFRL", "ACC",
    "ADANIENT", "ADANIGREEN", "ADANIPORTS", "ADANIPOWER", "ALKEM",
    "ALKYLAMINE", "AMARAJABAT", "AMBUJACEM", "APOLLOHOSP", "APOLLOTYRE",
    "ASHOKLEY", "ASIANPAINT", "ASTRAL", "ATUL", "AUBANK",
    "AUROPHARMA", "AXISBANK", "BAJAJ-AUTO", "BAJAJFINSV", "BAJFINANCE",
    "BALKRISIND", "BALRAMCHIN", "BANDHANBNK", "BANKBARODA", "BATAINDIA",
    "BEL", "BERGEPAINT", "BHARATFORG", "BHARTIARTL", "BHEL",
    "BIOCON", "BPCL", "BRITANNIA", "BSOFT", "CANBK",
    "CANFINHOME", "CASTROLIND", "CDSL", "CESC", "CHOLAFIN",
    "CIPLA", "COALINDIA", "COFORGE", "COLPAL", "CONCOR",
    "COROMANDEL", "CROMPTON", "CUB", "CUMMINSIND", "DABUR",
    "DALBHARAT", "DEEPAKNTR", "DELTACORP", "DIVISLAB", "DIXON",
    "DLF", "DRREDDY", "EICHERMOT", "ESCORTS", "EXIDEIND",
    "FEDERALBNK", "FINEMETA", "FINNIFTY", "FORTIS", "GAIL",
    "GLENMARK", "GMRINFRA", "GNFC", "GODREJCP", "GODREJPROP",
    "GRANULES", "GRASIM", "GUJGASLTD", "HAL", "HAVELLS",
    "HCLTECH", "HDFCAMC", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO",
    "HINDALCO", "HINDCOPPER", "HINDPETRO", "HINDUNILVR", "HONAUT",
    "ICICIBANK", "ICICIGI", "ICICIPRULI", "IDEA", "IDFCFIRSTB",
    "IEX", "IGL", "INDHOTEL", "INDIACEM", "INDIAMART",
    "INDIGO", "INDUSINDBK", "INDUSTOWER", "INFY", "IOC",
    "IPCALAB", "IRCTC", "ITC", "JINDALSTEL", "JSL",
    "JSWSTEEL", "JUBLFOOD", "KOTAKBANK", "KPITTECH", "LALPATHLAB",
    "LAURUSLABS", "LICHSGFIN", "LT", "LTIM", "LTTS",
    "LUPIN", "M&M", "M&MFIN", "MANAPPURAM", "MARICO",
    "MARUTI", "MCDOWELL-N", "MCX", "METROPOLIS", "MFSL",
    "MGL", "MOTHERSON", "MPHASIS", "MRF", "MUTHOOTFIN",
    "NATIONALUM", "NAUKRI", "NAVINFLUOR", "NESTLEIND", "NIFTYBEES",
    "NMDC", "NTPC", "OBEROIRLTY", "OFSS", "OIL",
    "ONGC", "PAGEIND", "PEL", "PERSISTENT", "PETRONET",
    "PFC", "PIDILITIND", "PIIND", "PNB", "POLYCAB",
    "POWERGRID", "PVRINOX", "RAMCOCEM", "RBLBANK", "RECLTD",
    "RELIANCE", "SAIL", "SBICARD", "SBILIFE", "SBIN",
    "SHREECEM", "SIEMENS", "SRF", "SUNPHARMA", "SUNTV",
    "SYNGENE", "TATACHEM", "TATACOMM", "TATACONSUM", "TATAMOTORS",
    "TATAPOWER", "TATASTEEL", "TCS", "TECHM", "TITAN",
    "TORNTPHARM", "TRENT", "TVSMOTOR", "UBL", "ULTRACEMCO",
    "UPL", "VEDL", "VOLTAS", "WHIRLPOOL", "WIPRO",
    "ZEEL", "ZOMATO", "ZYDUSLIFE",
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