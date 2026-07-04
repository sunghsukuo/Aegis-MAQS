import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup
import urllib.parse
from datetime import datetime

# Gossip, forum, and social media source keywords blacklist for de-noising
SOURCE_BLACKLIST = [
    "ptt.cc", "dcard.tw", "mobile01.com", "bahamut.com.tw", "pixnet.net",
    "medium.com", "blog", "forum", "plurk.com", "facebook.com", "youtube.com",
    "instagram.com", "twitter.com", "x.com", "論壇", "討論區", "部落格",
    "股市爆料同學會", "爆料同學會", "cmoney.tw/forum", "cmoney.tw/app", "stocktwits.com"
]

# Trusted professional financial and authoritative mainstream media whitelist
TRUSTED_MEDIA_WHITELIST = [
    "cnyes.com",         # 鉅亨網
    "moneydj.com",       # MoneyDJ理財網
    "udn.com",           # 聯合新聞網 / 經濟日報
    "chinatimes.com",    # 中時電子報 / 工商時報
    "wealth.com.tw",     # 財訊
    "businesstoday.com.tw", # 今周刊
    "commonwealth.com.tw",  # 天下雜誌
    "businessweekly.com.tw", # 商業周刊
    "yahoo.com",         # Yahoo Finance
    "bloomberg.com",     # Bloomberg
    "reuters.com",       # Reuters
    "cnbc.com",          # CNBC
    "wsj.com",           # WSJ
    "marketwatch.com",   # MarketWatch
    "nikkei.com",        # 日經新聞
    "technews.tw",       # 科技新報
    "digitimes.com.tw",  # 電子時報
    "ft.com",            # Financial Times
    "economist.com"      # The Economist
]

# Professional finance terms for fallback keyword density validation
PROFESSIONAL_FINANCE_KEYWORDS = [
    # Macroeconomic keywords
    "央行", "升息", "降息", "通膨", "通脹", "利率", "利差", "國債", "美債",
    "gdp", "cpi", "pce", "pmi", "出口", "進口", "順差", "逆差", "非農", "就業率",
    "失業率", "景氣燈號", "景氣對策信號", "折現率", "量化寬鬆", "qe", "縮表", "fed", "美聯儲",
    # Stock / Corporate keywords
    "營收", "財報", "毛利", "淨利", "eps", "每股盈餘", "每股收益", "法說", "業績", "訂單", 
    "產能", "擴產", "建廠", "研發", "晶圓", "代工", "毛利率", "股利", "配息", "除權息",
    "殖利率", "權值股", "概念股", "庫藏股", "增資", "減資", "收購", "合併", "m&a", "重組", 
    "供應鏈", "出貨", "晶片", "半導體", "人工智慧", "ai", "伺服器", "專利", "授權"
]

def scrape_article_content(url: str) -> str:
    """
    爬取新聞網頁的完整內文，並提取純文字段落作為實質摘要。
    設有防爬蟲 Header 偽裝，防範防火牆阻擋。
    """
    try:
        # 偽裝成真實瀏覽器 Header
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.google.com/"
        }
        
        # 進行網頁請求 (超時設定 8 秒，避免卡死)
        response = requests.get(url, headers=headers, timeout=8)
        if response.status_code != 200:
            return ""
            
        soup = BeautifulSoup(response.content, "html.parser")
        
        # 移除無效元素 (廣告、側邊欄、指令碼、頁尾)
        for element in soup(["script", "style", "nav", "footer", "iframe", "header", "aside", "noscript"]):
            element.decompose()
            
        # 尋找新聞主體段落 (常見的 p 標籤)
        paragraphs = soup.find_all("p")
        text_content = []
        for p in paragraphs:
            text = p.get_text().strip()
            # 過濾掉太短的段落 (如廣告警語、版權聲明、社群分享按鈕)
            if len(text) > 25 and "版權所有" not in text and "廣告" not in text:
                text_content.append(text)
                
        # 合併段落，限制長度以防 Token 膨脹
        full_text = "\n".join(text_content)
        return full_text[:600].strip()
        
    except Exception:
        # 防禦性退守：爬取失敗時不拋出錯誤，直接返回空值
        return ""

def fetch_rss_news(feed_url: str, max_items: int = 8, max_age_days: int = 14) -> list:
    """Helper function to fetch and parse an RSS XML feed into a clean list of news articles, filtering for time, publisher validity, and financial relevance."""
    import email.utils
    from datetime import datetime, timezone
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(feed_url, headers=headers, timeout=10)
        if response.status_code != 200:
            return []
            
        # Parse XML using Python standard library
        root = ET.fromstring(response.content)
        items = root.findall(".//item")
        
        now = datetime.now(timezone.utc)
        articles = []
        
        for item in items:
            if len(articles) >= max_items:
                break
                
            title = item.find("title").text if item.find("title") is not None else ""
            link = item.find("link").text if item.find("link") is not None else ""
            pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""
            description = item.find("description").text if item.find("description") is not None else ""
            
            # 1. Gossip & Forum Filtering: Skip personal gossip and discussion threads
            link_lower = link.lower() if link else ""
            title_lower = title.lower() if title else ""
            if any(word in link_lower or word in title_lower for word in SOURCE_BLACKLIST):
                continue
                
            # 2. Deep De-noising: Whitelist & Professional keyword relevance verification
            is_trusted_source = any(domain in link_lower for domain in TRUSTED_MEDIA_WHITELIST)
            if not is_trusted_source:
                desc_lower = description.lower() if description else ""
                combined_text = f"{title_lower} {desc_lower}"
                # If not from a trusted whitelisted media, it MUST contain at least one professional financial keyword
                if not any(kw in combined_text for kw in PROFESSIONAL_FINANCE_KEYWORDS):
                    continue
                    
            # 3. Time-validity filter: Reject stale articles older than max_age_days
            if pub_date:
                try:
                    dt = email.utils.parsedate_to_datetime(pub_date.strip())
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    age = now - dt
                    # Exclude articles older than our target age
                    if age.days > max_age_days:
                        continue
                except Exception as date_ex:
                    # If date parsing fails, proceed defensively but log warning
                    print(f"[!] Warning: Failed parsing date '{pub_date}': {date_ex}")
            
            # Clean HTML tags from description if present and de-duplicate if it repeats the title
            clean_summary = ""
            if description:
                desc_soup = BeautifulSoup(description, "html.parser")
                clean_summary = desc_soup.get_text().strip()
                
            # If the summary is identical or fully redundant with the title (e.g. Google News repeating title in desc)
            title_clean = title.strip()
            
            # Normalize strings by stripping all spaces, punctuation, and non-alphanumeric/non-Chinese chars
            import re
            def normalize_for_compare(s):
                return re.sub(r"[^\w\u4e00-\u9fff]", "", s).lower()
                
            norm_title = normalize_for_compare(title_clean)
            norm_summary = normalize_for_compare(clean_summary)
            
            if not norm_summary or norm_summary == norm_title or norm_summary in norm_title or norm_title in norm_summary:
                # Summary is redundant or empty! Attempt defensive live web scraping of the actual article content
                # Only try to scrape if it's a direct publisher link (not a Google News redirect tracking link)
                if "google.com" not in link_lower:
                    scraped_text = scrape_article_content(link.strip())
                    if scraped_text:
                        clean_summary = scraped_text
                    else:
                        clean_summary = ""
                else:
                    clean_summary = ""
                
            articles.append({
                "title": title_clean,
                "link": link.strip(),
                "pub_date": pub_date.strip() if pub_date else "N/A",
                "summary": clean_summary[:400]  # Expanded to 400 characters for richer context
            })
      
        # If strict filtering left us with 0 articles, retry with a slightly wider buffer (max 30 days) to prevent blank pages
        if not articles and max_age_days < 30:
            return fetch_rss_news(feed_url, max_items, max_age_days=30)
            
        return articles
    except Exception as e:
        print(f"Error fetching RSS from {feed_url}: {e}")
        return []

def get_stock_news(ticker: str, max_items: int = 5) -> list:
    """Fetches real-time stock-specific news using the Yahoo Finance RSS feed."""
    clean_ticker = ticker.strip().upper()
    # Yahoo Finance RSS Feed for a specific ticker
    feed_url = f"https://feeds.finance.yahoo.com/rss/2.0?s={clean_ticker}"
    
    news = fetch_rss_news(feed_url, max_items)
    # If Yahoo RSS is empty, fallback to Google News RSS search
    if not news:
        query = f"{clean_ticker} stock news when:7d"
        news = search_news(query, max_items)
        
    return news

def search_news(query: str, max_items: int = 6, language: str = "zh-TW", region: str = "TW") -> list:
    """Searches Google News RSS for macroeconomic topics or industry trends."""
    encoded_query = urllib.parse.quote(query)
    
    # Configure language/region suffixes
    if language == "zh-TW":
        feed_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    else:
        feed_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
        
    return fetch_rss_news(feed_url, max_items)

def get_macro_news(region_code: str, max_items: int = 5) -> list:
    """Fetches top macroeconomic and financial policy news for a given region."""
    if region_code == "US":
        # Search for major US economic events
        query = "US Federal Reserve interest rates inflation CPI market when:7d"
        return search_news(query, max_items, language="en-US", region="US")
    elif region_code == "Taiwan":
        # Search for major Taiwan economic events
        #query = "台灣 總體經濟 出口 央行 景氣燈號 when:7d"
        query = """(台灣 OR 台 OR 主計處 OR 國發會 OR 台灣央行) 
                    (intitle:"總體經濟" OR intitle:"總經" OR intitle:"景氣燈號" OR intitle:"經濟成長率" 
                    OR intitle:"GDP" OR intitle:"CPI" OR intitle:"通膨" OR intitle:"升息" OR intitle:"降息") 
                    -intitle:"美股" -intitle:"個股" -intitle:"聯準會" -intitle:"陸股" -intitle:"非農 when:7d"""
        return search_news(query, max_items, language="zh-TW", region="TW")
    else:
        query = f"{region_code} macroeconomic financial news"
        return search_news(query, max_items, language="en-US", region="US")

def get_thematic_industry_news(region_code: str, max_items: int = 5) -> list:
    """Fetches trending industry/technology themes and brokerage research news."""
    if region_code == "US":
        query = "(US OR Wall Street) (intitle:\"industry trends\" OR intitle:\"investment themes\" OR intitle:\"growth stocks\" OR intitle:\"brokerage research\") -intitle:\"crypto\" -intitle:\"bitcoin\" when:7d"
        return search_news(query, max_items, language="en-US", region="US")
    elif region_code == "Taiwan":
        query = "(台股 OR 台灣 OR 券商 OR 投顧) (intitle:\"產業趨勢\" OR intitle:\"熱門概念股\" OR intitle:\"投研報告\" OR intitle:\"題材\") -intitle:\"虛擬貨幣\" -intitle:\"比特幣\" when:7d"
        return search_news(query, max_items, language="zh-TW", region="TW")
    else:
        query = f"{region_code} hot industry trends technology news"
        return search_news(query, max_items, language="en-US", region="US")
