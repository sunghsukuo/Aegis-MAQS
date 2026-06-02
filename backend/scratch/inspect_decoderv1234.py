import googlenewsdecoder
import inspect

url = "https://news.google.com/rss/articles/CBMiWkFVX3lxTE5VNW1GQ3VEbW1tNWVhemtCanZYbnBRSGJWU3lQQWNwQUZaei1FcWhsTTJYUTFUQ29Ec25na0xjT01RM1lWOWp4T0hXeUFmV3RHNXg4QncwSTFCQQ?oc=5"

decoders = ["decoderv1", "decoderv2", "decoderv3", "decoderv4", "new_decoderv1"]

for d in decoders:
    func = getattr(googlenewsdecoder, d)
    print(f"\n==================================================")
    print(f"Testing Decoder: {d}")
    print(f"==================================================")
    try:
        source_code = inspect.getsource(func)
        print(f"Source Code length: {len(source_code)}")
        # Let's see if we can call it
        # Try to call it with the url or base64 str
        base64_response = googlenewsdecoder.GoogleDecoder().get_base64_str(url)
        base64_str = base64_response["base64_str"]
        print(f"Base64 string: {base64_str[:30]}...")
        
        result = func(base64_str)
        print(f"Result: {result}")
    except Exception as e:
        print(f"Error executing {d}: {e}")
