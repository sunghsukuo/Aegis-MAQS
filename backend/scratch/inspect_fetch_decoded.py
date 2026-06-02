import googlenewsdecoder.new_decoderv2 as nd2
import inspect

try:
    print("nd2.fetch_decoded_batch_execute source:")
    print(inspect.getsource(nd2.fetch_decoded_batch_execute))
except Exception as e:
    print(f"Error inspect fetch_decoded_batch_execute: {e}")
