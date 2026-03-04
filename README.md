# NSE F&O Morning Screener

A fully automated equity screener for the NSE Futures & Options universe, built for systematic pre-market preparation.

The screener downloads live NSE bhavcopy data every morning, scores all 206 F&O stocks across 13 indicators, and produces a ranked output of long and short candidates — ready before market open.

---

## What It Does

- Downloads live NSE F&O and CM bhavcopy files daily
- Fetches 1-year OHLCV history for all 206 F&O stocks via yfinance
- Scores each stock across 13 indicators into a composite score
- Ranks the full universe and flags top long/short candidates, OI alerts, sector bias, and persistent signals
- Saves output as CSV and JSON to the `logs/` folder
- Builds a rolling `signal_history.csv` to track multi-day signal persistence
- Runs automatically via GitHub Actions — no manual intervention needed

---

## Indicators

### Technical (8) — sourced from yfinance
| Indicator | Signal Logic |
|---|---|
| EMA Alignment (20/50/200) | Price > EMA20 > EMA50 > EMA200 = Bullish, reverse = Bearish |
| RSI (14) | 45–70 = Bullish zone, 30–55 = Bearish zone |
| MACD (12/26/9) | Bullish/bearish crossover in last 2 bars |
| ADX (14) | >25 with DI+ > DI- = Bull trend, DI- > DI+ = Bear trend |
| Supertrend (10, 3) | Price above = Bullish, below = Bearish |
| Volume Ratio | >1.5x 20-day avg = confirmation, <0.5x = weak |
| Bollinger Bands (20, 2σ) | Squeeze + price above mid = coiled bullish, below = coiled bearish |
| 52W Breakout | Breakout above/below 52-week range with volume confirmation |

### F&O (5) — sourced from NSE bhavcopy (no additional downloads)
| Indicator | Source | Signal Logic |
|---|---|---|
| OI Pattern | F&O bhavcopy (futures) | Long buildup / Short buildup / Short covering / Long unwinding |
| OI Magnitude | F&O bhavcopy (futures) | >15% change = medium (+1), >25% = high (+2) bonus |
| Delivery % | CM bhavcopy | >60% = institutional interest (+2), <20% = speculative (-1) |
| PCR per stock | F&O bhavcopy (options) | <0.5 = call-heavy (+2), >1.5 = put-heavy (-2) |
| Relative Strength vs Nifty | yfinance (^NSEI) | 20-day return percentile rank vs universe — top 20% = +2, bottom 20% = -2 |

---

## Composite Score & Classification

| Classification | Threshold | What It Means |
|---|---|---|
| Strong Long | ≥ +20 | 7+ indicators bullish — very high conviction |
| Long Candidate | ≥ +12 | 4–5 indicators aligned — tradeable setup |
| Neutral | -11 to +11 | No clear edge — wait for setup to develop |
| Short Candidate | ≤ -12 | 4–5 indicators bearish — tradeable short |
| Strong Short | ≤ -20 | 7+ indicators bearish — very high conviction |

Score range: +27 (maximum) to -26 (minimum) across all 13 indicators.

---

## OI Alert Severity

| Tier | OI Change | Cross-reference |
|---|---|---|
| MEDIUM | 10–24% | Flagged for monitoring |
| HIGH | 25–39% | Cross-referenced with composite score |
| EXTREME | ≥ 40% | Highest priority alert |

Alerts are cross-referenced with composite score to produce contextual labels such as `EXTREME LONG BUILDUP`, `STRONG BEARISH OI`, or `OI DIVERGENCE — WATCH`.

---

## Sector Summary

All 206 stocks are mapped across 13 sectors. Each run produces a sector-level bias table:

```
SECTOR SUMMARY:
  ENERGY             Avg= -4.5 | L: 2 S: 4 N:18 | NEUTRAL        LLSSSS
  REALTY             Avg=-10.7 | L: 0 S: 2 N: 4 | MILD BEARISH   SS
  IT                 Avg= -8.2 | L: 0 S: 3 N:10 | NEUTRAL        SSS
```

Bias labels: `BULLISH` / `MILD BULLISH` / `NEUTRAL` / `MILD BEARISH` / `BEARISH`

Sectors covered: FINANCIALS, IT, CONSUMER, AUTO, PHARMA, ENERGY, METALS, INFRA, REALTY, TELECOM, CHEMICALS, CAPITAL_GOODS, OTHERS

---

## Signal Persistence

The screener maintains a rolling `logs/signal_history.csv` updated every run. Stocks that have been a Long or Short Candidate for 3+ consecutive trading days are flagged as persistent signals:

```
PERSISTENT SIGNALS (3+ consecutive days):
  SHORTS:
    TATATECH        [P4d] Score= -14 | SHORT CANDIDATE
    WAAREEENER      [P3d] Score= -13 | SHORT CANDIDATE
```

Persistent signals are higher conviction than single-day flashes — they indicate sustained directional pressure across multiple sessions.

---

## Output

Each run produces files in `logs/`:

- `screener_output_YYYYMMDD.csv` — full 206-stock universe ranked by composite score
- `screener_results_YYYYMMDD.json` — structured output with top longs, shorts, OI alerts, sector summary, and persistent signals
- `signal_history.csv` — rolling multi-day signal history for persistence tracking

### Sample log output
```
RESULTS — 04 Mar 2026
Market Bias: BEARISH | FII Fut Net: -163,713
------------------------------------------------------------
TOP 10 LONG CANDIDATES:
  OIL             Score= +17 (T:+12 F:+4 RS:+1) | LONG CANDIDATE  | LONG BUILDUP       | BB:UPPER BAND RIDE | BO:NO BREAKOUT | PCR:0.54 | RS:ABOVE AVG RS(79%)
  SOLARINDS       Score= +12 (T: +8 F:+2 RS:+2) | LONG CANDIDATE  | SHORT COVERING     | BB:UPPER BAND RIDE | BO:NO BREAKOUT | PCR:0.83 | RS:TOP RS(88%)
------------------------------------------------------------
TOP 10 SHORT CANDIDATES:
  TATATECH        Score= -14 (T:-10 F:-2 RS:-2) | SHORT CANDIDATE | SHORT BUILDUP      | BB:LOWER BAND RIDE | BO:NEAR 52W LOW | PCR:0.64 | RS:WEAK RS(11%)
  WAAREEENER      Score= -13 (T: -9 F:-2 RS:-2) | SHORT CANDIDATE | SHORT BUILDUP      | BB:LOWER BAND RIDE | BO:NO BREAKOUT  | PCR:0.6  | RS:WEAK RS(8%)
------------------------------------------------------------
OI ALERTS: 3 stocks with OI change >10%
  FEDERALBNK      OI%=+12.5% | MEDIUM   | OI DIVERGENCE — WATCH
------------------------------------------------------------
SECTOR SUMMARY:
  REALTY             Avg=-10.7 | L: 0 S: 2 N: 4 | MILD BEARISH   SS
------------------------------------------------------------
PERSISTENT SIGNALS: None yet — need 3+ days of history
```

---

## Setup & Usage

### Prerequisites
- Python 3.10–3.13
- Git

### Install dependencies
```bash
pip install yfinance pandas requests numpy
```

### Run manually
```bash
# Latest trading day
python screener.py

# Specific date
python screener.py --date 2026-03-04
```

### Sync F&O universe
```bash
# Check diff only
python sync_fo_universe.py

# Auto-update config.py
python sync_fo_universe.py --update
```

---

## Automated Run (GitHub Actions)

The screener runs automatically on a daily schedule via `.github/workflows/`. It:
1. Checks out the repo
2. Installs dependencies
3. Downloads live NSE data
4. Scores all stocks and saves output

To trigger manually, go to **Actions → Run workflow** in the GitHub UI.

---

## Configuration

All parameters are in `config.py`:

| Parameter | Default | Description |
|---|---|---|
| `BB_SQUEEZE_THRESHOLD` | 0.05 | Bandwidth < 5% of price = squeeze |
| `BREAKOUT_NEAR_PCT` | 3.0 | Within 3% of 52W high/low = near breakout |
| `BREAKOUT_CONFIRM_VOL` | 1.5 | Volume must be >1.5x avg to confirm breakout |
| `PCR_VERY_BULLISH` | 0.5 | PCR below this = call-heavy = +2 score |
| `PCR_VERY_BEARISH` | 1.5 | PCR above this = put-heavy = -2 score |
| `RS_PERIOD` | 20 | Days for relative strength return calculation |
| `RS_STRONG_BULL` | 80 | RS percentile >= 80 = +2 score |
| `RS_STRONG_BEAR` | 20 | RS percentile <= 20 = -2 score |
| `OI_CHANGE_EXTREME` | 40 | OI change % for EXTREME severity tier |
| `LONG_THRESHOLD` | 12 | Minimum composite score for Long Candidate |
| `STRONG_LONG_THRESHOLD` | 20 | Minimum composite score for Strong Long |

---

## Universe

206 NSE F&O stocks as of March 2026, mapped across 13 sectors in `sector_map.py`. Auto-synced against live bhavcopy using `sync_fo_universe.py`. Run the sync script periodically (or via scheduled GitHub Action) to keep the universe current with NSE additions and removals.

---

## Roadmap

- **IV Percentile per stock** — requires 30–60 days of options data accumulation; the screener is building this history automatically with each daily run
- **Sector rotation alerts** — flag when a sector flips bias day-over-day
- **WhatsApp / Telegram morning brief** — auto-format and send top signals before market open

---

*Built for an institutional equity research workflow covering Indian consumer, BFSI, auto, and infrastructure sectors.*
