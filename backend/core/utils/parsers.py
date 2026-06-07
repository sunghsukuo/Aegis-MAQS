import re

def format_markdown_for_terminal(text: str) -> str:
    """
    Converts markdown syntax into clean, professional plain text for terminal reading.
    Strips raw markdown markers like #, *, _, and replaces bold markers with clean layouts.
    """
    lines = text.split("\n")
    formatted_lines = []
    for line in lines:
        # 1. Convert headers: '### Header' -> '【 Header 】'
        header_match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if header_match:
            level = len(header_match.group(1))
            content = header_match.group(2)
            # Strip styling from header content
            content = content.replace("*", "").replace("_", "")
            if level <= 3:
                formatted_lines.append(f"\n\033[1;32m【 {content} 】\033[0m")
            else:
                formatted_lines.append(f"\n\033[1;36m  {content}\033[0m")
            continue
            
        # 2. Identify and convert bullet points first
        bullet_match = re.match(r"^(\s*)[\*\-+]\s+(.*)$", line)
        if bullet_match:
            indent = bullet_match.group(1)
            content = bullet_match.group(2)
            
            # Replace multiplication asterisks in formulas with "×"
            content = re.sub(r"(\b\w+|\d+)\s*\*\s*(\b\w+|\d+)", r"\1 × \2", content)
            # Strip all other markdown asterisks/underscores in bullet content
            content = content.replace("*", "").replace("_", "")
            
            formatted_lines.append(f"{indent}▪ {content}")
        else:
            # Replace multiplication asterisks in formulas with "×"
            line = re.sub(r"(\b\w+|\d+)\s*\*\s*(\b\w+|\d+)", r"\1 × \2", line)
            line = line.replace("*", "").replace("_", "")
            formatted_lines.append(line)
            
    return "\n".join(formatted_lines)


def extract_price_from_line(line: str, current_price: float, is_target: bool = None) -> float:
    """
    Robustly extracts the target price or stop-loss price from a line of markdown text,
    filtering out small integers (like 10, 15, 200) representing days, weights, or SMA indicators,
    rejecting general discussion/strategy lines containing irrelevant numbers (e.g., PEG, history tickers),
    and returns the value that is closest to the current stock price.
    """
    # Reject lines that are clearly discussion/macro paragraphs rather than direct recommendations.
    # If the line is a formatted bullet point (e.g. starting with '*' and containing '**'), bypass this filter.
    is_guide_line = line.strip().startswith("*") and "**" in line
    if not is_guide_line:
        reject_keywords = ["策略", "回測", "分析師共識", "歷史", "區間為", "大盤", "年增率", "避免買入", "觸及上限"]
        if any(k in line for k in reject_keywords):
            return 0.0

    # Regex to find all numbers, including decimals and handling commas
    numbers = re.findall(r"(?:\$|NT\$|元)?\s*([\d,]+\.?[\d]*)\s*(?:元|%)?", line)
    valid_prices = []
    
    for num_str in numbers:
        num_str_clean = num_str.replace(",", "")
        if not num_str_clean:
            continue
        try:
            # Prevent matching leading-zero ticker numbers like 0050
            if num_str.startswith("00") and len(num_str_clean) >= 4:
                continue
                
            val = float(num_str_clean)
            # Filter out standard non-price metrics (e.g. 50-day, 200-day, 10% weight) 
            if val in [5.0, 10.0, 15.0, 20.0, 50.0, 200.0]:
                if current_price and abs(val - current_price) / current_price > 0.5:
                    continue
            
            # Directional validation:
            # Target price must be strictly greater than current price.
            # Stop loss must be strictly less than current price.
            if current_price:
                if is_target is True and val <= current_price:
                    continue
                if is_target is False and val >= current_price:
                    continue
                    
            valid_prices.append(val)
        except ValueError:
            continue
            
    if valid_prices:
        if current_price:
            closest_price = min(valid_prices, key=lambda x: abs(x - current_price))
            if abs(closest_price - current_price) / current_price < 0.6:
                return closest_price
            return 0.0  # Reject values that are too far away
        return valid_prices[-1]  # Fallback to the last matched number
    return 0.0



def extract_range_from_line(line: str, current_price: float) -> str:
    """
    Robustly extracts the buy range (low and high price) from a markdown line,
    filtering out typical non-price constants like SMAs (50, 200) and weights,
    and returns a formatted range string: 'low - high'.
    """
    numbers = re.findall(r"(?:\$|NT\$|元)?\s*([\d,]+\.?[\d]*)\s*(?:元|%)?", line)
    valid_nums = []
    
    for num_str in numbers:
        num_str_clean = num_str.replace(",", "")
        if not num_str_clean:
            continue
        try:
            val = float(num_str_clean)
            if val in [5.0, 10.0, 15.0, 20.0, 50.0, 200.0]:
                if current_price and abs(val - current_price) / current_price > 0.5:
                    continue
            valid_nums.append(val)
        except ValueError:
            continue
            
    if len(valid_nums) >= 2:
        low, high = sorted(valid_nums[:2])
        if current_price:
            if abs(low - current_price) / current_price < 0.5 and abs(high - current_price) / current_price < 0.5:
                return f"{low:.2f} - {high:.2f}"
        else:
            return f"{low:.2f} - {high:.2f}"
    return None
