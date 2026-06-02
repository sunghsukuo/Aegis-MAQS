import requests

url = "https://news.google.com/rss/articles/CBMiWkFVX3lxTE5VNW1GQ3VEbW1tNWVhemtCanZYbnBRSGJWU3lQQWNwQUZaei1FcWhsTTJYUTFUQ29Ec25na0xjT01RM1lWOWp4T0hXeUFmV3RHNXg4QncwSTFCQQ?oc=5"

try:
    print("Testing requests.get with no headers...")
    response1 = requests.get(url, timeout=10)
    print(f"Status 1: {response1.status_code}")
    print(f"URL 1: {response1.url}")
    
    print("\nTesting requests.head with no headers...")
    response2 = requests.head(url, allow_redirects=True, timeout=10)
    print(f"Status 2: {response2.status_code}")
    print(f"URL 2: {response2.url}")
    
    print("\nTesting requests.head with generic python UA...")
    headers = {"User-Agent": "python-requests/2.31.0"}
    response3 = requests.head(url, headers=headers, allow_redirects=True, timeout=10)
    print(f"Status 3: {response3.status_code}")
    print(f"URL 3: {response3.url}")

except Exception as e:
    print(f"Error: {e}")
