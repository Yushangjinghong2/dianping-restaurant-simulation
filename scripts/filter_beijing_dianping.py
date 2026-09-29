"""Create a city-filtered subset from the merged Dianping dataset."""

import collections
import gzip
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "datasets" / "Dianping_Three_Source_Merged"
OUTPUT = ROOT / "datasets" / "Dianping_Beijing_Subset"
CITY = "北京"


def read_jsonl_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def write_jsonl_gz(path, records):
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    restaurants = []
    restaurant_ids = set()
    restaurant_sources = collections.Counter()

    for restaurant in read_jsonl_gz(SOURCE / "restaurants.jsonl.gz"):
        if restaurant.get("city") != CITY:
            continue
        restaurants.append(restaurant)
        restaurant_ids.add(str(restaurant["restaurant_id"]))
        restaurant_sources[restaurant.get("source", "unknown")] += 1

    review_counts = collections.Counter()
    rating_counts = collections.Counter()
    nonempty_content = 0

    def selected_reviews():
        nonlocal nonempty_content
        for review in read_jsonl_gz(SOURCE / "reviews.jsonl.gz"):
            if str(review.get("restaurant_id")) not in restaurant_ids:
                continue
            review_counts[review.get("source", "unknown")] += 1
            rating = review.get("overall_rating")
            if rating is not None:
                rating_counts[str(rating)] += 1
            if review.get("content"):
                nonempty_content += 1
            yield review

    write_jsonl_gz(OUTPUT / "restaurants.jsonl.gz", restaurants)
    write_jsonl_gz(OUTPUT / "reviews.jsonl.gz", selected_reviews())

    stats = {
        "source_dataset": "Dianping_Three_Source_Merged",
        "filter": "restaurant.city exactly equals 北京; reviews joined by restaurant_id",
        "restaurants": {
            "total": len(restaurants),
            "by_source": dict(restaurant_sources),
            "with_address": sum(bool(item.get("address")) for item in restaurants),
        },
        "reviews": {
            "total": sum(review_counts.values()),
            "by_source": dict(review_counts),
            "with_nonempty_content": nonempty_content,
            "overall_rating_counts": dict(rating_counts),
        },
        "note": "Address strings commonly contain district/street only; the normalized restaurant city field was used to avoid missing Beijing records whose address omits 北京市.",
    }
    (OUTPUT / "statistics.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    readme = f"""# 大众点评北京地区子集

来源：`../Dianping_Three_Source_Merged` 三源合并数据。

筛选以餐厅表 `city` 字段严格等于“北京”为准，并通过 `restaurant_id` 关联评论。北京商户地址通常只写区县和街道、不重复写“北京市”，所以不能只搜索地址字符串中的“北京”，否则会漏掉大量北京商户。原合并数据未修改。

| 文件 | 内容 | 数量 |
| --- | --- | ---: |
| `restaurants.jsonl.gz` | 北京餐厅记录 | {len(restaurants):,} |
| `reviews.jsonl.gz` | 上述餐厅关联的评论 | {sum(review_counts.values()):,} |
| `statistics.json` | 来源、评论正文和评分统计 | — |

地区是餐厅所在地；数据不含顾客居住地。各字段结构沿用来源合并数据。
"""
    (OUTPUT / "README.md").write_text(readme, encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
