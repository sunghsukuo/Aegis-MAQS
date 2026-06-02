import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup
import sys
from pathlib import Path

# Add backend root to sys.path
backend_root = str(Path(__file__).resolve().parent.parent)
sys.path.append(backend_root)

import core.tools.web_search as search_tool

# CNBC Technology public RSS feed
url = "https://www.cnbc.com/id/19854910/device/rss/rss.html"

try:
    print(f"Fetching direct CNBC Technology RSS feed: {url}...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    response = requests.get(url, headers=headers, timeout=10)
    print(f"Status Code: {response.status_code}")
    
    root = ET.fromstring(response.content)
    items = root.findall(".//item")
    print(f"Total RSS items found: {len(items)}")
    
    for i, item in enumerate(items[:2], 1):
        title = item.find("title").text if item.find("title") is not None else ""
        link = item.find("link").text if item.find("link") is not None else ""
        
        print("\n" + "="*60)
        print(f"[{i}] 標題：{title}")
        print(f"    原始網址：{link}")
        
        # Test scraping this direct link!
        print(f"    正在啟動爬蟲，對連結進行深度內容精華抓取...")
        scraped_text = search_tool.scrape_article_content(link)
        print(f"    抓取成功！內文長度：{len(scraped_text)} 字元")
        if scraped_text:
            print(f"    內容精華資料 (前 300 字)：\n    {scraped_text[:350]}...")
        else:
            print("    ⚠️ 抓取內文失敗 (可能遇到反爬蟲阻擋或網頁結構不相符)")
            
except Exception as e:
    print(f"Error: {e}")
