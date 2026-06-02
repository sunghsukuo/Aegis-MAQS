import googlenewsdecoder
import inspect

print("googlenewsdecoder directory:")
print(dir(googlenewsdecoder))

print("\nInspect members of googlenewsdecoder:")
for name, obj in inspect.getmembers(googlenewsdecoder):
    if not name.startswith("_"):
        print(f"Name: {name} | Type: {type(obj)}")
