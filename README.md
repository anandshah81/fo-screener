# NSE F&O Morning Screener

A fully automated equity screener for the NSE Futures & Options universe, built for systematic pre-market preparation.

The screener downloads live NSE bhavcopy data every morning, scores all 206 F&O stocks across 8 technical and 3 F&O-specific indicators, and produces a ranked output of long and short candidates — ready before market open.

---

## What It Does

- Downloads live NSE F&O and CM bhavcopy files daily
- Fetches 1-year OHLCV history for all 206 F&O stocks via yfinance
- Scores each stock across 11 indicators into a composite score
- Ranks the full universe and flags top long/short candidates and OI alerts
- Saves output as CSV and JSON to the `logs/` folder
- Runs automatically via GitHub Actions — no manual intervention needed

---

## Indicators

### Technical (8)
| Indicator | Signal Logic |
|---|---|
| EMA Alignment | Price > EMA20 > EMA50 > EMA200 = Bullish, reverse = Bearish |
| RSI (14) | 45–70 = Bullish zone, 30–55 = Bearish zone |
| MACD (12/26/9) | Bullish/bearish crossover in last 2 bars |
| ADX (14) | >25 with DI+ > DI- = Bull trend, DI- > DI+ = Bear trend |
| Supertrend (10, 3) | Price above = Bullish, below = Bearish |
| Volume Ratio | >1.5x 20-day avg = confirmation, <0.5x = weak |
| Bollinger Bands (20, 2σ) | Squeeze + price above mid = coiled bullish, below = coiled bearish |
| 52W Breakout | Breakout above/below 52-week range with volume confirmation |

### F&O (3)
| Indicator | Signal Logic |
|---|---|
| OI Pattern | Long buildup / Short buildup / Short covering / Long unwinding |
| OI Magnitude | >15% change = medium, >25% = high bonus score |
| Delivery % | >60% = institutional interest, <20% = speculative |

---

## Composite Score & Classification

| Classification | Threshold | What It Means |
|---|---|---|
| Strong Long | ≥ +18 | 7+ indicators bullish — very high conviction |
| Long Candidate | ≥ +10 | 4–5 indicators aligned — tradeable setup |
| Neutral | -9 to +9 | No clear edge — wait for setup to develop |
| Short Candidate | ≤ -10 | 4–5 indicators bearish — tradeable short |
| Strong Short | ≤ -17 | 7+ indicators bearish — very high conviction |

Score range: +23 (maximum) to -22 (minimum) across all 11 indicators.

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
  OIL             Score= +15 (T:+12 F:+3) | LONG CANDIDATE  | LONG BUILDUP       | BB:UPPER BAND RIDE | BO:NO BREAKOUT
------------------------------------------------------------
TOP 10 SHORT CANDIDATES:
  VBL             Score= -14 (T:-11 F:-3) | SHORT CANDIDATE | SHORT BUILDUP      | BB:LOWER BAND RIDE | BO:52W LOW BREAKDOWN
------------------------------------------------------------
OI ALERTS: 3 stocks with OI change >10%
  AUBANK          OI%=+10.3% | MEDIUM   | OI SHORT BUILDUP
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
| `OI_CHANGE_EXTREME` | 40 | OI change % for EXTREME severity tier |
| `LONG_THRESHOLD` | 10 | Minimum composite score for Long Candidate |
| `STRONG_LONG_THRESHOLD` | 18 | Minimum composite score for Strong Long |

---

## Universe

206 NSE F&O stocks as of March 2026, auto-synced against live bhavcopy using `sync_fo_universe.py`. Run the sync script periodically (or via scheduled GitHub Action) to keep the universe current with NSE additions and removals.

---

*Built for an institutional equity research workflow covering Indian consumer, BFSI, auto, and infrastructure sectors.*
