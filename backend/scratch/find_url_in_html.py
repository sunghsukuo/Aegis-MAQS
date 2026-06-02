import requests
import re
from bs4 import BeautifulSoup

url = "https://news.google.com/rss/articles/CBMiWkFVX3lxTE5VNW1GQ3VEbW1tNWVhemtCanZYbnBRSGJWU3lQQWNwQUZaei1FcWhsTTJYUTFUQ29Ec25na0xjT01RM1lWOWp4T0hXeUFmV3RHNXg4QncwSTFCQQ?oc=5"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

try:
    print("Fetching Google News redirect page...")
    response = requests.get(url, headers=headers, timeout=10)
    html = response.text
    print(f"HTML Length: {len(html)}")
    
    # Let's find all HTTP/HTTPS links that do NOT contain google.com or gstatic.com
    all_links = re.findall(r'https?://[a-zA-Z0-9.\-_]+(?:\/[a-zA-Z0-9.\-_#?&%=~]*)*', html)
    print(f"Total links found: {len(all_links)}")
    
    unique_non_google_links = set()
    for l in all_links:
        if "google.com" not in l and "gstatic.com" not in l:
            unique_non_google_links.add(l)
            
    print(f"Unique non-Google links found ({len(unique_non_google_links)}):")
    for l in list(unique_non_google_links)[:25]:
        print(f"   - {l}")
        
except Exception as e:
    print(f"Error: {e}")
