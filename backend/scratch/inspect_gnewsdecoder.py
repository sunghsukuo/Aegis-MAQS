import googlenewsdecoder
import inspect

try:
    print("googlenewsdecoder.gnewsdecoder source:")
    print(inspect.getsource(googlenewsdecoder.gnewsdecoder))
except Exception as e:
    print(f"Error inspect gnewsdecoder: {e}")
    
try:
    print("\ngooglenewsdecoder.GoogleDecoder source:")
    print(inspect.getsource(googlenewsdecoder.GoogleDecoder))
except Exception as e:
    print(f"Error inspect GoogleDecoder: {e}")
