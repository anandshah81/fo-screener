# NSE F&O Morning Screener

A fully automated equity screener for the NSE Futures & Options universe, built for systematic pre-market preparation.

The screener downloads live NSE bhavcopy data every morning, scores all 206 F&O stocks across 12 indicators, and produces a ranked output of long and short candidates — ready before market open.

---

## What It Does

- Downloads live NSE F&O and CM bhavcopy files daily
- Fetches 1-year OHLCV history for all 206 F&O stocks via yfinance
- Scores each stock across 12 indicators into a composite score
- Ranks the full universe and flags top long/short candidates and OI alerts
- Saves output as CSV and JSON to the `logs/` folder
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

### F&O (4) — sourced from NSE bhavcopy (no additional downloads)
| Indicator | Source | Signal Logic |
|---|---|---|
| OI Pattern | F&O bhavcopy (futures) | Long buildup / Short buildup / Short covering / Long unwinding |
| OI Magnitude | F&O bhavcopy (futures) | >15% change = medium (+1), >25% = high (+2) bonus |
| Delivery % | CM bhavcopy | >60% = institutional interest, <20% = speculative |
| PCR per stock | F&O bhavcopy (options) | <0.5 = call-heavy (+2), >1.5 = put-heavy (-2) |

---

## Composite Score & Classification

| Classification | Threshold | What It Means |
|---|---|---|
| Strong Long | ≥ +19 | 7+ indicators bullish — very high conviction |
| Long Candidate | ≥ +11 | 4–5 indicators aligned — tradeable setup |
| Neutral | -10 to +10 | No clear edge — wait for setup to develop |
| Short Candidate | ≤ -11 | 4–5 indicators bearish — tradeable short |
| Strong Short | ≤ -19 | 7+ indicators bearish — very high conviction |

Score range: +25 (maximum) to -24 (minimum) across all 12 indicators.

---

## OI Alert Severity

| Tier | OI Change | Cross-reference |
|---|---|---|
| MEDIUM | 10–24% | Flagged for monitoring |
| HIGH | 25–39% | Cross-referenced with composite score |
| EXTREME | ≥ 40% | Highest priority alert |

Alerts are cross-referenced with composite score to produce contextual labels such as `EXTREME LONG BUILDUP`, `STRONG BEARISH OI`, or `OI DIVERGENCE — WATCH`.

---

## Output

Each run produces two files in `logs/`:

- `screener_output_YYYYMMDD.csv` — full 206-stock universe ranked by composite score
- `screener_results_YYYYMMDD.json` — structured output with top longs, shorts, OI alerts, and macro context

### Sample log output
```
RESULTS — 04 Mar 2026
Market Bias: BEARISH | FII Fut Net: -163,713
------------------------------------------------------------
TOP 10 LONG CANDIDATES:
  OIL             Score= +16 (T:+12 F:+4) | LONG CANDIDATE  | LONG BUILDUP       | BB:UPPER BAND RIDE | BO:NO BREAKOUT | PCR:0.54
------------------------------------------------------------
TOP 10 SHORT CANDIDATES:
  VBL             Score= -13 (T:-11 F:-2) | SHORT CANDIDATE | SHORT BUILDUP      | BB:LOWER BAND RIDE | BO:52W LOW BREAKDOWN | PCR:0.61
------------------------------------------------------------
OI ALERTS: 3 stocks with OI change >10%
  FEDERALBNK      OI%=+12.5% | MEDIUM   | OI DIVERGENCE — WATCH
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
| `OI_CHANGE_EXTREME` | 40 | OI change % for EXTREME severity tier |
| `LONG_THRESHOLD` | 11 | Minimum composite score for Long Candidate |
| `STRONG_LONG_THRESHOLD` | 19 | Minimum composite score for Strong Long |

---

## Universe

206 NSE F&O stocks as of March 2026, auto-synced against live bhavcopy using `sync_fo_universe.py`. Run the sync script periodically (or via scheduled GitHub Action) to keep the universe current with NSE additions and removals.

---

## Roadmap

- **IV Percentile per stock** — requires 30–60 days of options data accumulation; the screener is building this history automatically with each daily run
- **Relative strength vs Nifty** — normalise scores against index momentum
- **Sector rotation context** — flag when multiple stocks in a sector align directionally

---

*Built for an institutional equity research workflow covering Indian consumer, BFSI, auto, and infrastructure sectors.*
