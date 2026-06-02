from googlenewsdecoder import gnewsdecoder

url = "https://news.google.com/rss/articles/CBMiWkFVX3lxTE5VNW1GQ3VEbW1tNWVhemtCanZYbnBRSGJWU3lQQWNwQUZaei1FcWhsTTJYUTFUQ29Ec25na0xjT01RM1lWOWp4T0hXeUFmV3RHNXg4QncwSTFCQQ?oc=5"

try:
    print("Decoding Google News URL...")
    decoded = gnewsdecoder(url)
    print(f"Decoded result: {decoded}")
    if isinstance(decoded, dict) and decoded.get("status"):
        print(f"Success! Decoded URL: {decoded['decoded_url']}")
    else:
        print(f"Decoded directly as string/other: {decoded}")
except Exception as e:
    print(f"Error: {e}")
