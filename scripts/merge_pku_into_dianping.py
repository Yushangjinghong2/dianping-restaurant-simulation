import csv
import gzip
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "datasets" / "Dianping_Merged_Restaurants"
PKU_DIR = ROOT / "datasets" / "PKU_Guangzhou_211"
OUT = ROOT / "datasets" / "Dianping_Three_Source_Merged"


def dump_line(handle, row):
    handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def normalize_name(value):
    value = unicodedata.normalize("NFKC", str(value or "")).lower()
    value = value.replace("（", "(").replace("）", ")")
    return re.sub(r"[\s·・•,，。.:：;；\-_—/\\]+", "", value)


def normalize_reviewer(value):
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def stable_id(prefix, value, length=20):
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}:{digest}"


def clean_number(value, integer=False):
    value = str(value or "").strip()
    if not value or value in {"-", "--", "￥", "¥"}:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
    if not match:
        return None
    number = float(match.group(0))
    if integer or number.is_integer():
        return int(number)
    return number


def restaurant_name_variants(row):
    name = str(row.get("name") or "").strip()
    branch = str(row.get("branch") or "").strip()
    values = {name}
    if branch:
        values.update({name + branch, f"{name}({branch})", f"{name}（{branch}）"})
    return {normalize_name(value) for value in values if value}


def main():
    csv_path = next(PKU_DIR.glob("*.csv"))
    OUT.mkdir(parents=True, exist_ok=True)

    pku_rows = []
    merchant_counts = Counter()
    review_id_to_merchants = defaultdict(set)
    with csv_path.open("r", encoding="gb18030", newline="") as handle:
        for row in csv.DictReader(handle):
            merchant = row["Merchant"].strip()
            review_id = row["Review_ID"].strip()
            pku_rows.append(row)
            merchant_counts[merchant] += 1
            if review_id:
                review_id_to_merchants[review_id].add(merchant)

    restaurants = []
    restaurant_by_id = {}
    guangzhou_name_index = defaultdict(set)
    with gzip.open(BASE / "restaurants.jsonl.gz", "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            restaurant_id = str(row["restaurant_id"])
            restaurants.append(row)
            restaurant_by_id[restaurant_id] = row
            if row.get("city") == "广州" or "广州" in str(row.get("address") or ""):
                for variant in restaurant_name_variants(row):
                    guangzhou_name_index[variant].add(restaurant_id)

    existing_review_ids = set()
    existing_review_id_counts = Counter()
    shared_review_mapping = defaultdict(Counter)
    with gzip.open(BASE / "reviews.jsonl.gz", "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            review_id = row.get("review_id")
            if review_id is None:
                continue
            review_id = str(review_id)
            existing_review_ids.add(review_id)
            existing_review_id_counts[review_id] += 1
            if review_id in review_id_to_merchants:
                for merchant in review_id_to_merchants[review_id]:
                    shared_review_mapping[merchant][str(row["restaurant_id"])] += 1

    merchant_mapping = {}
    mapping_method = {}
    mapping_evidence = {}
    for merchant, candidates in shared_review_mapping.items():
        if len(candidates) == 1:
            restaurant_id, evidence = candidates.most_common(1)[0]
            merchant_mapping[merchant] = restaurant_id
            mapping_method[merchant] = "shared_review_id"
            mapping_evidence[merchant] = evidence

    exact_name_matches = 0
    for merchant in merchant_counts:
        if merchant in merchant_mapping:
            continue
        candidates = guangzhou_name_index.get(normalize_name(merchant), set())
        if len(candidates) == 1:
            merchant_mapping[merchant] = next(iter(candidates))
            mapping_method[merchant] = "exact_name_guangzhou"
            mapping_evidence[merchant] = None
            exact_name_matches += 1

    synthetic_merchants = 0
    for merchant in merchant_counts:
        if merchant not in merchant_mapping:
            merchant_mapping[merchant] = stable_id("pku", normalize_name(merchant))
            mapping_method[merchant] = "pku_only"
            mapping_evidence[merchant] = None
            synthetic_merchants += 1

    pku_names_by_restaurant = defaultdict(list)
    methods_by_restaurant = defaultdict(set)
    for merchant, restaurant_id in merchant_mapping.items():
        pku_names_by_restaurant[restaurant_id].append(merchant)
        methods_by_restaurant[restaurant_id].add(mapping_method[merchant])

    with gzip.open(OUT / "restaurants.jsonl.gz", "wt", encoding="utf-8", newline="") as output:
        for row in restaurants:
            restaurant_id = str(row["restaurant_id"])
            augmented = dict(row)
            sources = [str(row.get("source") or "unknown")]
            if restaurant_id in pku_names_by_restaurant:
                sources.append("pku")
                augmented["pku_merchant_names"] = sorted(pku_names_by_restaurant[restaurant_id])
                augmented["pku_match_methods"] = sorted(methods_by_restaurant[restaurant_id])
            augmented["sources"] = list(dict.fromkeys(sources))
            dump_line(output, augmented)

        for merchant in sorted(merchant_counts):
            if mapping_method[merchant] != "pku_only":
                continue
            restaurant_id = merchant_mapping[merchant]
            dump_line(output, {
                "restaurant_id": restaurant_id,
                "name": merchant,
                "branch": None,
                "city": "广州",
                "city_code": None,
                "address": None,
                "category": "粤菜",
                "tags": None,
                "average_cost": None,
                "overall_score": None,
                "flavor_score": None,
                "environment_score": None,
                "service_score": None,
                "latitude": None,
                "longitude": None,
                "url": None,
                "source": "pku",
                "sources": ["pku"],
                "pku_merchant_names": [merchant],
                "pku_match_methods": ["pku_only"],
            })

    duplicate_base_review_ids = {
        review_id for review_id, count in existing_review_id_counts.items() if count > 1
    }
    best_duplicate_rows = {}
    with gzip.open(BASE / "reviews.jsonl.gz", "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            review_id = row.get("review_id")
            if review_id is None or str(review_id) not in duplicate_base_review_ids:
                continue
            review_id = str(review_id)
            score = (
                "更新于" in str(row.get("date") or ""),
                len(str(row.get("content") or "")),
            )
            if review_id not in best_duplicate_rows or score > best_duplicate_rows[review_id][0]:
                best_duplicate_rows[review_id] = (score, row)

    base_duplicate_rows_removed = 0
    duplicate_ids_written = set()
    with gzip.open(OUT / "reviews.jsonl.gz", "wt", encoding="utf-8", newline="") as output:
        with gzip.open(BASE / "reviews.jsonl.gz", "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                review_id = row.get("review_id")
                if review_id is not None and str(review_id) in duplicate_base_review_ids:
                    review_id = str(review_id)
                    if review_id in duplicate_ids_written or row != best_duplicate_rows[review_id][1]:
                        base_duplicate_rows_removed += 1
                        continue
                    duplicate_ids_written.add(review_id)
                dump_line(output, row)

    seen_pku_review_ids = set()
    internal_duplicate_rows = 0
    cross_source_review_id_duplicates = 0
    added_pku_reviews = 0
    pku_users = set()
    with gzip.open(OUT / "reviews.jsonl.gz", "at", encoding="utf-8", newline="") as output:
        for row in pku_rows:
            review_id = row["Review_ID"].strip()
            if review_id in seen_pku_review_ids:
                internal_duplicate_rows += 1
                continue
            seen_pku_review_ids.add(review_id)
            if review_id in existing_review_ids:
                cross_source_review_id_duplicates += 1
                continue

            merchant = row["Merchant"].strip()
            reviewer = normalize_reviewer(row.get("Reviewer"))
            user_id = stable_id("pku_user", reviewer) if reviewer else None
            if user_id:
                pku_users.add(user_id)
            dump_line(output, {
                "review_id": review_id or None,
                "user_id": user_id,
                "restaurant_id": merchant_mapping[merchant],
                "timestamp_ms": None,
                "date": None,
                "date_raw": row.get("Time") or None,
                "overall_rating": clean_number(row.get("Rating"), integer=True),
                "flavor_rating": clean_number(row.get("Score_taste"), integer=True),
                "environment_rating": clean_number(row.get("Score_environment"), integer=True),
                "service_rating": clean_number(row.get("Score_service"), integer=True),
                "cost": clean_number(row.get("Price_per_person")),
                "content": row.get("Content_review") or "",
                "segmented_content": None,
                "thumbs_up": clean_number(row.get("Num_thumbs_up"), integer=True),
                "response_count": clean_number(row.get("Num_ response"), integer=True),
                "reviewer_value": clean_number(row.get("Reviewer_value")),
                "reviewer_rank": row.get("Reviewer_rank") or None,
                "favorite_foods": row.get("Favorite_foods") or None,
                "source": "pku",
            })
            added_pku_reviews += 1

    with gzip.open(OUT / "restaurant_mapping.jsonl.gz", "wt", encoding="utf-8", newline="") as output:
        for merchant in sorted(merchant_counts):
            restaurant_id = merchant_mapping[merchant]
            existing = restaurant_by_id.get(restaurant_id, {})
            dump_line(output, {
                "pku_merchant": merchant,
                "restaurant_id": restaurant_id,
                "match_method": mapping_method[merchant],
                "shared_review_id_count": mapping_evidence[merchant],
                "pku_review_rows": merchant_counts[merchant],
                "unified_name": existing.get("name", merchant),
                "unified_branch": existing.get("branch"),
                "unified_address": existing.get("address"),
            })

    base_stats = json.loads((BASE / "merge_statistics.json").read_text(encoding="utf-8"))
    base_reviews_input = int(base_stats["reviews"]["merged_total"])
    base_reviews = base_reviews_input - base_duplicate_rows_removed
    stats = {
        "sources": ["yongfeng", "stanford", "pku"],
        "restaurant_filter": "Yongfeng/Stanford use the existing high-confidence restaurant filter with drink and dessert venues excluded; PKU contains Guangzhou Cantonese restaurants.",
        "restaurants": {
            "base_merged_rows": len(restaurants),
            "pku_merchants": len(merchant_counts),
            "pku_matched_by_shared_review_id": sum(method == "shared_review_id" for method in mapping_method.values()),
            "pku_matched_by_exact_name": sum(method == "exact_name_guangzhou" for method in mapping_method.values()),
            "pku_only_synthetic_ids": synthetic_merchants,
            "merged_total": len(restaurants) + synthetic_merchants,
        },
        "reviews": {
            "base_merged_input_rows": base_reviews_input,
            "base_duplicate_review_id_rows_removed": base_duplicate_rows_removed,
            "base_merged_rows": base_reviews,
            "pku_input_rows": len(pku_rows),
            "pku_unique_review_ids": len(seen_pku_review_ids),
            "pku_internal_duplicate_rows_removed": internal_duplicate_rows,
            "pku_cross_source_review_id_duplicates_removed": cross_source_review_id_duplicates,
            "pku_reviews_added": added_pku_reviews,
            "merged_total": base_reviews + added_pku_reviews,
        },
        "users": {
            "pku_namespaced_users_in_added_reviews": len(pku_users),
            "pku_user_key": "pku_user:sha256(normalized Reviewer)[:20]",
            "cross_source_user_linking": "not performed because PKU provides display names rather than stable numeric user IDs",
        },
        "notes": [
            "PKU restaurant matches based on shared review IDs are highest confidence.",
            "Exact-name matches are restricted to Guangzhou and require a unique match.",
            "Unmatched PKU merchants receive deterministic pku: IDs and remain separate.",
            "PKU dates are preserved in date_raw because many rows omit the year.",
        ],
    }
    (OUT / "merge_statistics.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    readme = f"""# 大众点评三来源合并数据

本目录合并 Yongfeng 高置信度餐厅子集、Stanford Dianping 和北大广州粤菜数据。原始文件没有被覆盖。

## 文件

| 文件 | 内容 | 记录数 |
| --- | --- | ---: |
| `restaurants.jsonl.gz` | 统一餐厅表 | {stats['restaurants']['merged_total']:,} |
| `reviews.jsonl.gz` | 统一评论表 | {stats['reviews']['merged_total']:,} |
| `restaurant_mapping.jsonl.gz` | 北大餐厅名称到统一商户 ID 的映射及证据 | {len(merchant_counts):,} |
| `merge_statistics.json` | 合并、匹配和去重统计 | — |

## 合并口径

- Yongfeng 与 Stanford 沿用此前的餐厅筛选和合并结果。
- 北大餐厅中，{stats['restaurants']['pku_matched_by_shared_review_id']} 家通过相同 `Review_ID` 接入原始大众点评商户 ID。
- 另有 {stats['restaurants']['pku_matched_by_exact_name']} 家通过广州范围内唯一的规范化餐厅名称接入。
- 剩余 {stats['restaurants']['pku_only_synthetic_ids']} 家使用确定性的 `pku:` 商户 ID，避免错误合并。
- 原两源文件中同一评论 ID 的更新版本重复记录已删除 {base_duplicate_rows_removed} 行，并保留带更新时间或正文更完整的版本。
- 北大内部删除 {internal_duplicate_rows:,} 行重复 `Review_ID`；与已有 Stanford 评论重复的 {cross_source_review_id_duplicates:,} 行也已删除。
- 北大用户昵称生成带 `pku_user:` 前缀的稳定哈希，只用于北大数据内部画像，不与其他来源用户强行关联。
- 北大原始日期经常缺少年份，因此原样保存在 `date_raw`，统一 `date` 暂留空。

## 使用建议

实验以 `restaurant_id` 和 `user_id` 作为关联键。需要审计北大餐厅连接方式时，查询 `restaurant_mapping.jsonl.gz` 的 `match_method` 和 `shared_review_id_count`。
"""
    (OUT / "README.md").write_text(readme, encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
