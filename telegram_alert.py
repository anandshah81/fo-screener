"""
telegram_alert.py — Send F&O morning brief + error alerts via Telegram.
Reads screener JSON output and sends formatted message to Telegram channel.
"""

import os
import sys
import json
import logging
import requests
from datetime import date
from pathlib import Path

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, LOGS_DIR, GOOGLE_SHEET_ID

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
Path(LOGS_DIR).mkdir(exist_ok=True)
log_file = Path(LOGS_DIR) / f"telegram_{date.today().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


# ─────────────────────────────────────────────
# TELEGRAM SEND
# ─────────────────────────────────────────────

def send_telegram(message: str, parse_mode: str = "HTML", retries: int = 3) -> bool:
    """Send a message to the configured Telegram chat."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN)
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID)

    if token == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.warning("Telegram bot token not configured — skipping send")
        logger.info("Message that would be sent:")
        logger.info(message)
        return False

    url = TELEGRAM_API.format(token=token)
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=15)
            data = resp.json()
            if resp.status_code == 200 and data.get("ok"):
                logger.info(f"Telegram message sent (attempt {attempt})")
                return True
            else:
                logger.warning(f"Telegram API error: {data.get('description', 'Unknown error')}")
        except Exception as e:
            logger.warning(f"Telegram send error (attempt {attempt}): {e}")

    logger.error("Failed to send Telegram message after all retries")
    return False


def send_error_alert(component: str, error_msg: str):
    """Send a pipeline failure alert to Telegram."""
    message = (
        f"⚠️ <b>F&O SCREENER ALERT — PIPELINE FAILURE</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 Date: {date.today().strftime('%d %b %Y')}\n"
        f"❌ Component: <b>{component}</b>\n"
        f"💬 Error: <code>{error_msg[:500]}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Please check the logs folder for details."
    )
    return send_telegram(message)


# ─────────────────────────────────────────────
# MESSAGE BUILDER
# ─────────────────────────────────────────────

def fmt_pct(val, decimals=1) -> str:
    if val is None or val == "":
        return "N/A"
    try:
        v = float(val)
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.{decimals}f}%"
    except Exception:
        return str(val)


def fmt_score(val) -> str:
    try:
        return f"{int(val)}"
    except Exception:
        return "0"


def build_morning_brief(results: dict) -> str:
    """Build the full morning brief message in Telegram HTML format."""
    macro     = results.get("macro", {})
    top_longs = results.get("top_longs", [])[:5]
    top_shorts = results.get("top_shorts", [])[:5]
    oi_alerts  = results.get("oi_alerts", [])
    trade_date = results.get("trade_date", date.today().strftime("%d %b %Y"))

    bias = macro.get("market_bias", "NEUTRAL")
    fii_fut_net = macro.get("fii_index_fut_net", 0)
    fii_dir = "Net LONG 📈" if fii_fut_net >= 0 else "Net SHORT 📉"
    fii_display = f"{fii_dir} ({abs(fii_fut_net):,.0f})"

    bias_emoji = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}.get(bias, "🟡")

    sheet_url = f"https://docs.google.com/spreadsheets/d/{os.environ.get('GOOGLE_SHEET_ID', GOOGLE_SHEET_ID)}"

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "📊 <b>F&amp;O MORNING BRIEF</b>",
        f"📅 {trade_date} | Session: Pre-market",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "🌐 <b>MACRO</b>",
        f"FII Index Futures: {fii_display}",
        f"Market Bias: {bias_emoji} <b>{bias}</b>",
        "",
        "🟢 <b>TOP 5 LONGS</b>",
    ]

    for i, s in enumerate(top_longs, 1):
        sym = s.get("SYMBOL", "N/A")
        score = fmt_score(s.get("COMPOSITE_SCORE", 0))
        signal = s.get("OI_SIGNAL", "N/A")
        oi_chg = fmt_pct(s.get("OI_CHANGE_PCT"))
        lines.append(
            f"{i}. <b>{sym}</b> | {score}/27 | {signal} | OI {oi_chg}"
        )

    lines += ["", "🔴 <b>TOP 5 SHORTS</b>"]
    for i, s in enumerate(top_shorts, 1):
        sym = s.get("SYMBOL", "N/A")
        score = fmt_score(s.get("COMPOSITE_SCORE", 0))
        signal = s.get("OI_SIGNAL", "N/A")
        oi_chg = fmt_pct(s.get("OI_CHANGE_PCT"))
        lines.append(
            f"{i}. <b>{sym}</b> | {score}/27 | {signal} | OI {oi_chg}"
        )

    lines += ["", f"⚠️ <b>OI ALERTS ({len(oi_alerts)})</b>"]
    for s in sorted(oi_alerts, key=lambda x: abs(x.get("OI_CHANGE_PCT") or 0), reverse=True)[:5]:
        sym      = s.get("SYMBOL", "N/A")
        oi_chg   = fmt_pct(s.get("OI_CHANGE_PCT"))
        px_chg   = fmt_pct(s.get("PRICE_CHANGE_PCT"))
        severity = s.get("ALERT_SEVERITY", "")
        label    = s.get("ALERT_LABEL", s.get("OI_SIGNAL", "N/A"))
        sev_tag  = "🔥" if severity == "EXTREME" else ("⚡" if severity == "HIGH" else "•")
        lines.append(f"{sev_tag} <b>{sym}</b>: OI {oi_chg}, Px {px_chg} → {label}")

    # ── Sector Rotations ─────────────────────────────
    sector_rotations = results.get("sector_rotations", [])
    if sector_rotations:
        lines += ["", "🔄 <b>SECTOR ROTATIONS</b>"]
        dir_emoji = {"↑": "🟢", "↓": "🔴"}
        for r in sector_rotations:
            emoji = dir_emoji.get(r.get("DIRECTION", ""), "•")
            lines.append(
                f"{emoji} <b>{r.get('SECTOR',''):<13}</b> "
                f"{r.get('PREV_BIAS','')} → {r.get('CURR_BIAS','')} {r.get('DIRECTION','')}"
            )

    # ── Sector Summary ───────────────────────────────
    sector_summary = results.get("sector_summary", [])
    if sector_summary:
        bias_emoji = {
            "BULLISH":      "🟢",
            "MILD BULLISH": "🟩",
            "NEUTRAL":      "⬜",
            "MILD BEARISH": "🟧",
            "BEARISH":      "🔴",
        }
        lines += ["", "🗂 <b>SECTOR BIAS</b>"]
        for sec in sector_summary:
            avg    = float(sec.get("AVG_SCORE", 0))
            bias   = sec.get("BIAS", "NEUTRAL")
            emoji  = bias_emoji.get(bias, "⬜")
            sign   = "+" if avg >= 0 else ""
            longs  = sec.get("LONGS", 0)
            shorts = sec.get("SHORTS", 0)
            lines.append(
                f"{emoji} <b>{sec.get('SECTOR',''):<13}</b> {sign}{avg:.1f} | L:{longs} S:{shorts}"
            )

    # ── Persistent Signals ───────────────────────────
    persistent_longs  = results.get("persistent_longs",  [])
    persistent_shorts = results.get("persistent_shorts", [])
    if persistent_longs or persistent_shorts:
        lines += ["", "🔁 <b>PERSISTENT SIGNALS (3+ days)</b>"]
        for s in persistent_longs[:5]:
            streak = int(s.get("PERSISTENCE", 0))
            score  = fmt_score(s.get("COMPOSITE_SCORE", 0))
            rs     = s.get("RS_SIGNAL", "")
            lines.append(f"  🟢 <b>{s.get('SYMBOL','')}</b> [P{streak}d] Score:{score} | {rs}")
        for s in persistent_shorts[:5]:
            streak = int(s.get("PERSISTENCE", 0))
            score  = fmt_score(s.get("COMPOSITE_SCORE", 0))
            rs     = s.get("RS_SIGNAL", "")
            lines.append(f"  🔴 <b>{s.get('SYMBOL','')}</b> [P{streak}d] Score:{score} | {rs}")
    else:
        lines += ["", "🔁 <b>PERSISTENT SIGNALS:</b> Building history..."]

    lines += [
        "",
        f"📱 <a href='{sheet_url}'>Full Dashboard →</a>",
        "━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    return "\n".join(lines)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def send_morning_brief(results: dict = None, json_path: str = None) -> bool:
    """Send morning brief from results dict or JSON file."""
    if results is None:
        if json_path is None:
            today = date.today().strftime("%Y%m%d")
            json_path = f"logs/screener_results_{today}.json"
        logger.info(f"Loading results from: {json_path}")
        with open(json_path) as f:
            results = json.load(f)

    message = build_morning_brief(results)
    logger.info("Sending morning brief to Telegram...")
    logger.info(f"Message preview:\n{message[:300]}...")
    return send_telegram(message)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Send Telegram morning brief")
    parser.add_argument("--json", help="Path to screener results JSON file")
    parser.add_argument("--test-error", help="Send a test error alert with this message")
    args = parser.parse_args()

    if args.test_error:
        ok = send_error_alert("TEST", args.test_error)
        sys.exit(0 if ok else 1)

    try:
        ok = send_morning_brief(json_path=args.json)
        sys.exit(0 if ok else 1)
    except Exception as e:
        logger.error(f"Telegram alert failed: {e}", exc_info=True)
        send_error_alert("telegram_alert.py", str(e))
        sys.exit(1)
