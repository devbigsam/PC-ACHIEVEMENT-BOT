from PIL import Image, ImageDraw, ImageFont
import random
import io
import os
from utils import format_mc

def get_text_size(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]

async def generate_pnl_image(ca_data):
    # Pick random template
    template_num = random.randint(1, 5)
    template_path = f"pnl_templates/pnl_template_{template_num}.png"

    if not os.path.exists(template_path):
        print(f"[PNL] Template {template_path} not found.")
        return None

    image = Image.open(template_path).convert("RGBA")
    draw = ImageDraw.Draw(image)

    # Load fonts
    try:
        font_path = "./fonts/LuckiestGuy-Regular.ttf"  # ticker
        font_path2 = "./fonts/Fredoka.ttf"             # footer & called at
        font_path3 = "./fonts/ttm.ttf"                  # multiplier
        font_large = ImageFont.truetype(font_path, 72)
        font_medium = ImageFont.truetype(font_path2, 36)
        font_mult = ImageFont.truetype(font_path3, 120)
    except Exception:
        font_large = font_medium = font_mult = ImageFont.load_default()

    symbol_text = f"${ca_data['symbol']}"
    mc_text = f"Called at {format_mc(ca_data['initial_mc'])}"
    max_mult = max(ca_data["multipliers"]) if ca_data["multipliers"] else 1
    mult_text = f"{max_mult}x"
    footer_text = "BIG SAM PRIVATE CLUB"  # No emoji here, we will paste the emoji image

    width, height = image.size

    # Padding and spacing
    padding_right = 100
    padding_top = 150
    spacing = 15

    # --- Draw ticker top right ---
    w_sym, h_sym = get_text_size(draw, symbol_text, font_large)
    x_sym = width - w_sym - padding_right
    y_sym = padding_top
    draw.text((x_sym, y_sym), symbol_text, font=font_large, fill="white")

    # --- Draw called at below ticker, top right aligned ---
    w_mc, h_mc = get_text_size(draw, mc_text, font_medium)
    x_mc = width - w_mc - padding_right
    y_mc = y_sym + h_sym + spacing
    draw.text((x_mc, y_mc), mc_text, font=font_medium, fill="white")

    # --- TWEAKED: Draw multiplier right aligned near right edge ---
    w_mult, h_mult = get_text_size(draw, mult_text, font_mult)
    x_mult = width - w_mult - padding_right  # right align multiplier text
    y_mult = y_mc + h_mc + 5 * spacing
    draw.text((x_mult, y_mult), mult_text, font=font_mult, fill="green")

    # --- Draw footer bottom right with emoji icon ---
    w_foot, h_foot = get_text_size(draw, footer_text, font_medium)
    
    # Load emoji icon image (TWEAK)
    try:
        emoji_icon = Image.open("./fonts/icon.png").convert("RGBA")  # <-- put your emoji png file here
        emoji_size = h_foot  # make emoji height same as footer text height
        emoji_icon = emoji_icon.resize((emoji_size, emoji_size), Image.Resampling.LANCZOS)
    except Exception as e:
        print("[PNL] Emoji icon not found or failed to load:", e)
        emoji_icon = None

    # Calculate positions
    total_width = w_foot + (emoji_icon.width if emoji_icon else 0) + 10  # 10 px spacing between emoji and text
    x_foot = width - total_width - padding_right
    y_foot = height - h_foot - padding_top

    # Paste emoji icon if loaded
    if emoji_icon:
        emoji_y = y_foot + 10  # align top with footer text
        image.paste(emoji_icon, (int(x_foot), int(emoji_y)), emoji_icon)
        x_foot += emoji_icon.width + 10  # shift text right after emoji

    draw.text((x_foot, y_foot), footer_text, font=font_medium, fill="white")

    bio = io.BytesIO()
    bio.name = "pnl.png"
    image.save(bio, "PNG")
    bio.seek(0)
    return bio
