import os
import re
import json
import time
import random
import sqlite3
import asyncio
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

# === Setup ===
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
VIP_CHANNEL_ID = int(os.getenv("VIP_CHANNEL_ID"))
VIP_CHANNEL_USERNAME = os.getenv("VIP_CHANNEL_USERNAME", "yourvipchannel")

CA_PATTERN = r"\b[a-zA-Z0-9]{44}\b"
DB_FILE = "tracked_vip.db"

# === Database ===
def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tracked (
            ca TEXT PRIMARY KEY,
            name TEXT,
            symbol TEXT,
            initial_mc REAL,
            multipliers TEXT,
            posted_at INTEGER,
            message_id INTEGER
        )
    """)
    conn.commit()
    conn.close()

def get_tracked():
    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute("SELECT * FROM tracked").fetchall()
    conn.close()
    return {row[0]: {
        "name": row[1],
        "symbol": row[2],
        "initial_mc": row[3],
        "multipliers": json.loads(row[4] or "[]"),
        "posted_at": row[5],
        "message_id": row[6]
    } for row in rows}

def upsert_ca(ca, data):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        INSERT INTO tracked (ca, name, symbol, initial_mc, multipliers, posted_at, message_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ca) DO UPDATE SET
        name=excluded.name,
        symbol=excluded.symbol,
        initial_mc=excluded.initial_mc,
        multipliers=excluded.multipliers,
        posted_at=excluded.posted_at,
        message_id=excluded.message_id
    """, (
        ca,
        data["name"],
        data["symbol"],
        data["initial_mc"],
        json.dumps(data.get("multipliers", [])),
        data.get("posted_at"),
        data.get("message_id")
    ))
    conn.commit()
    conn.close()

# === Utils ===
def format_mc(mc):
    if mc >= 1_000_000_000:
        return f"{mc / 1_000_000_000:.2f}B"
    elif mc >= 1_000_000:
        return f"{mc / 1_000_000:.2f}M"
    elif mc >= 1_000:
        return f"{mc / 1_000:.2f}K"
    return f"{mc:.2f}"

def get_random_quote():
    with open("quotes.txt", "r", encoding="utf-8") as f:
        quotes = f.readlines()
    return random.choice(quotes).strip()


async def fetch_token_data(ca):
    try:
        res = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}")
        data = res.json()
        if not data.get("pairs"):
            return None
        pair = data["pairs"][0]
        return {
            "name": pair["baseToken"]["name"],
            "symbol": pair["baseToken"]["symbol"],
            "mc": pair.get("fdv", 0)
        }
    except Exception as e:
        print(f"[ERROR] fetch_token_data: {e}")
        return None

# === Handlers ===
async def handle_vip_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if msg.chat.id != VIP_CHANNEL_ID:
        return

    text = msg.text or msg.caption or ""
    matches = re.findall(CA_PATTERN, text)
    if not matches:
        return

    ca = matches[0]
    tracked = get_tracked()
    if ca in tracked:
        return

    data = await fetch_token_data(ca)
    if not data or not data.get("mc"):
        return

    tracked[ca] = {
        "name": data["name"],
        "symbol": data["symbol"],
        "initial_mc": data["mc"],
        "multipliers": [],
        "posted_at": int(time.time()),
        "message_id": msg.message_id  # Save initial post message ID here
    }
    upsert_ca(ca, tracked[ca])
    print(f"[TRACKING] {ca} - {data['name']}")

async def monitor_multipliers(app):
    while True:
        tracked = get_tracked()
        for ca, info in tracked.items():
            token = await fetch_token_data(ca)
            if not token or not token.get("mc"):
                continue

            start = info["initial_mc"]
            current = token["mc"]
            if not start:
                continue

            multiplier = current / start
            next_target = int(multiplier)

            if next_target > max(info["multipliers"], default=1):
                info["multipliers"].append(next_target)
                upsert_ca(ca, info)

                caption = f"""
🚀 <b>VIP UPDATE</b>

Name: {info['name']}

Symbol: ${info['symbol']}

💵 <b>{next_target}x from Entry !!</b>

From {format_mc(start)} ➡️ {format_mc(current)} 🤯

📊 <a href="https://dexscreener.com/solana/{ca}">View Stats</a>
"""

            
                # Send image instead of GIF
                image_path = "images/general-update.png"  # Change path as needed
                if os.path.exists(image_path):
                    with open(image_path, "rb") as img_file:
                        await app.bot.send_photo(
                            chat_id=VIP_CHANNEL_ID,
                            photo=img_file,
                            caption=caption.strip(),
                            parse_mode=ParseMode.HTML,
                            reply_to_message_id=info["message_id"],
        
                        )
                else:
                    await app.bot.send_message(
                        chat_id=VIP_CHANNEL_ID,
                        text=caption.strip(),
                        parse_mode=ParseMode.HTML,
                        reply_to_message_id=info["message_id"],
                      
                    )

                print(f"[VIP UPDATE] {ca} - {next_target}x")
        await asyncio.sleep(60)

# === Daily Summary ===
async def send_daily_summary(app):
    while True:
        now = datetime.now(timezone.utc)
        next_run = datetime.combine(now.date(), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=23, minutes=58)
        if now >= next_run:
            next_run += timedelta(days=1)
        await asyncio.sleep((next_run - now).total_seconds())

        print("[DAILY] Generating VIP daily summary...")
        tracked = get_tracked()

        today_start = int(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        today_calls = [
            data for data in tracked.values()
            if data.get("posted_at") and data["posted_at"] >= today_start
        ]

        total = len(today_calls)
        hits = [(c["symbol"], max(c["multipliers"])) for c in today_calls if any(x >= 2 for x in c["multipliers"])]
        hit_rate = round((len(hits) / total * 100), 1) if total else 0
        top_5 = sorted(hits, key=lambda x: x[1], reverse=True)[:5]

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        msg = f"""📊 <b>VIP Daily Report | PRIVATE CLUB</b>

📅 Date: {today_str}

📈 Total Calls: {total}

🔥 Hit Rate: {hit_rate}%

<b>Top 5 VIP Plays:</b>"""
        if top_5:
            for i, (sym, multi) in enumerate(top_5, 1):
                msg += f"\n{i}. ${sym} – {multi:.1f}x"
                
            msg += f"\n\n{get_random_quote}"
        else:
            msg += "\n\There were no winnings today 😓. Let's push harder tomorrow 💪!!"


        image_path = "images/daily-report.png"  # Change path as needed
        if os.path.exists(image_path):
            with open(image_path, "rb") as img_file:
                await app.bot.send_photo(
                    chat_id=VIP_CHANNEL_ID,
                    photo=img_file,
                    caption=msg,
                    parse_mode=ParseMode.HTML,
                   
                )
        else:
            await app.bot.send_message(
                chat_id=VIP_CHANNEL_ID,
                text=msg,
                parse_mode=ParseMode.HTML,
               
            )
        print("[DAILY] VIP report sent.")

# === Main ===
async def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Register handler for VIP channel messages (for tracking CA)
    app.add_handler(MessageHandler(filters.Chat(chat_id=VIP_CHANNEL_ID) & (filters.TEXT | filters.Caption), handle_vip_message))

    # Start background tasks for monitoring and daily summary
    async def background_tasks():
        await asyncio.gather(
            monitor_multipliers(app),
            send_daily_summary(app),
        )

    # Run the bot and background tasks concurrently
    await asyncio.gather(
        app.start(),
        background_tasks()
    )

    # Properly stop the bot on exit (optional)
    await app.stop()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
