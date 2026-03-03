# F&O Morning Screener — Complete Setup Guide

Estimated total setup time: **45–60 minutes** (one-time)

---

## Prerequisites
- A Google account
- A Telegram account
- A GitHub account
- Python 3.10+ installed locally

---

## STEP 1: Create Google Service Account + Download Credentials JSON

**Time: ~10 minutes**

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click **Select a project** → **New Project**
   - Name: `fo-screener` → **Create**
3. In the left sidebar: **APIs & Services → Library**
   - Search **Google Sheets API** → Enable
   - Search **Google Drive API** → Enable
4. Go to **APIs & Services → Credentials**
5. Click **+ Create Credentials → Service Account**
   - Name: `fo-screener-bot` → **Create and Continue → Done**
6. Click on the service account email you just created
7. Go to **Keys** tab → **Add Key → Create New Key → JSON → Create**
8. A JSON file downloads automatically — **save it securely**
9. Note the service account email (looks like `fo-screener-bot@your-project.iam.gserviceaccount.com`)

---

## STEP 2: Create Google Sheet + Share with Service Account

**Time: ~5 minutes**

1. Go to [Google Sheets](https://sheets.google.com/) → **Create blank spreadsheet**
2. Name it: `F&O Morning Screener`
3. Copy the **Sheet ID** from the URL:
   ```
   https://docs.google.com/spreadsheets/d/THIS_IS_YOUR_SHEET_ID/edit
   ```
4. Click **Share** → paste the service account email → set **Editor** → **Done**
5. Paste the Sheet ID into `config.py`:
   ```python
   GOOGLE_SHEET_ID = "your_sheet_id_here"
   ```
6. For the PWA, also update `pwa/index.html`:
   ```javascript
   const SHEET_ID = "your_sheet_id_here";
   ```
7. After first screener run, find the GID for each tab:
   - Click each tab in Google Sheets
   - The URL shows `&gid=XXXXXXXXX`
   - Update `TAB_GIDS` in `pwa/index.html` accordingly

---

## STEP 3: Create Telegram Bot + Get Chat ID

**Time: ~5 minutes**

### Create the bot:
1. Open Telegram → search **@BotFather**
2. Send `/newbot`
3. Enter name: `	`
4. Enter username: `fo_screener_yourname_bot` (must be unique)
5. BotFather gives you a **Bot Token** — copy it

### Get your Chat ID:
1. Start your new bot (send `/start`)
2. Visit this URL in your browser (replace TOKEN):
   ```
   https://api.telegram.org/bot8035306929:AAElgG0S22vrKCyXEW_OyDm6wOPc7U21Ux8/getUpdates
   ```
3. Find `"chat":{"id":XXXXXXXXX}` — that number is your Chat ID
4. For a **group/channel**: add the bot to it, send a message, check `getUpdates`

### Update config:
```python
TELEGRAM_BOT_TOKEN = "your_bot_token_here"
TELEGRAM_CHAT_ID   = "your_chat_id_here"
```

---

## STEP 4: Create GitHub Repository

**Time: ~5 minutes**

1. Go to [GitHub](https://github.com) → **New repository**
2. Name: `fo-screener` → Private (recommended) → **Create repository**
3. Initialize your local repo and push:
   ```bash
   cd fo-screener/
   git init
   git add .
   git commit -m "Initial F&O screener setup"
   git remote add origin https://github.com/YOUR_USERNAME/fo-screener.git
   git push -u origin main
   ```

> **Important:** Add `credentials/` to `.gitignore` to avoid committing your service account JSON!

---

## STEP 5: Add GitHub Secrets

**Time: ~5 minutes**

Go to your GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**

Add these 4 secrets:

| Secret Name | Value |
|---|---|
| `GOOGLE_CREDENTIALS_JSON` | Paste the **entire contents** of your service account JSON file |
| `GOOGLE_SHEET_ID` | Your Google Sheet ID |
| `TELEGRAM_BOT_TOKEN` | Your Telegram bot token |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |

---

## STEP 6: Deploy PWA to GitHub Pages

**Time: ~5 minutes**

1. In your GitHub repo → **Settings → Pages**
2. Source: **Deploy from a branch**
3. Branch: `main` / Folder: `/pwa` → **Save**
4. Wait 2–3 minutes → your PWA URL will be:
   ```
   https://YOUR_USERNAME.github.io/fo-screener/
   ```
5. Update the sheet link in `pwa/index.html` if needed
6. Commit and push the `pwa/` folder

---

## STEP 7: Install PWA on iPhone and Android

**Time: ~2 minutes**

### iPhone / Safari:
1. Open the PWA URL in Safari
2. Tap the **Share** button (square with arrow)
3. Scroll down → tap **Add to Home Screen**
4. Name it → **Add**

### Android / Chrome:
1. Open the PWA URL in Chrome
2. Tap the **⋮ menu** → **Add to Home screen**
3. Or wait for the **install banner** to appear automatically
4. Tap **Install**

---

## STEP 8: First Manual Test Run

**Time: ~10 minutes**

```bash
# 1. Navigate to project folder
cd fo-screener/

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set up credentials (for local testing)
mkdir -p credentials
cp /path/to/your/service_account.json credentials/service_account.json

# 4. Set environment variables (or edit config.py directly)
export GOOGLE_SHEET_ID="your_sheet_id"
export TELEGRAM_BOT_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"

# 5. Run the screener (uses last NSE trading day by default)
python screener.py

# 6. Update Google Sheets
python sheets_updater.py

# 7. Send Telegram message
python telegram_alert.py

# 8. Test a specific date
python screener.py --date 2025-01-15
```

---

## STEP 9: Verify GitHub Actions is Scheduled

1. Go to your GitHub repo → **Actions** tab
2. You should see **F&O Morning Screener** workflow listed
3. To test manually: click the workflow → **Run workflow** → **Run workflow**
4. Watch the run complete — check each step for ✅
5. Check your Telegram for the morning brief message
6. Check Google Sheets to see populated data

The schedule runs at **6:30 AM IST every weekday** (01:00 UTC).

---

## STEP 10: How to Read the Morning Output

### Signal Types:
| Signal | Meaning | Action |
|---|---|---|
| **LONG BUILDUP** | OI↑ + Price↑ | Bulls adding positions — bullish |
| **SHORT COVERING** | OI↓ + Price↑ | Bears exiting — price may spike |
| **SHORT BUILDUP** | OI↑ + Price↓ | Bears adding positions — bearish |
| **LONG UNWINDING** | OI↓ + Price↓ | Bulls exiting — bearish pressure |

### Composite Score Guide:
| Score | Classification | Action |
|---|---|---|
| +14 to +18 | **STRONG LONG** | High-conviction long trade |
| +8 to +13 | **LONG CANDIDATE** | Look for entry on pullback |
| -7 to +7 | **NEUTRAL** | No trade / monitor |
| -8 to -13 | **SHORT CANDIDATE** | Look for entry on bounce |
| -14 to -18 | **STRONG SHORT** | High-conviction short trade |

### OI Alert Severity:
- **🔥 HIGH** — OI change >30% (major institutional activity)
- **⚡ MEDIUM** — OI change 20–30% (significant activity)

### Macro Context (FII positioning):
- **BULLISH**: FII net long >10,000 contracts in index futures
- **BEARISH**: FII net short >10,000 contracts
- **NEUTRAL**: FII positions balanced

---

## Troubleshooting

**NSE download fails:**
- NSE blocks requests without proper headers — the screener handles this
- If failing consistently, the NSE site may be down — check NSE website directly
- Bhavcopy is available from 6:00 PM IST on trading days

**Google Sheets authentication fails:**
- Ensure the service account JSON is correctly pasted in GitHub Secrets
- Ensure the sheet is shared with the service account email

**Telegram not sending:**
- Verify bot token and chat ID are correct
- Send `/start` to your bot if you haven't already
- For groups, ensure the bot is added as a member

**yfinance data unavailable for some stocks:**
- Some stocks may be newly listed or have thin trading history
- The screener handles this gracefully (scores as 0)

**GitHub Actions not triggering:**
- The cron runs in UTC — `0 1 * * 1-5` = 6:30 AM IST
- GitHub may delay scheduled workflows by up to 30 minutes during high load
- Use "Run workflow" to test manually

---

## File Structure

```
fo-screener/
├── config.py              # All configuration & F&O universe
├── screener.py            # Core screener (NSE + technical + F&O scoring)
├── sheets_updater.py      # Google Sheets output
├── telegram_alert.py      # Telegram messaging
├── requirements.txt       # Python dependencies
├── setup_guide.md         # This file
├── .gitignore             # Excludes credentials/ and logs/
├── credentials/           # (gitignored) Service account JSON
│   └── service_account.json
├── logs/                  # (gitignored) Daily log files + CSV output
│   ├── screener_YYYYMMDD.log
│   ├── screener_results_YYYYMMDD.json
│   └── screener_output_YYYYMMDD.csv
├── pwa/                   # Progressive Web App
│   ├── index.html         # Main PWA (all-in-one)
│   ├── manifest.json      # PWA manifest
│   ├── sw.js              # Service worker
│   └── icons/             # App icons (192×192 and 512×512 PNG)
└── .github/
    └── workflows/
        └── screener.yml   # GitHub Actions workflow
```

---

## Maintenance

**Update F&O stock list** (NSE changes the F&O lot monthly):
- Edit `FO_STOCKS` in `config.py`

**Tune scoring thresholds**:
- All thresholds are in `config.py` — adjust to your preference

**Update holiday list** annually:
- Edit `NSE_HOLIDAYS_2026` in `config.py`

**Add new Google Sheet year** in tabs:
- The screener auto-creates tabs — no action needed
