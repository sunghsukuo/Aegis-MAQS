import requests
import json
import re
from urllib.parse import quote

# Let's see what batchexecute returns exactly
base64_str = "CBMiWkFVX3lxTE5VNW1GQ3VEbW1tNWVhemtCanZYbnBRSGJWU3lQQWNwQUZaei1FcWhsTTJYUTFUQ29Ec25na0xjT01RM1lWOWp4T0hXeUFmV3RHNXg4QncwSTFCQQ"
signature = "AaLI4RSMQ18S4ytNtsHj_tG1QTHw"
timestamp = "1780297015"

batch_url = "https://news.google.com/_/DotsSplashUi/data/batchexecute"

# Test payload with different format
payload = [
    "Fbv4je",
    f'["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{base64_str}",{timestamp},"{signature}"]',
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

print(f"Status: {resp.status_code}")
print("Response text first 1000 chars:")
print(resp.text[:1000])
