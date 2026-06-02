import googlenewsdecoder

url = "https://news.google.com/rss/articles/CBMiWkFVX3lxTE5VNW1GQ3VEbW1tNWVhemtCanZYbnBRSGJWU3lQQWNwQUZaei1FcWhsTTJYUTFUQ29Ec25na0xjT01RM1lWOWp4T0hXeUFmV3RHNXg4QncwSTFCQQ?oc=5"

try:
    print("Calling googlenewsdecoder.decoderv1 with full URL...")
    result = googlenewsdecoder.decoderv1(url)
    print(f"Result: {result}")
except Exception as e:
    print(f"Error: {e}")
