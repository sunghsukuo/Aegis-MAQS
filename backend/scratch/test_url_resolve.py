import requests
from bs4 import BeautifulSoup

url = "https://news.google.com/rss/articles/CBMiWkFVX3lxTE5VNW1GQ3VEbW1tNWVhemtCanZYbnBRSGJWU3lQQWNwQUZaei1FcWhsTTJYUTFUQ29Ec25na0xjT01RM1lWOWp4T0hXeUFmV3RHNXg4QncwSTFCQQ?oc=5"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

try:
    print("Sending request to Google News link...")
    response = requests.get(url, headers=headers, timeout=10)
    print(f"Status Code: {response.status_code}")
    print(f"Final URL: {response.url}")
    print(f"Content Length: {len(response.content)}")
    
    # Check if there is meta-refresh redirect
    soup = BeautifulSoup(response.content, "html.parser")
    meta_refresh = soup.find("meta", attrs={"http-equiv": "refresh"})
    if meta_refresh:
        print(f"Found meta refresh: {meta_refresh}")
    else:
        print("No meta refresh found.")
        
    # Print first 500 characters of text
    text = soup.get_text()
    print("Text snippet:")
    print(text[:500])
except Exception as e:
    print(f"Error: {e}")
