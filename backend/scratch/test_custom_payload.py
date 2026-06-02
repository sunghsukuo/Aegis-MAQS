import requests
import json
import base64
import re
from bs4 import BeautifulSoup
from urllib.parse import quote, urlparse

url = "https://news.google.com/rss/articles/CBMiWkFVX3lxTE5VNW1GQ3VEbW1tNWVhemtCanZYbnBRSGJWU3lQQWNwQUZaei1FcWhsTTJYUTFUQ29Ec25na0xjT01RM1lWOWp4T0hXeUFmV3RHNXg4QncwSTFCQQ?oc=5"

try:
    # 1. Get base64 string
    url_obj = urlparse(url)
    base64_str = url_obj.path.split("/")[-1]
    print(f"Base64 Str: {base64_str}")
    
    # 2. Get decoding params
    rss_url = f"https://news.google.com/rss/articles/{base64_str}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    response = requests.get(rss_url, headers=headers, timeout=10)
    
    soup = BeautifulSoup(response.content, "html.parser")
    data_element = soup.find("c-wiz")
    if not data_element:
        data_element = soup.find("div", attrs={"jscontroller": True})
        
    signature = None
    timestamp = None
    if data_element:
        signature = data_element.get("data-n-a-sg")
        timestamp = data_element.get("data-n-a-ts")
        
    print(f"Soup Signature: {signature}")
    print(f"Soup Timestamp: {timestamp}")
    
    if not signature or not timestamp:
        # Search raw html text for attributes using regex
        sig_match = re.search(r'data-n-a-sg="([^"]+)"', response.text)
        ts_match = re.search(r'data-n-a-ts="([^"]+)"', response.text)
        signature = sig_match.group(1) if sig_match else None
        timestamp = ts_match.group(1) if ts_match else None
        print(f"Regex Signature: {signature}")
        print(f"Regex Timestamp: {timestamp}")

    # 3. Call batchexecute with Taiwan payload!
    if signature and timestamp:
        batch_url = "https://news.google.com/_/DotsSplashUi/data/batchexecute"
        
        # Test both US and Taiwan region settings in payload
        regions = [
            ("TW:zh-Hant", "TW", "zh-TW"),
            ("US:en", "US", "en-US")
        ]
        
        for region_tag, gl, hl in regions:
            print(f"\nTrying with region: {region_tag}")
            payload = [
                "Fbv4je",
                f'["garturlreq",[["X","X",["X","X"],null,null,1,1,"{region_tag}",null,1,null,null,null,null,null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{base64_str}",{timestamp},"{signature}"]',
            ]
            
            headers = {
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            }

            resp = requests.post(
                batch_url,
                headers=headers,
                data=f"f.req={quote(json.dumps([[payload]]))}",
                timeout=10
            )
            print(f"BatchExecute Response Status: {resp.status_code}")
            
            try:
                raw_text = resp.text
                parsed_data = json.loads(raw_text.split("\n\n")[1])[:-2]
                res_str = parsed_data[0][2]
                print(f"Raw inner JSON: {res_str[:100]}...")
                if res_str:
                    decoded_url = json.loads(res_str)[1]
                    print(f"🎉 SUCCESS! Decoded URL: {decoded_url}")
                    break
            except Exception as e:
                print(f"   Failed to parse: {e}")
                
except Exception as e:
    print(f"Error: {e}")
