import json
from collections import Counter

with open("data/2025.json", "r", encoding="utf-8") as f:
    data = json.load(f)


body = data["result"]["data"]["bodyList"]

codes = []

for x in body:
    codes.append(x.get("preDrawCode"))


print("总数:", len(codes))
print("重复:", len(codes) - len(set(codes)))
