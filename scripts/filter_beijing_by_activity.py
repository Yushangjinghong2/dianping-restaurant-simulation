"""Apply sequential restaurant/customer activity filters to Beijing Dianping."""

import collections
import gzip
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "datasets" / "Dianping_Beijing_Subset"
OUTPUT = ROOT / "datasets" / "Dianping_Beijing_Restaurant200_Customer20"
RESTAURANT_LIMIT = 200  # strict: more than 200 comments
CUSTOMER_LIMIT = 20  # strict: more than 20 comments


def read_rows(path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def valid_user_id(value):
    return value not in (None, "", -1, "-1")


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    restaurants_by_id = {
        str(row["restaurant_id"]): row
        for row in read_rows(SOURCE / "restaurants.jsonl.gz")
    }

    restaurant_counts = collections.Counter()
    global_customer_counts = collections.Counter()
    total_beijing_reviews = 0
    for review in read_rows(SOURCE / "reviews.jsonl.gz"):
        total_beijing_reviews += 1
        restaurant_counts[str(review["restaurant_id"])] += 1
        user_id = review.get("user_id")
        if valid_user_id(user_id):
            global_customer_counts[str(user_id)] += 1

    restaurant_ids_gt200 = {
        restaurant_id
        for restaurant_id, count in restaurant_counts.items()
        if count > RESTAURANT_LIMIT
    }
    stage_reviews = OUTPUT / "stage_restaurants_gt200" / "reviews.jsonl.gz"
    stage_reviews.parent.mkdir(parents=True, exist_ok=True)
    stage_customer_counts = collections.Counter()
    stage_review_count = 0
    stage_source_counts = collections.Counter()
    with gzip.open(stage_reviews, "wt", encoding="utf-8", newline="") as output:
        for review in read_rows(SOURCE / "reviews.jsonl.gz"):
            if str(review["restaurant_id"]) not in restaurant_ids_gt200:
                continue
            output.write(json.dumps(review, ensure_ascii=False) + "\n")
            stage_review_count += 1
            stage_source_counts[review.get("source", "unknown")] += 1
            user_id = review.get("user_id")
            if valid_user_id(user_id):
                stage_customer_counts[str(user_id)] += 1

    customers_gt20_local = {
        user_id for user_id, count in stage_customer_counts.items()
        if count > CUSTOMER_LIMIT
    }
    customer_stage_dir = OUTPUT / "stage_customers_gt20"
    customer_stage_dir.mkdir(parents=True, exist_ok=True)
    final_review_counts = collections.Counter()
    final_customer_counts = collections.Counter()
    final_review_total = 0
    with gzip.open(customer_stage_dir / "reviews.jsonl.gz", "wt", encoding="utf-8", newline="") as output:
        for review in read_rows(stage_reviews):
            user_id = str(review.get("user_id"))
            if user_id not in customers_gt20_local:
                continue
            output.write(json.dumps(review, ensure_ascii=False) + "\n")
            final_review_total += 1
            final_review_counts[str(review["restaurant_id"])] += 1
            final_customer_counts[user_id] += 1

    # Also measure the alternative reading: customer history >20 across all
    # Beijing data, then inspect those users within the >200-comment restaurants.
    global_customers_gt20 = {
        user_id for user_id, count in global_customer_counts.items()
        if count > CUSTOMER_LIMIT
    }
    alternative_restaurant_counts = collections.Counter()
    alternative_users = set()
    alternative_reviews = 0
    for review in read_rows(stage_reviews):
        user_id = str(review.get("user_id"))
        if user_id in global_customers_gt20:
            alternative_reviews += 1
            alternative_users.add(user_id)
            alternative_restaurant_counts[str(review["restaurant_id"])] += 1

    stage_restaurant_dir = OUTPUT / "stage_restaurants_gt200"
    write_rows(
        stage_restaurant_dir / "restaurants.jsonl.gz",
        (restaurants_by_id[restaurant_id] for restaurant_id in sorted(restaurant_ids_gt200)),
    )
    write_rows(
        stage_restaurant_dir / "customers.jsonl.gz",
        ({"user_id": user_id, "review_count": count}
         for user_id, count in sorted(stage_customer_counts.items())),
    )
    final_restaurant_ids = set(final_review_counts)
    write_rows(
        customer_stage_dir / "restaurants.jsonl.gz",
        (restaurants_by_id[restaurant_id] for restaurant_id in sorted(final_restaurant_ids)),
    )
    write_rows(
        customer_stage_dir / "customers.jsonl.gz",
        ({"user_id": user_id, "review_count": count}
         for user_id, count in sorted(final_customer_counts.items())),
    )

    stats = {
        "source_dataset": "Dianping_Beijing_Subset",
        "thresholds": {
            "restaurant_review_count": "> 200",
            "customer_review_count": "> 20",
            "review_count_basis": "all comment records, including empty content",
        },
        "beijing_baseline": {
            "restaurants": len(restaurants_by_id),
            "reviews": total_beijing_reviews,
            "customers_with_valid_id": len(global_customer_counts),
        },
        "stage_restaurants_gt200": {
            "restaurants": len(restaurant_ids_gt200),
            "reviews": stage_review_count,
            "reviews_by_source": dict(stage_source_counts),
            "customers": len(stage_customer_counts),
            "max_reviews_per_customer_in_stage": max(stage_customer_counts.values(), default=0),
        },
        "stage_customers_gt20_within_restaurant_subset": {
            "customers": len(customers_gt20_local),
            "reviews": final_review_total,
            "restaurants_with_remaining_reviews": len(final_restaurant_ids),
            "restaurants_still_over_200_after_customer_filter": sum(
                count > RESTAURANT_LIMIT for count in final_review_counts.values()
            ),
        },
        "alternative_customer_threshold_over_all_beijing_reviews": {
            "customers_over_20_globally": len(global_customers_gt20),
            "their_reviews_inside_restaurants_over_200": alternative_reviews,
            "customers_present_in_that_intersection": len(alternative_users),
            "restaurants_with_at_least_one_such_review": len(alternative_restaurant_counts),
            "restaurants_still_over_200_after_that_filter": sum(
                count > RESTAURANT_LIMIT for count in alternative_restaurant_counts.values()
            ),
        },
    }
    (OUTPUT / "statistics.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUTPUT / "README.md").write_text(
        """# 北京餐厅与顾客评论数筛选

来源为 `../Dianping_Beijing_Subset`。评论数按所有评论记录计算，包括正文为空的记录；两个阈值均为严格大于。

1. `stage_restaurants_gt200/`：保留评论数 >200 的餐厅，并包含这些餐厅的全部评论和评论者计数。
2. `stage_customers_gt20/`：在第 1 步评论中，保留累计评论数 >20 的顾客及其评论，再保留仍有这些顾客评论的餐厅。

逐层口径的分步数量和另一种“顾客 >20 按整个北京数据计算”的口径见 `statistics.json`。北京原始子集未改动。
""",
        encoding="utf-8",
    )
    print(json.dumps(stats, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
