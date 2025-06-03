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
from pnl_generator import generate_pnl_image
from telegram.ext import CallbackQueryHandler
from dateutil.parser import isoparse
import statistics



import functools


def with_db_connection(func):
    @functools.wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        # Adjust path to your DB file
        conn = sqlite3.connect('tracked_vip.db')
        try:
            result = await func(update, context, conn, *args, **kwargs)
            return result
        finally:
            conn.close()
    return wrapper

# === Setup ===
load_dotenv()
VIP_BOT_TOKEN = os.getenv("VIP_BOT_TOKEN")
VIP_CHANNEL_ID = int(os.getenv("VIP_CHANNEL_ID"))

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

def get_random_quote(top_token=None, highest_multiplier=None):
    try:
        with open("quotes.txt", "r", encoding="utf-8") as f:
            quotes = f.readlines()
        quote = random.choice(quotes).strip()
        if top_token:
            quote = quote.replace("{highest_ticker}", top_token).replace("{highest_multiplier}", highest_multiplier)
        return quote
    except Exception:
        return "Join the VIP club and catch them early with Big Sam. 🔥"

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
    print(f"[TRACKING] {tracked[ca]['name']} - Initial MC: {tracked[ca]['initial_mc']}")


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
                tracked[ca]["current_mult"] = multiplier
                upsert_ca(ca, info)
                
                caption = f"""
🚀 <b>VIP UPDATE</b>
                
Name: {info['name']}
                
Symbol: ${info['symbol']}
                
💵 <b>{next_target}x from Entry!!</b>
                
From {format_mc(start)} ➡️ {format_mc(current)} 🤯
                
📊 <b><a href="https://dexscreener.com/solana/{ca}">View Stats</a></b> | 🖼️ <b><a href="https://t.me/bigsamachievement_bot?start={ca}">View PNL</a></b>
"""
                
                photo_path = "gifs/general-update.png"  
                if os.path.exists(photo_path):
                    await app.bot.send_photo(
                        chat_id=VIP_CHANNEL_ID,
                        photo=open(photo_path, "rb"),
                        caption=caption.strip(),
                        parse_mode=ParseMode.HTML,
                        reply_to_message_id=info["message_id"],  # Reply to initial message
                        )
                else:
                    await app.bot.send_message(
                        chat_id=VIP_CHANNEL_ID,
                        text=caption.strip(),
                        parse_mode=ParseMode.HTML,
                        reply_to_message_id=info["message_id"],  # Reply to initial message
                        )
                    print(f"[VIP UPDATE] {ca} - {next_target}x")

        await asyncio.sleep(60)

from telegram.ext import CommandHandler

def delete_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🗑️", callback_data="delete")]])

async def pnl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /pnl <contract_address or symbol>", reply_markup=delete_button())
        return

    query = args[0]
    tracked = get_tracked()

    # First, try direct CA lookup (case-sensitive)
    ca_data = tracked.get(query)

    # If not found by CA, try matching symbol (case-insensitive)
    if not ca_data:
        query_lower = query.lower()
        for data in tracked.values():
            if data["symbol"].lower() == query_lower:
                ca_data = data
                break

    if not ca_data:
        await update.message.reply_text("❌ Coin not found. Can't generate flex.", reply_markup=delete_button())
        return

    bio = await generate_pnl_image(ca_data)
    if bio is None:
        await update.message.reply_text("❌ PNL templates missing, cannot generate image.", reply_markup=delete_button())
        return

    await update.message.reply_photo(photo=bio, reply_markup=delete_button(), reply_to_message_id=update.message.message_id)


async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # Acknowledge the callback

    # Delete the message with the button (the reply)
    await query.message.delete()

    # Also delete the message it was replying to, if any
    if query.message.reply_to_message:
        await query.message.reply_to_message.delete()
        

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE,):
    args = context.args
    if args:
        arg0 = args[0]

        if arg0.startswith("gpnl_"):
            # Extract timeframe from deep link, e.g. "gpnl_1d" -> "1d"
            timeframe_arg = arg0[5:]

            # Temporarily replace context.args with [timeframe_arg] for gpnl_command
            old_args = context.args
            context.args = [timeframe_arg]

            await gpnl_command(update, context, add_delete_button=False)  # no keyword argument here

            # Restore original args after
            context.args = old_args
            return

        else:
            # Assume arg0 is a contract address for the flex image
            ca = arg0
            tracked = get_tracked()
            if ca not in tracked:
                await update.message.reply_text("❌ Coin not found. Can't generate flex.")
                return

            bio = await generate_pnl_image(tracked[ca])
            if bio is None:
                await update.message.reply_text("❌ PNL templates missing, cannot generate image.")
                return

            await update.message.reply_photo(photo=bio)
    else:
        await update.message.reply_text(
            "Welcome to BIG SAM PRIVATE CLUB ACHIEVEMENT BOT (Still on Beta Mode)!\n\n"
            "Use /pnl <contract_address> to flex our calls."
        )

from datetime import datetime, timedelta, timezone

def parse_timeframe(arg):
    now = datetime.now(timezone.utc)

    arg = arg.lower().replace("h", "hr") if "h" in arg and not arg.endswith("hr") else arg

    # Special case for fixed 1d reset (midnight UTC)
    if arg == "1d":
        return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)

    mapping = {
        '2d': timedelta(days=2),
        '4d': timedelta(days=4),
        '7d': timedelta(days=7),
        '14d': timedelta(days=14),
        '1mo': timedelta(days=30),
        '2mo': timedelta(days=60),
        '4mo': timedelta(days=120),
        '6mo': timedelta(days=180),
        '1yr': timedelta(days=365)
    }

    # Add 1hr to 24hr
    for hr in range(1, 25):  # includes 24hr now
        mapping[f"{hr}hr"] = timedelta(hours=hr)

    return now - mapping.get(arg, timedelta(days=1))  # default is rolling 24h


def parse_posted_at(posted_at_raw):
    if isinstance(posted_at_raw, int):
        # Assume UNIX timestamp (seconds)
        return datetime.fromtimestamp(posted_at_raw, tz=timezone.utc)
    elif isinstance(posted_at_raw, str):
        try:
            # Try ISO 8601 parsing, fix trailing Z if needed
            posted_at_fixed = posted_at_raw.replace("Z", "+00:00")
            return datetime.fromisoformat(posted_at_fixed).astimezone(timezone.utc)
        except Exception:
            # Fallback: try dateutil's parser if available
            try:
                return isoparse(posted_at_raw).astimezone(timezone.utc)
            except Exception as e:
                print(f"Failed to parse ISO timestamp {posted_at_raw}: {e}")
                return None
    else:
        print(f"Unknown posted_at format: {posted_at_raw} ({type(posted_at_raw)})")
        return None

@with_db_connection
async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE, conn):
    args = context.args
    timeframe_arg = args[0] if args else '1d'
    cutoff = parse_timeframe(timeframe_arg)

    cursor = conn.cursor()
    cursor.execute("SELECT ca, name, symbol, multipliers, posted_at FROM tracked")
    all_rows = cursor.fetchall()

    valid_rows = []
    for ca, name, symbol, multipliers_json, posted_at_raw in all_rows:
        posted_at = parse_posted_at(posted_at_raw)
        if posted_at is None:
            print(f"[ERROR] Skipping {ca} due to bad timestamp: {posted_at_raw}")
            continue
        if posted_at >= cutoff:
            valid_rows.append((ca, name, symbol, multipliers_json, posted_at))

    if not valid_rows:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑", callback_data='delete_lb')]
        ])
        await update.message.reply_text(
            "No tracked tokens in that timeframe.",
            reply_markup=keyboard
        )
        return

    calls = []
    total_return = 0
    hits = 0
    
    multipliers_max = [max(json.loads(m_json)) for _, _, _, m_json, _ in valid_rows if json.loads(m_json)]

    multipliers_max.sort()

    n = len(multipliers_max)
    if n == 0:
        median = 0
    elif n % 2 == 1:
        median = multipliers_max[n // 2]
    else:
        median = (multipliers_max[(n // 2) - 1] + multipliers_max[n // 2]) / 2


    for ca, name, symbol, multipliers_json, _ in valid_rows:
        multipliers = json.loads(multipliers_json)
        if multipliers:
            max_x = max(multipliers)
        else:
            max_x = 0  # No multipliers recorded yet
        total_return += max_x
        if max_x >= 2:
            hits += 1
        calls.append((max_x, name, symbol, ca))
        
        
    calls.sort(reverse=True, key=lambda x: x[0])
    total_calls = len(calls)
    average_return = total_return / total_calls if total_calls else 0
    hit_rate = hits / total_calls if total_calls else 0
    top_10 = calls[:10]
    
    bot_username = "bigsamachievement_bot"  # replace with your bot's username without @
    timeframe_for_link = timeframe_arg if timeframe_arg else "1d"

    header_link = (
    f'<b><a href="https://t.me/{bot_username}?start=gpnl_{timeframe_for_link}">'
    "BIG SAM PRIVATE CLUB 💎👾⚡️</a></b>"
)


    # Your existing lines for stats
    lines = [
    f"🏰 {header_link}\n",
    "📊 <b>PRIVATE CLUB STATS</b>",
    f" ├ <code>Period</code>: <b>{timeframe_arg}</b>",
    f" ├ <code>Calls</code>: <b>{total_calls}</b>",
    f" ├ <code>Hit Rate</code>: <b>{hit_rate:.0%}</b>",
    f" ├ <code>Median</code>: <b>{median:.1f}x</b>",
    f" └ <code>Return</code>: <b>{total_return:.1f}x</b> (Avg:{average_return:.1f}x)",
]
    
    emojis = ['🔥❤️‍🔥', '🚀😎', '💎⚡️', '👾🔥', '💊👾', '💊👾', '🚀😎', '💊👾', '🏆❤️‍🔥', '🔥🚀']
    blockquote_lines = []
    for i, (max_x, name, symbol, ca) in enumerate(top_10, 1):
        emoji = emojis[i-1]
        url = f"https://dexscreener.com/solana/{ca}"
        blockquote_lines.append(f"<b>{emoji}{i}. <a href='{url}'>${symbol}</a> » BIG SAM PRIVATE CLUB 💎👾⚡️ [{max_x:}x]</b>")
        
    lines.append("<blockquote>" + "\n".join(blockquote_lines) + "\n</blockquote>")
    lines.append(f'\n<b><a href="https://x.com/bigsamkoll">📚 Learn More...</a></b>')

        
    quote_text = "\n".join(lines); "\n"
    
        
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️", callback_data="delete_lb")]
    ])

    await update.message.reply_text(
        quote_text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=keyboard
    )


async def delete_leaderboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        await query.message.delete()
        if query.message.reply_to_message:
            await query.message.reply_to_message.delete()
    except Exception as e:
        print(f"Error deleting messages: {e}")

from gpnl_generator import generate_gpnl_image
from telegram import Update
from telegram.ext import ContextTypes

@with_db_connection
async def gpnl_command(update: Update, context: ContextTypes.DEFAULT_TYPE, conn, add_delete_button=True):
    args = context.args
    timeframe_arg = args[0] if args else '1d'
    cutoff = parse_timeframe(timeframe_arg)  # reuse your existing timeframe parser

    cursor = conn.cursor()
    cursor.execute("SELECT ca, name, symbol, multipliers, posted_at FROM tracked")
    all_rows = cursor.fetchall()

    valid_rows = []
    for ca, name, symbol, multipliers_json, posted_at_raw in all_rows:
        posted_at = parse_posted_at(posted_at_raw)
        if posted_at is None:
            continue
        if posted_at >= cutoff:
            valid_rows.append((ca, name, symbol, multipliers_json, posted_at))

    if not valid_rows:
        await update.message.reply_text("No calls found in that timeframe.")
        return

    calls = []
    total_return = 0
    hits = 0

    multipliers_max = [max(json.loads(m_json)) for _, _, _, m_json, _ in valid_rows if json.loads(m_json)]
    multipliers_max.sort()
    n = len(multipliers_max)
    median = multipliers_max[n // 2] if n % 2 == 1 else (multipliers_max[(n // 2) - 1] + multipliers_max[n // 2]) / 2 if n else 0

    for ca, name, symbol, multipliers_json, _ in valid_rows:
        multipliers = json.loads(multipliers_json)
        max_x = max(multipliers) if multipliers else 0
        total_return += max_x
        if max_x >= 2:
            hits += 1
        calls.append((max_x, name, symbol, ca))

    calls.sort(reverse=True, key=lambda x: x[0])

    total_calls = len(calls)
    average_return = total_return / total_calls if total_calls else 0
    hit_rate = hits / total_calls if total_calls else 0

    top_3 = calls[:3]

    img_bytes = generate_gpnl_image(top_3, total_calls, hit_rate, average_return, median, total_return, timeframe_arg)
    
    reply_markup = get_delete_keyboard() if add_delete_button else None
    await update.message.reply_photo(photo=img_bytes, parse_mode='HTML', reply_markup=reply_markup)

def get_delete_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🗑", callback_data="delete_gpnl")]])

async def delete_gpnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        await context.bot.delete_message(chat_id=query.message.chat.id, message_id=query.message.message_id)
        if query.message.reply_to_message:
            await context.bot.delete_message(chat_id=query.message.chat.id, message_id=query.message.reply_to_message.message_id)
    except Exception as e:
        print(f"Delete failed: {e}")

# === Main ===
def main():
    init_db()
    app = ApplicationBuilder().token(VIP_BOT_TOKEN).build()
    app.add_handler(CommandHandler("pnl", pnl_command))
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(delete_leaderboard_callback, pattern="^delete_lb$"))
    app.add_handler(CallbackQueryHandler(delete_gpnl, pattern="^delete_gpnl$"))

    app.add_handler(CommandHandler("gpnl", gpnl_command))

    app.add_handler(CommandHandler("lb", leaderboard_command))

    app.add_handler(CallbackQueryHandler(delete_callback, pattern="^delete$"))

    app.add_handler(MessageHandler(filters.Chat(VIP_CHANNEL_ID) & filters.TEXT, handle_vip_message))

    # Start background tasks after bot is running
    async def on_startup(app):
        asyncio.create_task(monitor_multipliers(app))

    app.post_init = on_startup

    print("[BOT] Starting...")
    app.run_polling()  # This blocks and handles its own event loop

if __name__ == "__main__":
    main()
