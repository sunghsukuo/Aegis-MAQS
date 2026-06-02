import googlenewsdecoder.decoderv2 as d2
import inspect

try:
    print(inspect.getsource(d2))
except Exception as e:
    print(f"Error inspect: {e}")
