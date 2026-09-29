import csv
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THRESHOLDS = (1, 2, 3, 5, 10, 20, 50, 100)


def coverage(counts: Counter) -> dict:
    values = sorted(counts.values())
    if not values:
        return {}

    def pct(p: float) -> int:
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


def joint_coverage(rows, user_counts, shop_counts, user_min=5, shop_min=20) -> dict:
    records = 0
    users = set()
    shops = set()
    for user_id, shop_id in rows:
        if user_counts[user_id] >= user_min and shop_counts[shop_id] >= shop_min:
            records += 1
            users.add(user_id)
            shops.add(shop_id)
    return {
        "rule": f"user>={user_min}, shop>={shop_min}",
        "records": records,
        "users": len(users),
        "shops": len(shops),
    }


def profile_yf() -> dict:
    path = ROOT / "datasets" / "downloads" / "yf_dianping.csv"
    users = Counter()
    shops = Counter()
    pairs = []
    nonempty = 0
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if not row.get("comment", "").strip():
                continue
            user_id = row["userId"]
            shop_id = row["restId"]
            users[user_id] += 1
            shops[shop_id] += 1
            pairs.append((user_id, shop_id))
            nonempty += 1
    return {
        "nonempty_reviews": nonempty,
        "users": coverage(users),
        "businesses": coverage(shops),
        "joint_5_20": joint_coverage(pairs, users, shops),
        "joint_10_20": joint_coverage(pairs, users, shops, 10, 20),
        "joint_5_50": joint_coverage(pairs, users, shops, 5, 50),
    }


def profile_stanford() -> dict:
    path = ROOT / "datasets" / "Stanford_Dianping_Ni" / "dianping.json"
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    users = Counter()
    shops = Counter()
    pairs = []
    missing_user = 0
    for shop_id, shop in data.items():
        for review in shop.get("reviews", []):
            if not str(review.get("text") or "").strip():
                continue
            user_id = str(review.get("member_id") or "").strip()
            if not user_id:
                missing_user += 1
                continue
            users[user_id] += 1
            shops[shop_id] += 1
            pairs.append((user_id, shop_id))
    return {
        "restaurants_total": len(data),
        "reviews_with_user_and_text": len(pairs),
        "reviews_missing_user": missing_user,
        "users": coverage(users),
        "restaurants": coverage(shops),
        "joint_5_20": joint_coverage(pairs, users, shops),
        "joint_10_20": joint_coverage(pairs, users, shops, 10, 20),
        "joint_5_50": joint_coverage(pairs, users, shops, 5, 50),
    }


def profile_pku() -> dict:
    path = ROOT / "datasets" / "PKU_Guangzhou_211" / "大众点评评论数据.csv"
    users = Counter()
    shops = Counter()
    pairs = []
    missing_user = 0
    with path.open("r", encoding="gb18030", newline="") as handle:
        for row in csv.DictReader(handle):
            if not str(row.get("Content_review") or "").strip():
                continue
            shop_id = str(row.get("Merchant") or "").strip()
            user_id = str(row.get("Reviewer") or "").strip()
            if not user_id:
                missing_user += 1
                continue
            users[user_id] += 1
            shops[shop_id] += 1
            pairs.append((user_id, shop_id))
    return {
        "reviews_with_user_and_text": len(pairs),
        "reviews_missing_user": missing_user,
        "reviewer_name_warning": "Reviewer is a displayed name, not a guaranteed stable account ID.",
        "users_by_display_name": coverage(users),
        "restaurants": coverage(shops),
        "joint_5_20": joint_coverage(pairs, users, shops),
        "joint_10_20": joint_coverage(pairs, users, shops, 10, 20),
        "joint_5_50": joint_coverage(pairs, users, shops, 5, 50),
    }


if __name__ == "__main__":
    result = {
        "yf_dianping": profile_yf(),
        "stanford": profile_stanford(),
        "pku": profile_pku(),
    }
    output = ROOT / "datasets" / "portrait_coverage_stats.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
