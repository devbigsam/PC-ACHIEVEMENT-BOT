# utils.py
def format_mc(mc):
    if mc >= 1_000_000:
        return f"${mc/1_000_000:.2f}M"
    elif mc >= 1_000:
        return f"${mc/1_000:.2f}K"
    else:
        return f"${mc:.2f}"
