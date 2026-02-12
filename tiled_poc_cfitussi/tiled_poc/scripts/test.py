from tiled.client import from_uri

client = from_uri("http://localhost:8005",api_key="secret")

print("Top-level keys (Hamiltonians):")
print(list(client.keys())[:5])

first_key = list(client.keys())[0]
h = client[first_key]

keys_inside = list(h.keys())
print(f"Keys : {keys_inside}")


arr = h["rixs"][0][:]
print(arr)
print(f"Shape : {arr.shape}")


arr2=h["xps"][0][:]
print(arr2)
print(f"Shape : {arr2.shape}")



