import unicodedata
from datetime import datetime, timedelta, date

# ANSI color codes for formatting
GREEN = "\033[92m"
RED = "\033[91m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"
UNDERLINE = "\033[4m"

def get_display_width(s):
    """Calculates terminal rendering width of a string containing CJK characters and emojis."""
    width = 0
    for c in s:
        val = unicodedata.east_asian_width(c)
        if val in ('W', 'F', 'A'):
            width += 2
        elif ord(c) >= 0x1F300:  # Emoji range
            width += 2
        else:
            width += 1
    return width

def pad_left(s, width):
    """Pads string with spaces on the left based on terminal display width."""
    disp_w = get_display_width(s)
    if disp_w >= width:
        return s
    return " " * (width - disp_w) + s

def pad_right(s, width):
    """Pads string with spaces on the right based on terminal display width."""
    disp_w = get_display_width(s)
    if disp_w >= width:
        return s
    return s + " " * (width - disp_w)

def pad_center(s, width):
    """Centers string inside a given width based on terminal display width."""
    disp_w = get_display_width(s)
    if disp_w >= width:
        return s
    pad_total = width - disp_w
    pad_left_cnt = pad_total // 2
    pad_right_cnt = pad_total - pad_left_cnt
    return " " * pad_left_cnt + s + " " * pad_right_cnt

def print_header(title):
    """Renders a beautifully aligned terminal box considering display width of emojis and CJK."""
    inside_width = 78
    padded_title = pad_center(title, inside_width)
    print(f"\n{BOLD}{BLUE}┌" + "─" * inside_width + "┐")
    print(f"│{padded_title}│")
    print(f"└" + "─" * inside_width + "┘" + RESET)

def format_roi_padded(roi, pnl, currency, width):
    """Pads and colors ROI percentages and PnL values considering display width before wrapping with ANSI codes."""
    if roi is None:
        return pad_left("N/A", width)
    percentage = roi * 100
    color = GREEN if percentage >= 0 else RED
    sign = "+" if percentage >= 0 else ""
    raw_str = f"{sign}{percentage:.1f}% ({pnl:+.0f} {currency})"
    padded_raw = pad_left(raw_str, width)
    return padded_raw.replace(raw_str, f"{color}{raw_str}{RESET}")

def get_progress_bar(start_date_str, total_days=30):
    """Calculates progress days and renders a beautiful progress bar."""
    try:
        # Support formats like YYYY-MM-DD_HHMMSS or standard YYYY-MM-DD safely
        start_date = datetime.strptime(start_date_str[:10], "%Y-%m-%d").date()
    except Exception:
        start_date = date.today()
        
    today = date.today()
    
    # Calculate business days (Monday to Friday) inclusive
    elapsed = 0
    if start_date <= today:
        curr = start_date
        while curr <= today:
            if curr.weekday() < 5:  # 0 is Monday, 4 is Friday
                elapsed += 1
            curr += timedelta(days=1)
            
    elapsed = max(1, elapsed)  # Day 1 start
    
    percent = min(1.0, elapsed / total_days)
    filled_length = int(total_days * percent)
    bar = "█" * filled_length + "░" * (total_days - filled_length)
    
    return elapsed, percent * 100, bar
