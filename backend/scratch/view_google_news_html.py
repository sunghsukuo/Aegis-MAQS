import requests
from bs4 import BeautifulSoup
import re

url = "https://news.google.com/rss/articles/CBMiWkFVX3lxTE5VNW1GQ3VEbW1tNWVhemtCanZYbnBRSGJWU3lQQWNwQUZaei1FcWhsTTJYUTFUQ29Ec25na0xjT01RM1lWOWp4T0hXeUFmV3RHNXg4QncwSTFCQQ?oc=5"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

try:
    response = requests.get(url, headers=headers, timeout=10)
    soup = BeautifulSoup(response.content, "html.parser")
    
    # Let's search for the actual article URL in the Google News page.
    # Typically, the actual link is in the href of a specific anchor tag or inside a script.
    anchors = soup.find_all("a")
    print(f"Total anchor tags found: {len(anchors)}")
    for a in anchors[:15]:
        href = a.get("href")
        text = a.get_text().strip()
        print(f"Text: {text} | Href: {href}")
        
    print("\nSearching for any URLs in script tags or meta tags...")
    for script in soup.find_all("script"):
        content = script.string
        if content and "http" in content:
            # Print script snippet
            print(f"Found script containing http (len {len(content)})")
            # Find URLs
            urls = re.findall(r'https?://[^\s"\']+', content)
            if urls:
                print(f"Urls in script: {urls[:5]}")
                
except Exception as e:
    print(f"Error: {e}")
