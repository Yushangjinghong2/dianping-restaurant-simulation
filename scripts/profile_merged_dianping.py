import gzip
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "datasets" / "Dianping_Merged_Restaurants"
OUT = BASE / "profile_statistics.json"


def distribution(counter):
    values = sorted(counter.values())

    def pct(p):
        return values[round((len(values) - 1) * p)]

    return {
        "entities": len(values),
        "records": sum(values),
        "median": pct(0.50),
        "p75": pct(0.75),
        "p90": pct(0.90),
        "p95": pct(0.95),
        "p99": pct(0.99),
        "max": values[-1],
        "history_bins": {
            "1": sum(v == 1 for v in values),
            "2": sum(v == 2 for v in values),
            "3-4": sum(3 <= v <= 4 for v in values),
            "5-9": sum(5 <= v <= 9 for v in values),
            "10-19": sum(10 <= v <= 19 for v in values),
            "20-49": sum(20 <= v <= 49 for v in values),
            "50-99": sum(50 <= v <= 99 for v in values),
            "100+": sum(v >= 100 for v in values),
        },
    }


users = Counter()
restaurants = Counter()
with gzip.open(BASE / "reviews.jsonl.gz", "rt", encoding="utf-8") as handle:
    for line in handle:
        row = json.loads(line)
        users[str(row.get("user_id"))] += 1
        restaurants[str(row.get("restaurant_id"))] += 1

restaurant_rows = 0
with gzip.open(BASE / "restaurants.jsonl.gz", "rt", encoding="utf-8") as handle:
    for line in handle:
        json.loads(line)
        restaurant_rows += 1

result = {
    "review_rows": sum(users.values()),
    "restaurant_metadata_rows": restaurant_rows,
    "restaurants_with_reviews": len(restaurants),
    "users": distribution(users),
    "restaurants": distribution(restaurants),
}
OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
