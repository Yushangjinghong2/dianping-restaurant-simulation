import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from dianping_restaurant_filter import (
    DRINK_DESSERT_STYLES,
    NEGATIVE,
    POSITIVE,
    is_restaurant as is_restaurant_category,
)


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "datasets" / "Yongfeng_Dianping" / "dianping"
OUT = ROOT / "datasets" / "Yongfeng_Dianping" / "restaurant_only_statistics.json"
THRESHOLDS = (1, 2, 3, 5, 10, 20, 50, 100)

def rows(path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if " ^ " not in line:
                continue
            url, payload = line.rstrip("\n").split(" ^ ", 1)
            yield url, json.loads(payload)


def is_restaurant(row):
    return is_restaurant_category(row.get("18", ""), row.get("20", ""))


def distribution(counter):
    values = sorted(counter.values())
    if not values:
        return {}

    def pct(p):
        return values[round((len(values) - 1) * p)]

    return {
        "entities": len(values),
        "records": sum(values),
        "median": pct(0.5),
        "p75": pct(0.75),
        "p90": pct(0.90),
        "p95": pct(0.95),
        "p99": pct(0.99),
        "max": values[-1],
        "entities_at_least": {str(t): sum(v >= t for v in values) for t in THRESHOLDS},
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


restaurant_ids = set()
styles = Counter()
metadata_fields = Counter()
metadata_sample = None
for url, row in rows(BASE / "businesses.txt"):
    if not is_restaurant(row):
        continue
    business_id = str(row.get("0", "")).strip()
    if not business_id:
        continue
    restaurant_ids.add(business_id)
    styles[str(row.get("18", "")).strip() or "未知"] += 1
    for key, name in {
        "1": "name", "2": "city", "7": "address", "16": "latitude", "17": "longitude",
        "18": "style", "19": "average_cost", "20": "tags", "11": "recommended_dishes",
    }.items():
        if row.get(key) not in (None, "", [], {}):
            metadata_fields[name] += 1
    if metadata_sample is None:
        metadata_sample = {"url": url, **row}

users = Counter()
restaurants = Counter()
users_with_text = Counter()
restaurants_with_text = Counter()
ratings = Counter()
nonempty_text = 0
date_min = None
date_max = None
sample = None
for url, row in rows(BASE / "reviews.txt"):
    restaurant_id = str(row.get("restId", "")).strip()
    if restaurant_id not in restaurant_ids:
        continue
    user_id = str(row.get("userId", "")).strip()
    users[user_id] += 1
    restaurants[restaurant_id] += 1
    content = str(row.get("content", "")).strip()
    if content:
        nonempty_text += 1
        users_with_text[user_id] += 1
        restaurants_with_text[restaurant_id] += 1
    ratings[str(row.get("rate"))] += 1
    timestamp = row.get("time")
    if isinstance(timestamp, (int, float)) and timestamp > 0:
        day = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).date().isoformat()
        date_min = day if date_min is None or day < date_min else date_min
        date_max = day if date_max is None or day > date_max else date_max
    if sample is None and content and row.get("rate") in {1, 2, 3, 4, 5}:
        sample = {"url": url, **row}

result = {
    "method": {
        "name": "high_confidence_food_service_filter_v1",
        "positive_keywords": POSITIVE,
        "negative_keywords": NEGATIVE,
        "excluded_drink_dessert_styles": DRINK_DESSERT_STYLES,
        "warning": "Rule-based high-confidence subset; not a ground-truth restaurant label.",
    },
    "restaurant_metadata": {
        "entities": len(restaurant_ids),
        "field_nonempty": dict(metadata_fields),
        "top_styles": dict(styles.most_common(30)),
        "sample": metadata_sample,
    },
    "reviews": {
        "records": sum(users.values()),
        "nonempty_content": nonempty_text,
        "users_all": distribution(users),
        "restaurants_all": distribution(restaurants),
        "users_with_text": distribution(users_with_text),
        "restaurants_with_text": distribution(restaurants_with_text),
        "rating_values": dict(ratings),
        "date_min_utc": date_min,
        "date_max_utc": date_max,
        "sample": sample,
    },
}

eligible_users = {key for key, value in users_with_text.items() if value >= 5}
eligible_restaurants = {key for key, value in restaurants_with_text.items() if value >= 20}
joint_users = set()
joint_restaurants = set()
joint_records = 0
for _, row in rows(BASE / "reviews.txt"):
    restaurant_id = str(row.get("restId", "")).strip()
    user_id = str(row.get("userId", "")).strip()
    content = str(row.get("content", "")).strip()
    if content and user_id in eligible_users and restaurant_id in eligible_restaurants:
        joint_records += 1
        joint_users.add(user_id)
        joint_restaurants.add(restaurant_id)

result["joint_portrait_threshold"] = {
    "definition": "nonempty restaurant reviews; user >= 5 and restaurant >= 20",
    "records": joint_records,
    "users": len(joint_users),
    "restaurants": len(joint_restaurants),
}
OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(OUT)
