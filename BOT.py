import os
import re
import time
import json
import sqlite3
import asyncio
import random
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from telegram.error import TimedOut, RetryAfter, TelegramError

# === Load Environment ===
load_dotenv()
BOT_TOKEN = os.getenv("VIP_BOT_TOKEN")
VIP_CHANNEL_ID = int(os.getenv("VIP_CHANNEL_ID"))

# === Pattern for Solana CAs ===
CA_PATTERN = r"\b[a-zA-Z0-9]{44}\b"

# === SQLite DB ===
DB_FILE = "vip_tracked.db"
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vip_contracts (
            ca TEXT PRIMARY KEY,
            name TEXT,
            symbol TEXT,
            initial_mc REAL,
            multipliers TEXT,
            timestamp INTEGER,
            ath_mc REAL
        )
    """)
    conn.commit()
    conn.close()

def get_tracked():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vip_contracts")
    rows = cursor.fetchall()
    conn.close()
    return {
        row[0]: {
            "name": row[1], "symbol": row[2], "initial_mc": row[3],
            "multipliers": json.loads(row[4] or "[]"), "timestamp": row[5], "ath_mc": row[6]
        } for row in rows
    }

def upsert(ca, data):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO vip_contracts (ca, name, symbol, initial_mc, multipliers, timestamp, ath_mc)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ca) DO UPDATE SET
            name=excluded.name,
            symbol=excluded.symbol,
            initial_mc=excluded.initial_mc,
            multipliers=excluded.multipliers,
            timestamp=excluded.timestamp,
            ath_mc=excluded.ath_mc
    """, (
        ca, data["name"], data["symbol"], data["initial_mc"],
        json.dumps(data.get("multipliers", [])), data["timestamp"], data["ath_mc"]
    ))
    conn.commit()
    conn.close()

def format_mc(value):
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    elif value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    elif value >= 1_000:
        return f"{value / 1_000:.2f}K"
    return f"{value:.2f}"

CHAIN_ID = "solana"
async def fetch_data(ca):
    try:
        dex_url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}"
        res = requests.get(dex_url).json()
        if "pairs" in res and res["pairs"]:
            pair = res["pairs"][0]
            base = pair.get("baseToken", {})
            return {
                "name": base.get("name", "Unknown"),
                "symbol": base.get("symbol", ""),
                "mc": pair.get("fdv", 0)
            }
    except Exception as e:
        print(f"[ERROR] API fail: {e}")
    return None

# === Message Handler ===
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != VIP_CHANNEL_ID:
        return

    text = update.effective_message.text or update.effective_message.caption or ""
    match = re.findall(CA_PATTERN, text)
    if not match:
        return

    ca = match[0]
    tracked = get_tracked()
    if ca in tracked:
        return

    data = await fetch_data(ca)
    if data and data["mc"]:
        new_entry = {
            "name": data["name"], "symbol": data["symbol"],
            "initial_mc": data["mc"], "multipliers": [],
            "timestamp": int(time.time()), "ath_mc": data["mc"]
        }
        upsert(ca, new_entry)
        print(f"[TRACKING] {ca} | {data['symbol']} | {format_mc(data['mc'])}")
    else:
        print(f"[SKIP] No valid MC for {ca}")

# === Send Animation with Retry ===
async def safe_send(bot, chat_id, gif_path, caption, markup=None):
    try:
        with open(gif_path, "rb") as gif:
            await bot.send_animation(chat_id=chat_id, animation=gif, caption=caption, parse_mode=ParseMode.HTML, reply_markup=markup)
    except (RetryAfter, TimedOut) as e:
        delay = getattr(e, "retry_after", 5)
        print(f"[RETRY] Delay {delay}s")
        await asyncio.sleep(delay)
        await safe_send(bot, chat_id, gif_path, caption, markup)
    except Exception as e:
        print(f"[FAIL] Send error: {e}")

# === Multiplier Checker ===
async def check_multipliers(app):
    while True:
        tracked = get_tracked()
        for ca, info in tracked.items():
            if time.time() - info["timestamp"] > 30 * 86400:
                print(f"[EXPIRE] {ca}")
                continue

            data = await fetch_data(ca)
            if not data or not data.get("mc"):
                continue

            start = info["initial_mc"]
            current = data["mc"]
            ath = info.get("ath_mc", start)
            if current > ath:
                info["ath_mc"] = current

            multiplier = current / start if start else 0
            next_x = int(multiplier)
            if next_x > max(info.get("multipliers", []), default=1):
                info["multipliers"].append(next_x)
                upsert(ca, info)

                msg = f"""
🚀 <b>VIP UPDATE</b>

Name: {info['name']}

Symbol: ${info['symbol']}

💵 <b>{next_x}x From Entry</b>

{format_mc(start)} ➡️ {format_mc(current)} 🤯
"""

                photo_path = "gifs/general-update.png"
                if os.path.exists(photo_path):
                    with open(photo_path, "rb") as photo:
                        await app.bot.send_photo(chat_id=VIP_CHANNEL_ID, photo=photo, caption=msg.strip(), parse_mode=ParseMode.HTML)
                else:
                    await app.bot.send_message(chat_id=VIP_CHANNEL_ID, text=msg.strip(), parse_mode=ParseMode.HTML)
                    print(f"[VIP UPDATE] {ca} - {next_x}x")


        await asyncio.sleep(60)

# === App Runner ===
async def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.ALL, handle_msg))
    asyncio.create_task(check_multipliers(app))
    print("[VIP BOT STARTED]")
    await app.run_polling()

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(main())
