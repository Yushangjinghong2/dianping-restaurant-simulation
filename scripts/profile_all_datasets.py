import csv
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "datasets"
THRESHOLDS = (1, 2, 3, 5, 10, 20, 50, 100)


def coverage(counts: Counter) -> dict:
    values = sorted(counts.values())
    if not values:
        return {}

    def pct(p: float) -> int:
        return values[round((len(values) - 1) * p)]

    history_bins = {
        "1": sum(v == 1 for v in values),
        "2": sum(v == 2 for v in values),
        "3-4": sum(3 <= v <= 4 for v in values),
        "5-9": sum(5 <= v <= 9 for v in values),
        "10-19": sum(10 <= v <= 19 for v in values),
        "20-49": sum(20 <= v <= 49 for v in values),
        "50-99": sum(50 <= v <= 99 for v in values),
        "100+": sum(v >= 100 for v in values),
    }
    result = {
        "entities": len(values),
        "records": sum(values),
        "median": pct(0.50),
        "p75": pct(0.75),
        "p90": pct(0.90),
        "p95": pct(0.95),
        "p99": pct(0.99),
        "max": values[-1],
        "entities_at_least": {str(t): sum(v >= t for v in values) for t in THRESHOLDS},
        "history_bins": history_bins,
    }
    if len(values) <= 100:
        result["entity_values"] = values
    return result


def profile_asap() -> dict:
    base = DATASETS / "ASAP" / "data"
    stars = Counter()
    aspect_mentions = Counter()
    rows_by_split = {}
    aspect_columns = []
    for split in ("train", "dev", "test"):
        count = 0
        with (base / f"{split}.csv").open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not aspect_columns:
                aspect_columns = [c for c in reader.fieldnames or [] if "#" in c]
            for row in reader:
                count += 1
                stars[str(int(float(row["star"])))] += 1
                for aspect in aspect_columns:
                    if row[aspect] != "-2":
                        aspect_mentions[aspect] += 1
        rows_by_split[split] = count
    return {
        "records": sum(rows_by_split.values()),
        "splits": rows_by_split,
        "users": None,
        "restaurants": None,
        "stars": dict(sorted(stars.items())),
        "aspect_columns": len(aspect_columns),
        "aspect_mentions": dict(aspect_mentions.most_common()),
    }


def profile_sequential() -> dict:
    path = DATASETS / "Dianping_SequentialRec" / "Dianping_SequentialRec" / "actions.txt"
    users = Counter()
    items = Counter()
    ratings = Counter()
    dates = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            user_id, item_id, rating, date, *_ = line.rstrip("\n").split(",")
            users[user_id] += 1
            items[item_id] += 1
            ratings[rating] += 1
            dates.append(date)
    return {
        "actions": sum(users.values()),
        "users": coverage(users),
        "restaurants": coverage(items),
        "rating_values": dict(sorted(ratings.items())),
        "date_min": min(dates),
        "date_max": max(dates),
    }


def profile_social() -> dict:
    base = DATASETS / "Dianping_SocialRec_2015" / "Dianping_SocialRec_2015"
    users = Counter()
    items = Counter()
    ratings = Counter()
    dates = []
    with (base / "rating.txt").open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            user_id, item_id, rating, date = line.rstrip("\n").split("|")
            users[user_id] += 1
            items[item_id] += 1
            ratings[rating] += 1
            dates.append(date)
    friend_degree = Counter()
    with (base / "user.txt").open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            user_id, friends = line.rstrip("\n").split("|", 1)
            friend_degree[user_id] = len(friends.split()) if friends.strip() else 0
    return {
        "ratings": sum(users.values()),
        "users_with_ratings": coverage(users),
        "restaurants": coverage(items),
        "rating_values": dict(sorted(ratings.items())),
        "date_min": min(dates),
        "date_max": max(dates),
        "users_in_social_file": len(friend_degree),
        "friend_degree": coverage(friend_degree),
    }


def count_csv(path: Path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        count = sum(1 for _ in reader)
    return header, count


def profile_sandwich() -> dict:
    base = DATASETS / "Sandwich_Analytics_25_Stores"
    receipt_stores = Counter()
    drive_thru = Counter()
    return_values = Counter()
    with (base / "E1_Receipts.csv").open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            receipt_stores[row["Store_Num"]] += 1
            drive_thru[row["Drive_Thru"]] += 1
            return_values[row["Return"]] += 1

    item_stores = Counter()
    menu_items_seen = set()
    units = 0
    item_rows = 0
    with (base / "E3_Item_on_Receipt.csv").open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            item_rows += 1
            receipt_id = row["Receipt_ID"]
            item_stores[receipt_id.split("_", 1)[0]] += 1
            menu_items_seen.add(row["Inv_Num"])
            try:
                units += int(float(row["Count"]))
            except ValueError:
                pass

    _, payment_rows = count_csv(base / "E2_Payment.csv")
    _, menu_rows = count_csv(base / "E4_Menu_Items.csv")
    _, ingredient_link_rows = count_csv(base / "E5_Ing_in_Item.csv")
    _, ingredient_rows = count_csv(base / "E6_Ingredients.csv")
    _, weather_rows = count_csv(base / "E7_Weather.csv")
    _, attribute_rows = count_csv(base / "E8_Attributes.csv")
    return {
        "users": None,
        "receipt_count": sum(receipt_stores.values()),
        "receipts_per_store": coverage(receipt_stores),
        "drive_thru_values": dict(drive_thru),
        "return_values": dict(return_values),
        "payment_rows": payment_rows,
        "item_detail_rows": item_rows,
        "item_detail_units": units,
        "item_rows_per_store": coverage(item_stores),
        "menu_rows": menu_rows,
        "menu_items_seen_in_sales": len(menu_items_seen),
        "ingredient_link_rows": ingredient_link_rows,
        "ingredient_rows": ingredient_rows,
        "weather_rows": weather_rows,
        "store_attribute_rows": attribute_rows,
    }


if __name__ == "__main__":
    portrait_path = DATASETS / "portrait_coverage_stats.json"
    portrait = json.loads(portrait_path.read_text(encoding="utf-8"))
    yongfeng = json.loads(
        (DATASETS / "Yongfeng_Dianping" / "statistics.json").read_text(encoding="utf-8")
    )
    result = {
        "Yongfeng_Dianping": yongfeng,
        "yf_dianping": portrait["yf_dianping"],
        "stanford": portrait["stanford"],
        "pku": portrait["pku"],
        "ASAP": profile_asap(),
        "SequentialRec": profile_sequential(),
        "SocialRec": profile_social(),
        "Sandwich_Analytics": profile_sandwich(),
    }
    output = DATASETS / "all_datasets_profile_stats.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
