import requests

url_with_query = "https://news.google.com/rss/articles/CBMiWkFVX3lxTE5VNW1GQ3VEbW1tNWVhemtCanZYbnBRSGJWU3lQQWNwQUZaei1FcWhsTTJYUTFUQ29Ec25na0xjT01RM1lWOWp4T0hXeUFmV3RHNXg4QncwSTFCQQ?oc=5"
url_no_query = "https://news.google.com/rss/articles/CBMiWkFVX3lxTE5VNW1GQ3VEbW1tNWVhemtCanZYbnBRSGJWU3lQQWNwQUZaei1FcWhsTTJYUTFUQ29Ec25na0xjT01RM1lWOWp4T0hXeUFmV3RHNXg4QncwSTFCQQ"

try:
    print("1. Testing with query params:")
    r1 = requests.get(url_with_query, allow_redirects=True, timeout=10)
    print(f"   Status: {r1.status_code}")
    print(f"   Final URL: {r1.url}")
    print(f"   History: {r1.history}")
    
    print("\n2. Testing WITHOUT query params:")
    r2 = requests.get(url_no_query, allow_redirects=True, timeout=10)
    print(f"   Status: {r2.status_code}")
    print(f"   Final URL: {r2.url}")
    print(f"   History: {r2.history}")
    
    print("\n3. Testing head WITHOUT query params:")
    r3 = requests.head(url_no_query, allow_redirects=True, timeout=10)
    print(f"   Status: {r3.status_code}")
    print(f"   Final URL: {r3.url}")
    print(f"   History: {r3.history}")
    
except Exception as e:
    print(f"Error: {e}")
