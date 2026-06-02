import sys
import requests
import base64
import json

# Let's inspect the actual file contents of googlenewsdecoder/decoderv2.py by looking at sys.modules or inspect
import googlenewsdecoder.decoderv2 as d2_func

# In python, d2_func is a function, so its module name is d2_func.__module__
module_name = d2_func.__module__
print(f"Module name: {module_name}")
module_obj = sys.modules[module_name]
print(f"Module file path: {module_obj.__file__}")

with open(module_obj.__file__, "r", encoding="utf-8") as f:
    print(f.read())
