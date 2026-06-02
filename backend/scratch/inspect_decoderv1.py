import googlenewsdecoder
import inspect

try:
    print("googlenewsdecoder.decoderv1 source:")
    print(inspect.getsource(googlenewsdecoder.decoderv1))
except Exception as e:
    print(f"Error inspect decoderv1: {e}")
