import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup

url = "https://news.cnyes.com/rss/genre/tw_macro"

try:
    print(f"Fetching cnyes.com RSS feed from {url}...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    response = requests.get(url, headers=headers, timeout=10)
    print(f"Status Code: {response.status_code}")
    
    root = ET.fromstring(response.content)
    items = root.findall(".//item")
    print(f"Total items found: {len(items)}")
    
    for i, item in enumerate(items[:3], 1):
        title = item.find("title").text if item.find("title") is not None else ""
        link = item.find("link").text if item.find("link") is not None else ""
        description = item.find("description").text if item.find("description") is not None else ""
        
        print(f"\n[{i}] {title}")
        print(f"    Link: {link}")
        # Clean description HTML tags
        desc_soup = BeautifulSoup(description, "html.parser")
        desc_text = desc_soup.get_text().strip()
        print(f"    Description: {desc_text[:200]}...")
        
        # Test scraping this cnyes link
        print(f"    Testing scraping direct link...")
        # Custom cnyes scraper: usually cnyes paragraphs are in div[itemprop="articleBody"] p or just standard p
        r = requests.get(link, headers=headers, timeout=8)
        soup = BeautifulSoup(r.content, "html.parser")
        paragraphs = soup.find_all("p")
        scraped_text = []
        for p in paragraphs:
            t = p.get_text().strip()
            if len(t) > 20 and "廣告" not in t and "版權所有" not in t:
                scraped_text.append(t)
        
        print(f"    Scraped text length: {len(''.join(scraped_text))}")
        print(f"    Snippet: {' '.join(scraped_text)[:300]}...")
        
except Exception as e:
    print(f"Error: {e}")
