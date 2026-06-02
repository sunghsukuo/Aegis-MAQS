import requests
from bs4 import BeautifulSoup
import re

url = "https://news.google.com/rss/articles/CBMiWkFVX3lxTE5VNW1GQ3VEbW1tNWVhemtCanZYbnBRSGJWU3lQQWNwQUZaei1FcWhsTTJYUTFUQ29Ec25na0xjT01RM1lWOWp4T0hXeUFmV3RHNXg4QncwSTFCQQ?oc=5"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

# Try with CONSENT cookie
cookies = {
    'CONSENT': 'YES+cb.20220419-08-p0.cs'
}

try:
    print("Fetching WITH consent cookie...")
    r = requests.get(url, headers=headers, cookies=cookies, timeout=10)
    print(f"Status Code: {r.status_code}")
    print(f"Final URL: {r.url}")
    
    soup = BeautifulSoup(r.content, "html.parser")
    anchors = soup.find_all("a")
    print(f"Total anchors found: {len(anchors)}")
    
    for a in anchors[:10]:
        print(f"   - Text: {a.get_text().strip()} | Href: {a.get('href')}")
        
    # Search for the redirection href link inside the HTML text
    # In some modern versions, Google News stores it in an <a> tag pointing to the source
    # Or in a meta refresh
    meta_refresh = soup.find("meta", attrs={"http-equiv": "refresh"})
    if meta_refresh:
        print(f"Meta refresh found: {meta_refresh}")
        
    # Let's inspect if there are any specific <a> tags inside a div
    divs = soup.find_all("div")
    print(f"Total divs: {len(divs)}")
    
    # Print the raw HTML text to see if there is any readable URL in it
    text = r.text
    print("\nCheck if 'money.udn.com' or 'economic' or 'udn' is in the raw HTML:")
    found_udn = "udn.com" in text or "economic" in text or "money" in text
    print(f"   Contains 'udn.com'? {found_udn}")
    
    if found_udn:
        # Find all strings matching udn.com
        matches = re.findall(r'https?://[a-zA-Z0-9.\-_]*udn\.com[a-zA-Z0-9.\-_#?&%=~/]*', text)
        print(f"Matches for UDN: {matches}")
        
except Exception as e:
    print(f"Error: {e}")
