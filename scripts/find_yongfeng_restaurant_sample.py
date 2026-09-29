import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "datasets" / "Yongfeng_Dianping" / "dianping"
OUT = ROOT / "datasets" / "Yongfeng_Dianping" / "restaurant_sample.json"


def rows(path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if " ^ " not in line:
                continue
            url, payload = line.rstrip("\n").split(" ^ ", 1)
            yield url, json.loads(payload)


businesses = {}
for url, row in rows(BASE / "businesses.txt"):
    if row.get("1") and row.get("18") in {"川菜", "粤菜", "火锅", "湘菜", "日本料理"}:
        businesses[str(row["0"])] = {
            "url": url,
            "business_id": row["0"],
            "name": row["1"],
            "city_code": row.get("2"),
            "style": row.get("18"),
            "address": row.get("7"),
            "average_cost": row.get("19"),
        }

sample = None
for url, row in rows(BASE / "reviews.txt"):
    business_id = str(row.get("restId", ""))
    content = str(row.get("content", "")).strip()
    if business_id in businesses and content and row.get("rate", -1) in {1, 2, 3, 4, 5}:
        sample = {
            "business": businesses[business_id],
            "review": {
                "url": url,
                "user_id": row.get("userId"),
                "business_id": row.get("restId"),
                "time_unix_ms": row.get("time"),
                "rate": row.get("rate"),
                "flavor": row.get("flavor"),
                "environment": row.get("environment"),
                "service": row.get("service"),
                "cost": row.get("cost"),
                "content": content,
                "dishes": row.get("dishes"),
            },
        }
        break

OUT.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
print(OUT)
