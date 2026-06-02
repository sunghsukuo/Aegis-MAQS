import googlenewsdecoder
import inspect

try:
    print("googlenewsdecoder.decoderv2 source:")
    print(inspect.getsource(googlenewsdecoder.decoderv2))
except Exception as e:
    print(f"Error inspect decoderv2: {e}")
