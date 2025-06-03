from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import random

# Load fonts (ensure these paths are correct for your system)
TITLE_FONT = "./fonts/LuckiestGuy-Regular.ttf"
CALL_FONT = "./fonts/Fredoka.ttf"
X_FONT = "./fonts/ttm.ttf"
STATS_FONT = "./fonts/Fredoka.ttf"

TITLE_FONT_SIZE = 90
CALL_FONT_SIZE = 50
X_FONT_SIZE = 120
STATS_FONT_SIZE = 26
STATS_VALUE_FONT_SIZE = 32

title_font = ImageFont.truetype(TITLE_FONT, TITLE_FONT_SIZE)
call_font = ImageFont.truetype(CALL_FONT, CALL_FONT_SIZE)
x_font = ImageFont.truetype(X_FONT, X_FONT_SIZE)
stats_label_font = ImageFont.truetype(STATS_FONT, STATS_FONT_SIZE)
stats_value_font = ImageFont.truetype(STATS_FONT, STATS_VALUE_FONT_SIZE)

# Light green used in Phanes' image
GREEN = "#00FF00"
WHITE = "white"

def generate_gpnl_image(top_calls, total_calls, hit_rate, avg_return, median_return, total_return, timeframe_arg):
    # Choose template
    template_path = f"gpnl_templates/template_{random.choice([1, 2, 3])}.png"
    base_img = Image.open(template_path).convert("RGBA")
    draw = ImageDraw.Draw(base_img)
    img_w, img_h = base_img.size

    # HEADER
    header_text = "BIG SAM PRIVATE CLUB"
    bbox = draw.textbbox((0, 0), header_text, font=title_font)
    header_x = (img_w - (bbox[2] - bbox[0])) / 2
    draw.text((header_x, 40), header_text, font=title_font, fill=GREEN)

    # SUMMARY
    summary_text = f"{total_return:}x  {timeframe_arg}"
    bbox = draw.textbbox((0, 0), summary_text, font=x_font)
    summary_x = (img_w - (bbox[2] - bbox[0])) / 2
    draw.text((summary_x, 110), summary_text, font=x_font, fill=GREEN)

    # TOP CALLS
    y = 270
    spacing = 80
    
    for max_x, name, symbol, ca in top_calls[:3]:
        call_text = f"PRIVATE CLUB : ${symbol.upper()}"
        call_bbox = draw.textbbox((0, 0), call_text, font=call_font)
        call_width = call_bbox[2] - call_bbox[0]

        x_multiplier_text = f"{max_x:}X"
        x_bbox = draw.textbbox((0, 0), x_multiplier_text, font=call_font)
        x_width = x_bbox[2] - x_bbox[0]

        total_width = call_width + 10 + x_width  # 10 px spacing between text and multiplier

        start_x = (img_w - total_width) / 2

        # Draw the call text (without multiplier)
        draw.text((start_x, y), call_text, font=call_font, fill=WHITE)

        # Draw the multiplier in green, right after call text + 10px
        draw.text((start_x + call_width + 10, y), x_multiplier_text, font=call_font, fill=GREEN)

        y += spacing

    # FOOTER STATS
    stat_labels = ["Total Calls", "Hit Rate", "Avg Return", "Median Return"]
    stat_values = [
        str(total_calls),
        f"{hit_rate:.0%}",
        f"{avg_return:.1f}x",
        f"{median_return:.1f}x"
    ]

    # Calculate equal spacing across the image
    label_y = img_h - 110
    value_y = label_y + 30
    num_stats = len(stat_labels)
    spacing = img_w // num_stats

    for i in range(num_stats):
        label = stat_labels[i]
        value = stat_values[i]

        label_bbox = draw.textbbox((0, 0), label, font=stats_label_font)
        value_bbox = draw.textbbox((0, 0), value, font=stats_value_font)

        center_x = (spacing * i) + (spacing // 2)

        label_x = center_x - (label_bbox[2] - label_bbox[0]) / 2
        value_x = center_x - (value_bbox[2] - value_bbox[0]) / 2

        draw.text((label_x, label_y), label, font=stats_label_font, fill=WHITE)
        draw.text((value_x, value_y), value, font=stats_value_font, fill=WHITE)

    # Save image to memory
    output = BytesIO()
    base_img.save(output, format="PNG")
    output.seek(0)
    return output
