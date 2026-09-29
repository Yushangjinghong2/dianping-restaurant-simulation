import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "datasets" / "Yongfeng_Dianping" / "dianping"
THRESHOLDS = (1, 2, 3, 5, 10, 20, 50, 100)


def distribution(counts):
    values = sorted(counts.values())
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


def parse_dump(path):
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if " ^ " not in line:
                continue
            key, payload = line.rstrip("\n").split(" ^ ", 1)
            try:
                yield line_number, key, json.loads(payload)
            except json.JSONDecodeError:
                yield line_number, key, None


def nonempty(value):
    if value is None:
        return False
    if isinstance(value, (dict, list)):
        return bool(value)
    return bool(str(value).strip())


def profile_businesses():
    total = 0
    invalid = 0
    ids = set()
    completeness = Counter()
    styles = Counter()
    cities = Counter()
    top_categories = Counter()
    sample = None
    for _, url, row in parse_dump(BASE / "businesses.txt"):
        total += 1
        if row is None:
            invalid += 1
            continue
        business_id = str(row.get("0", "")).strip()
        if business_id:
            ids.add(business_id)
        fields = {
            "name": "1",
            "city_code": "2",
            "platform_score": "3",
            "flavor": "4",
            "environment": "5",
            "service": "6",
            "address": "7",
            "telephone": "8",
            "share_count": "9",
            "description": "10",
            "recommended_dishes": "11",
            "atmosphere": "12",
            "special_service": "13",
            "opening_hours": "14",
            "traffic_route": "15",
            "latitude": "16",
            "longitude": "17",
            "style": "18",
            "average_cost": "19",
            "tags": "20",
            "areas": "21",
        }
        for name, key in fields.items():
            if nonempty(row.get(key)) and str(row.get(key)).strip() not in {"0", "0.0", "{}", "[]"}:
                completeness[name] += 1
        style = str(row.get("18") or "").strip()
        if style:
            styles[style] += 1
        tags = str(row.get("20") or "").strip()
        match = re.search(r"\(0\)(.*?)(?=\(1\)|$)", tags)
        if match:
            top_categories[match.group(1)] += 1
        city = str(row.get("2") or "").strip()
        if city:
            cities[city] += 1
        if sample is None and nonempty(row.get("1")) and nonempty(row.get("18")) and nonempty(row.get("7")):
            sample = {"url": url, **row}
    return {
        "records": total,
        "valid_json": total - invalid,
        "invalid_json": invalid,
        "unique_business_ids": len(ids),
        "field_nonempty": dict(completeness),
        "top_styles": dict(styles.most_common(30)),
        "top_level_categories": dict(top_categories.most_common()),
        "style_distinct": len(styles),
        "city_codes_distinct": len(cities),
        "sample": sample,
    }


def profile_business_review_join():
    metadata = {}
    for _, _, row in parse_dump(BASE / "businesses.txt"):
        if row is None:
            continue
        business_id = str(row.get("0") or "").strip()
        if business_id:
            metadata[business_id] = {
                "name": nonempty(row.get("1")),
                "city": nonempty(row.get("2")),
                "address": nonempty(row.get("7")),
                "coordinates": nonempty(row.get("16")) and nonempty(row.get("17")),
                "style": nonempty(row.get("18")),
                "tags": nonempty(row.get("20")),
            }
    reviewed = set()
    for _, _, row in parse_dump(BASE / "reviews.txt"):
        if row is not None and row.get("restId") not in (None, -1, "-1"):
            reviewed.add(str(row["restId"]))
    matched = reviewed.intersection(metadata)
    result = {
        "reviewed_business_ids": len(reviewed),
        "matched_to_metadata": len(matched),
        "missing_from_metadata": len(reviewed - matched),
    }
    for field in ("name", "city", "address", "coordinates", "style", "tags"):
        result[f"matched_with_{field}"] = sum(metadata[business_id][field] for business_id in matched)
    return result


def profile_reviews():
    total = 0
    invalid = 0
    missing_user = 0
    missing_business = 0
    nonempty_content = 0
    users_all = Counter()
    users_text = Counter()
    businesses_all = Counter()
    businesses_text = Counter()
    fields = Counter()
    rates = Counter()
    min_time = None
    max_time = None
    sample = None
    for _, url, row in parse_dump(BASE / "reviews.txt"):
        total += 1
        if row is None:
            invalid += 1
            continue
        user_id = row.get("userId")
        business_id = row.get("restId")
        user_known = user_id not in (None, -1, "-1")
        business_known = business_id not in (None, -1, "-1")
        if user_known:
            users_all[str(user_id)] += 1
        else:
            missing_user += 1
        if business_known:
            businesses_all[str(business_id)] += 1
        else:
            missing_business += 1
        content = str(row.get("content") or "").strip()
        if content:
            nonempty_content += 1
            if user_known:
                users_text[str(user_id)] += 1
            if business_known:
                businesses_text[str(business_id)] += 1
        for name in ("rate", "flavor", "environment", "service"):
            if row.get(name) not in (None, -1, "-1"):
                fields[f"known_{name}"] += 1
        if row.get("cost") not in (None, 0, "0", -1, "-1"):
            fields["known_cost"] += 1
        if row.get("stage") not in (None, -1, "-1"):
            fields["known_stage"] += 1
        if row.get("waiting") not in (None, -1, "-1"):
            fields["known_waiting"] += 1
        for name in ("dishes", "atmosphere", "special"):
            if nonempty(row.get(name)):
                fields[f"nonempty_{name}"] += 1
        rate = row.get("rate")
        rates[str(rate)] += 1
        timestamp = row.get("time")
        if isinstance(timestamp, (int, float)) and timestamp > 0:
            min_time = timestamp if min_time is None else min(min_time, timestamp)
            max_time = timestamp if max_time is None else max(max_time, timestamp)
        if sample is None and content and user_known and business_known:
            sample = {"url": url, **row}
    to_date = lambda ms: datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat() if ms else None
    return {
        "records": total,
        "valid_json": total - invalid,
        "invalid_json": invalid,
        "nonempty_content": nonempty_content,
        "missing_user_id": missing_user,
        "missing_business_id": missing_business,
        "users_all": distribution(users_all),
        "users_with_text": distribution(users_text),
        "businesses_all": distribution(businesses_all),
        "businesses_with_text": distribution(businesses_text),
        "field_coverage": dict(fields),
        "rating_values": dict(rates),
        "date_min_utc": to_date(min_time),
        "date_max_utc": to_date(max_time),
        "sample": sample,
    }


def main():
    result = {
        "source_archive": str(ROOT.parent / "dianping.zip"),
        "businesses": profile_businesses(),
        "reviews": profile_reviews(),
        "business_review_join": profile_business_review_join(),
    }
    output = ROOT / "datasets" / "Yongfeng_Dianping" / "statistics.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
