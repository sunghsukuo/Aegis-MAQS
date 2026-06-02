import googlenewsdecoder
import inspect

try:
    print(inspect.getsource(googlenewsdecoder))
except Exception as e:
    print(f"Error inspect: {e}")
