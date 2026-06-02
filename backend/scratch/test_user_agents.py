import requests
from bs4 import BeautifulSoup

url = "https://news.google.com/rss/articles/CBMiWkFVX3lxTE5VNW1GQ3VEbW1tNWVhemtCanZYbnBRSGJWU3lQQWNwQUZaei1FcWhsTTJYUTFUQ29Ec25na0xjT01RM1lWOWp4T0hXeUFmV3RHNXg4QncwSTFCQQ?oc=5"

user_agents = [
    # 1. No User-Agent (we already tested this, it returned 200)
    None,
    # 2. Googlebot
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    # 3. Very old IE browser
    "Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.1; SV1)",
    # 4. Simple curl UA
    "curl/7.68.0",
    # 5. Mobile browser (iPhone)
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"
]

for ua in user_agents:
    print(f"\n==================================================")
    print(f"Testing User-Agent: {ua}")
    print(f"==================================================")
    try:
        headers = {}
        if ua:
            headers["User-Agent"] = ua
            
        response = requests.get(url, headers=headers, allow_redirects=True, timeout=8)
        print(f"Status: {response.status_code}")
        print(f"Final URL: {response.url}")
        
        soup = BeautifulSoup(response.content, "html.parser")
        
        # Check meta refresh
        meta_refresh = soup.find("meta", attrs={"http-equiv": "refresh"})
        if meta_refresh:
            print(f"✅ Found Meta Refresh! Content: {meta_refresh.get('content')}")
            # Try to extract the URL from the content attribute
            content_attr = meta_refresh.get('content', '')
            if "url=" in content_attr.lower():
                actual_url = content_attr.lower().split("url=")[-1]
                print(f"   Parsed actual URL: {actual_url}")
        else:
            print("❌ No Meta Refresh found in HTML.")
            
        # Check if there is an anchor tag redirect fallback
        anchors = soup.find_all("a")
        if anchors:
            print(f"Found {len(anchors)} anchor tags. Headings:")
            for a in anchors[:3]:
                print(f"   - {a.get_text().strip()} -> {a.get('href')}")
                
    except Exception as e:
        print(f"Error: {e}")
