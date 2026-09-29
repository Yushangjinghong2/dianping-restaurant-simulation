import csv
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def summarize_counts(counts: Counter) -> dict:
    values = sorted(counts.values())
    total = len(values)

    def percentile(p: float) -> int:
        if not values:
            return 0
        return values[round((total - 1) * p)]

    return {
        "entities": total,
        "events": sum(values),
        "min": values[0] if values else 0,
        "p25": percentile(0.25),
        "median": percentile(0.50),
        "p75": percentile(0.75),
        "p90": percentile(0.90),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "max": values[-1] if values else 0,
        "at_least_2": sum(v >= 2 for v in values),
        "at_least_5": sum(v >= 5 for v in values),
        "at_least_10": sum(v >= 10 for v in values),
        "at_least_20": sum(v >= 20 for v in values),
        "at_least_50": sum(v >= 50 for v in values),
    }


def profile_yf() -> dict:
    path = ROOT / "datasets" / "downloads" / "yf_dianping.csv"
    users = Counter()
    shops = Counter()
    nonempty_comment_users = Counter()
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            users[row["userId"]] += 1
            shops[row["restId"]] += 1
            if row.get("comment", "").strip():
                nonempty_comment_users[row["userId"]] += 1
    return {
        "user_history_all": summarize_counts(users),
        "user_history_with_comment": summarize_counts(nonempty_comment_users),
        "shop_history_all": summarize_counts(shops),
    }


def profile_sequential() -> dict:
    path = ROOT / "datasets" / "Dianping_SequentialRec" / "Dianping_SequentialRec" / "actions.txt"
    users = Counter()
    items = Counter()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            user_id, item_id, *_ = line.rstrip("\n").split(",")
            users[user_id] += 1
            items[item_id] += 1
    return {
        "user_history": summarize_counts(users),
        "item_history": summarize_counts(items),
    }


if __name__ == "__main__":
    print(json.dumps({"yf_dianping": profile_yf(), "SequentialRec": profile_sequential()}, ensure_ascii=False, indent=2))
