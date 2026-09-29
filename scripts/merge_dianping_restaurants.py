import gzip
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from dianping_restaurant_filter import is_restaurant, is_stanford_restaurant


ROOT = Path(__file__).resolve().parents[1]
YF = ROOT / "datasets" / "Yongfeng_Dianping" / "dianping"
STANFORD = ROOT / "datasets" / "Stanford_Dianping_Ni" / "dianping.json"
OUT = ROOT / "datasets" / "Dianping_Merged_Restaurants"


def dump_line(handle, row):
    handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def source_rows(path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if " ^ " not in line:
                continue
            url, payload = line.rstrip("\n").split(" ^ ", 1)
            yield url, json.loads(payload)


def user_number(value):
    match = re.search(r"\d+", str(value or ""))
    return match.group(0) if match else None


def normalized_text(value):
    return re.sub(r"\s+", "", str(value or ""))


def review_key(restaurant_id, user_id, content):
    raw = f"{restaurant_id}\x1f{user_id or ''}\x1f{normalized_text(content)}"
    return hashlib.sha1(raw.encode("utf-8")).digest()


def valid_number(value):
    return None if value in (None, "", -1, "-1") else value


OUT.mkdir(parents=True, exist_ok=True)
database = OUT / "stanford_merge_index.sqlite"
if database.exists():
    database.unlink()

city_by_code = {}
for line in (YF / "city.txt").read_text(encoding="utf-8").splitlines():
    if "=" in line:
        name, code = line.rsplit("=", 1)
        city_by_code[code.strip()] = name.strip()

stanford = json.loads(STANFORD.read_text(encoding="utf-8"))
connection = sqlite3.connect(database)
connection.execute("CREATE TABLE pending (key BLOB PRIMARY KEY, payload TEXT NOT NULL)")
stanford_restaurant_ids = set()
stanford_reviews_input = 0
stanford_reviews_internal_duplicates = 0
for restaurant_id, shop in stanford.items():
    if not is_stanford_restaurant(shop):
        continue
    stanford_restaurant_ids.add(str(restaurant_id))
    for review in shop.get("reviews", []):
        stanford_reviews_input += 1
        user_id = user_number(review.get("member_id"))
        content = review.get("text") or ""
        row = {
            "review_id": review.get("review_id"),
            "user_id": user_id,
            "restaurant_id": str(restaurant_id),
            "timestamp_ms": None,
            "date": review.get("date_posted"),
            "overall_rating": review.get("star_rank"),
            "flavor_rating": review.get("kouwei"),
            "environment_rating": review.get("huanjing"),
            "service_rating": review.get("fuwu"),
            "cost": review.get("cost_per"),
            "content": content,
            "segmented_content": review.get("text-seg"),
            "source": "stanford",
        }
        cursor = connection.execute(
            "INSERT OR IGNORE INTO pending(key, payload) VALUES (?, ?)",
            (review_key(restaurant_id, user_id, content), json.dumps(row, ensure_ascii=False)),
        )
        if cursor.rowcount == 0:
            stanford_reviews_internal_duplicates += 1
connection.commit()

selected_original_ids = set()
original_restaurants = 0
with gzip.open(OUT / "restaurants.jsonl.gz", "wt", encoding="utf-8", newline="") as output:
    for url, row in source_rows(YF / "businesses.txt"):
        if not is_restaurant(row.get("18"), row.get("20")):
            continue
        restaurant_id = str(row.get("0"))
        selected_original_ids.add(restaurant_id)
        original_restaurants += 1
        code = str(row.get("2", ""))
        dump_line(output, {
            "restaurant_id": restaurant_id,
            "name": row.get("1"),
            "branch": None,
            "city": city_by_code.get(code),
            "city_code": code or None,
            "address": row.get("7"),
            "category": row.get("18"),
            "tags": row.get("20"),
            "average_cost": valid_number(row.get("19")),
            "overall_score": valid_number(row.get("3")),
            "flavor_score": valid_number(row.get("4")),
            "environment_score": valid_number(row.get("5")),
            "service_score": valid_number(row.get("6")),
            "latitude": valid_number(row.get("16")),
            "longitude": valid_number(row.get("17")),
            "url": url,
            "source": "yongfeng",
        })
    stanford_restaurants_added = 0
    for restaurant_id, shop in stanford.items():
        if str(restaurant_id) in selected_original_ids or not is_stanford_restaurant(shop):
            continue
        stanford_restaurants_added += 1
        dump_line(output, {
            "restaurant_id": str(restaurant_id),
            "name": shop.get("name"),
            "branch": shop.get("branch"),
            "city": shop.get("city"),
            "city_code": None,
            "address": shop.get("address"),
            "category": shop.get("category"),
            "tags": shop.get("breadcrumb"),
            "average_cost": shop.get("cost_per"),
            "overall_score": shop.get("star_rank"),
            "flavor_score": shop.get("kouwei"),
            "environment_score": shop.get("huanjing"),
            "service_score": shop.get("fuwu"),
            "latitude": None,
            "longitude": None,
            "url": f"http://www.dianping.com/shop/{restaurant_id}",
            "source": "stanford",
        })

original_reviews = 0
original_reviews_with_text = 0
cross_source_duplicates = 0
with gzip.open(OUT / "reviews.jsonl.gz", "wt", encoding="utf-8", newline="") as output:
    for url, row in source_rows(YF / "reviews.txt"):
        restaurant_id = str(row.get("restId"))
        if restaurant_id not in selected_original_ids:
            continue
        user_id = user_number(row.get("userId"))
        content = row.get("content") or ""
        original_reviews += 1
        if content.strip():
            original_reviews_with_text += 1
        key = review_key(restaurant_id, user_id, content)
        cursor = connection.execute("DELETE FROM pending WHERE key = ?", (key,))
        cross_source_duplicates += cursor.rowcount
        timestamp = row.get("time")
        date = None
        if isinstance(timestamp, (int, float)) and timestamp > 0:
            date = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).date().isoformat()
        dump_line(output, {
            "review_id": None,
            "user_id": user_id,
            "restaurant_id": restaurant_id,
            "timestamp_ms": timestamp,
            "date": date,
            "overall_rating": valid_number(row.get("rate")),
            "flavor_rating": valid_number(row.get("flavor")),
            "environment_rating": valid_number(row.get("environment")),
            "service_rating": valid_number(row.get("service")),
            "cost": valid_number(row.get("cost")),
            "content": content,
            "segmented_content": None,
            "source": "yongfeng",
        })
        if original_reviews % 100000 == 0:
            connection.commit()
    connection.commit()
    stanford_reviews_added = 0
    for payload, in connection.execute("SELECT payload FROM pending"):
        dump_line(output, json.loads(payload))
        stanford_reviews_added += 1

connection.close()
database.unlink()

stats = {
    "filter": "high-confidence restaurants; drink and dessert venue styles excluded",
    "restaurants": {
        "from_yongfeng": original_restaurants,
        "stanford_ids_already_present": len(selected_original_ids & stanford_restaurant_ids),
        "added_from_stanford": stanford_restaurants_added,
        "merged_total": original_restaurants + stanford_restaurants_added,
    },
    "reviews": {
        "from_yongfeng": original_reviews,
        "from_yongfeng_with_text": original_reviews_with_text,
        "stanford_input_after_category_filter": stanford_reviews_input,
        "stanford_internal_duplicate_keys": stanford_reviews_internal_duplicates,
        "cross_source_duplicates_removed": cross_source_duplicates,
        "added_from_stanford": stanford_reviews_added,
        "merged_total": original_reviews + stanford_reviews_added,
    },
    "deduplication_key": "restaurant_id + normalized user_id + whitespace-stripped content",
}
(OUT / "merge_statistics.json").write_text(
    json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(stats, ensure_ascii=False, indent=2))
