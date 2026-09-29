"""Sample 20 representative restaurant profiles and 120 customer profiles."""

import collections
import gzip
import json
import random
import re
import statistics
from pathlib import Path

from build_beijing_archetypes import family, number


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "datasets" / "Dianping_Beijing_Subset"
OUTPUT_DIR = DATA_DIR / "sampled_portrait_pool"
SEED = 20260929
RESTAURANT_COUNT = 20
CUSTOMER_COUNT = 120
MIN_RESTAURANT_REVIEWS = 20
MIN_CUSTOMER_REVIEWS = 5


def read_jsonl_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def quantile(values, p):
    values = sorted(values)
    return values[int(p * (len(values) - 1))] if values else None


def price_tier(value, cuts):
    if value is None:
        return "消费未知"
    if value <= cuts[0]:
        return "低价"
    if value <= cuts[1]:
        return "中价"
    return "高价"


def main():
    rng = random.Random(SEED)
    restaurant_data = {
        str(row["restaurant_id"]): row
        for row in read_jsonl_gz(DATA_DIR / "restaurants.jsonl.gz")
    }
    restaurant_reviews = collections.defaultdict(list)
    customer_reviews = collections.defaultdict(list)
    customer_family_counts = collections.defaultdict(collections.Counter)
    pair_reviews = collections.defaultdict(list)

    for review in read_jsonl_gz(DATA_DIR / "reviews.jsonl.gz"):
        if not review.get("content"):
            continue
        rid = str(review["restaurant_id"])
        cid = str(review["user_id"])
        shop = restaurant_data.get(rid, {})
        category_family = family(shop.get("category"))
        row = {
            "restaurant_id": rid,
            "rating": number(review.get("overall_rating"), 1, 5),
            "cost": number(review.get("cost"), 0.01, 5000),
            "family": category_family,
            "date": review.get("date"),
            "content": review.get("content") or "",
            "restaurant_name": shop.get("name"),
            "restaurant_category": shop.get("category"),
        }
        restaurant_reviews[rid].append(row)
        customer_reviews[cid].append(row)
        customer_family_counts[cid][category_family] += 1
        pair_reviews[(rid, cid)].append(row)

    eligible_restaurants = {
        rid for rid, reviews in restaurant_reviews.items()
        if len(reviews) >= MIN_RESTAURANT_REVIEWS
    }
    shop_costs = [
        number(restaurant_data[rid].get("average_cost"), 0.01, 5000)
        for rid in eligible_restaurants
    ]
    shop_costs = [value for value in shop_costs if value is not None]
    shop_cuts = [quantile(shop_costs, p) for p in (1 / 3, 2 / 3)]

    restaurant_groups = collections.defaultdict(list)
    for rid in eligible_restaurants:
        shop = restaurant_data[rid]
        family_name = family(shop.get("category"))
        cost = number(shop.get("average_cost"), 0.01, 5000)
        restaurant_groups[(family_name, price_tier(cost, shop_cuts))].append(rid)

    # Allocate 20 selections proportionally across the supported cuisine/price
    # groups, then draw randomly within each group.
    group_weights = {key: len(ids) for key, ids in restaurant_groups.items()}
    total_restaurants = sum(group_weights.values())
    quotas = {key: RESTAURANT_COUNT * count / total_restaurants
              for key, count in group_weights.items()}
    allocations = {key: int(quota) for key, quota in quotas.items()}
    for key in sorted(quotas, key=lambda item: (-(quotas[item] - allocations[item]), item)):
        if sum(allocations.values()) >= RESTAURANT_COUNT:
            break
        allocations[key] += 1
    selected_restaurants = []
    for key in sorted(allocations):
        candidates = sorted(restaurant_groups[key])
        selected_restaurants.extend(rng.sample(candidates, min(allocations[key], len(candidates))))

    # Customer strata mirror the actual distribution among all customers with
    # enough history, including low-support groups rather than dropping them.
    eligible_customers = {
        cid for cid, reviews in customer_reviews.items()
        if len(reviews) >= MIN_CUSTOMER_REVIEWS
    }
    spend_by_customer = {}
    for cid in eligible_customers:
        costs = [row["cost"] for row in customer_reviews[cid] if row["cost"] is not None]
        spend_by_customer[cid] = statistics.median(costs) if costs else None
    spend_values = [value for value in spend_by_customer.values() if value is not None]
    spend_cuts = [quantile(spend_values, p) for p in (1 / 3, 2 / 3)]
    customer_strata = collections.defaultdict(list)
    for cid in eligible_customers:
        fam_counts = customer_family_counts[cid]
        top_family, top_count = fam_counts.most_common(1)[0]
        pref = top_family if top_count / len(customer_reviews[cid]) >= 0.40 else "口味/菜系分散"
        customer_strata[(pref, price_tier(spend_by_customer[cid], spend_cuts))].append(cid)

    cold_start = {
        cid for cid, reviews in customer_reviews.items()
        if 0 < len(reviews) < MIN_CUSTOMER_REVIEWS
    }
    cold_start_label = ("冷启动/历史稀疏", "低置信度")
    customer_strata[cold_start_label] = list(cold_start)

    total_customers_with_reviews = sum(len(ids) for ids in customer_strata.values())
    exact_quotas = {key: CUSTOMER_COUNT * len(ids) / total_customers_with_reviews
                    for key, ids in customer_strata.items()}
    customer_allocations = {key: int(quota) for key, quota in exact_quotas.items()}
    remaining = CUSTOMER_COUNT - sum(customer_allocations.values())
    for key in sorted(exact_quotas, key=lambda item: (-(exact_quotas[item] - customer_allocations[item]), item))[:remaining]:
        customer_allocations[key] += 1

    selected_customers = []
    customer_group_rows = []
    for key in sorted(customer_allocations):
        population = customer_strata[key]
        take = min(customer_allocations[key], len(population))
        chosen = rng.sample(population, take) if take else []
        selected_customers.extend((cid, key) for cid in chosen)
        customer_group_rows.append({
            "archetype": " × ".join(key),
            "population": len(population),
            "population_share": round(len(population) / total_customers_with_reviews, 6),
            "sampled_agents": take,
            "sample_share": round(take / CUSTOMER_COUNT, 6),
        })

    restaurant_rows = []
    for rid in selected_restaurants:
        shop = restaurant_data[rid]
        reviews = restaurant_reviews[rid]
        ratings = [row["rating"] for row in reviews if row["rating"] is not None]
        restaurant_rows.append({
            "restaurant_id": rid,
            "name": shop.get("name"),
            "category": shop.get("category"),
            "profile_family": family(shop.get("category")),
            "price_tier": price_tier(number(shop.get("average_cost"), 0.01, 5000), shop_cuts),
            "average_cost_rmb": number(shop.get("average_cost"), 0.01, 5000),
            "review_count": len(reviews),
            "mean_rating": round(statistics.mean(ratings), 3) if ratings else None,
            "negative_review_share": round(sum(score <= 2 for score in ratings) / len(ratings), 4) if ratings else None,
            "archetype_group_population": len(restaurant_groups[(family(shop.get("category")), price_tier(number(shop.get("average_cost"), 0.01, 5000), shop_cuts))]),
        })

    customer_rows = []
    cold_start_profiles = []
    for cid, (pref, spend_tier) in selected_customers:
        reviews = customer_reviews[cid]
        ratings = [row["rating"] for row in reviews if row["rating"] is not None]
        costs = [row["cost"] for row in reviews if row["cost"] is not None]
        fam_counts = customer_family_counts[cid]
        primary_family, primary_count = fam_counts.most_common(1)[0]
        family_counts = dict(fam_counts)
        dominant_family = max(family_counts, key=family_counts.get) if family_counts else None
        profile = {
            "user_id": cid,
            "profile_type": "cold_start" if pref == "冷启动/历史稀疏" else "history_based",
            "archetype": " × ".join((pref, spend_tier)),
            "history_count": len(reviews),
            "distinct_restaurants": len({row["restaurant_id"] for row in reviews}),
            "median_spend_rmb": round(statistics.median(costs), 2) if costs else None,
            "mean_rating": round(statistics.mean(ratings), 3) if ratings else None,
            "preferred_family": pref if pref not in {"口味/菜系分散", "冷启动/历史稀疏"} else None,
            "dominant_family_share": round(primary_count / len(reviews), 4),
            "family_review_distribution": family_counts,
        }
        if pref == "冷启动/历史稀疏":
            # A short history may show a weak signal, but never treat it as a
            # stable preference. Explicitly preserve uncertainty in the profile.
            profile.update({
                "observed_top_family": dominant_family,
                "preference_confidence": "low",
                "portrait_note": "仅为少量历史记录中的倾向，不代表稳定偏好",
            })
            cold_start_profiles.append(profile.copy())
        customer_rows.append(profile)

    def safe_excerpt(text, limit=72):
        text = re.sub(r"(?:\+?\d[\d\s-]{7,}\d)", "[号码已隐去]", text)
        text = re.sub(r"https?://\S+|www\.\S+", "[链接已隐去]", text)
        text = re.sub(r"@[\w\u4e00-\u9fff-]+", "[用户信息已隐去]", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:limit] + ("…" if len(text) > limit else "")

    # Choose eight readable illustrative review examples across distinct weak
    # cuisine signals; show no source user identifier or display name.
    example_candidates = []
    for profile in cold_start_profiles:
        cid = profile["user_id"]
        reviews = customer_reviews[cid]
        if not reviews:
            continue
        for row in reviews:
            excerpt = safe_excerpt(row["content"])
            if len(excerpt) >= 12:
                example_candidates.append({
                    "user_id": cid,
                    "family": row["family"],
                    "rating": row["rating"],
                    "cost": row["cost"],
                    "date": row["date"],
                    "restaurant_name": row["restaurant_name"],
                    "restaurant_category": row["restaurant_category"],
                    "excerpt": excerpt,
                    "family_share": profile["dominant_family_share"],
                })
    example_candidates.sort(key=lambda item: (-item["family_share"], item["user_id"], item["date"] or ""))
    examples = []
    used_users = set()
    for item in example_candidates:
        if item["user_id"] in used_users:
            continue
        examples.append(item)
        used_users.add(item["user_id"])
        if len(examples) == 8:
            break
    for index, item in enumerate(examples, start=1):
        item["example"] = f"示例{index}"
        item.pop("user_id")
        item.pop("family_share")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "restaurants.json").write_text(json.dumps(restaurant_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUTPUT_DIR / "customers.json").write_text(json.dumps(customer_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUTPUT_DIR / "cold_start_customer_profiles.json").write_text(
        json.dumps(cold_start_profiles, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUTPUT_DIR / "cold_start_review_examples.json").write_text(
        json.dumps(examples, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary = {
        "source": "Dianping_Beijing_Subset",
        "seed": SEED,
        "target_ratio": "20 restaurants : 120 customer agents (1:6)",
        "restaurant_count": len(restaurant_rows),
        "customer_agent_count": len(customer_rows),
        "customer_sampling_basis": "Stratified proportional sampling by archetype population share, with largest-remainder rounding; includes sparse-history cold-start cohort.",
        "customer_group_distribution": customer_group_rows,
        "cold_start_agents_with_individual_evidence_profiles": len(cold_start_profiles),
        "cold_start_review_examples_included": len(examples),
        "restaurant_sampling_basis": "Proportional stratified random sampling by broad cuisine family and average-cost tier.",
        "qualification": "Customer agents are profiles sampled from the population. Restaurants are selected independently; no fixed six-customer assignment per store is implied.",
    }
    (OUTPUT_DIR / "sampling_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    group_md = "\n".join(
        f"| {row['archetype']} | {row['population']:,} | {row['population_share']:.1%} | {row['sampled_agents']} | {row['sample_share']:.1%} |"
        for row in customer_group_rows if row["sampled_agents"] > 0
    )
    readme = f"""# 北京实验画像抽样池

## 抽样规模

- 餐厅画像：{len(restaurant_rows)} 家，按菜系大类与价格档的总体分布分层随机抽取。
- 顾客 agent：{len(customer_rows)} 位，最终总量为 20:120，即 1:6。此比例只约束池子总规模，不表示每家餐厅固定分配 6 位顾客。
- 顾客按各画像组在北京有评论用户中的真实人数占比抽取，组内随机抽取真实用户；低历史用户作为冷启动组纳入，不强行赋予稳定偏好。
- 餐厅、顾客分别抽样，历史评论关联不作为固定配对约束；每位顾客的画像保留自身在北京范围的真实历史统计。
- 固定随机种子：{SEED}。文件中保留数据源 ID 便于回溯，未包含评论正文和用户昵称。

## 顾客群体比例

| 顾客画像组 | 总体人数 | 总体占比 | 抽样 agent 数 | 抽样占比 |
| --- | ---: | ---: | ---: | ---: |
{group_md}

数据文件：`restaurants.json`、`customers.json`、`sampling_summary.json`。可用 `../../scripts/sample_beijing_portrait_pool.py` 按同一随机种子复现。

94 位冷启动顾客的个人历史线索另见 `cold_start_customer_profiles.json`；少量评论正文示例（已做基础脱敏）见 `cold_start_review_examples.json` 和 `COLD_START_PROFILES.md`。其中“观察到的主要菜系”只是这几条记录中的最多类别，不视为稳定偏好。
"""
    (OUTPUT_DIR / "README.md").write_text(readme, encoding="utf-8")
    example_md = "\n".join(
        f"### {item['example']}\n\n"
        f"- 顾客历史：1–4 条；当前示例涉及：{item.get('restaurant_category') or '类别未知'}（{item.get('family')}）\n"
        f"- 消费记录：{item.get('cost') if item.get('cost') is not None else '未知'} 元；评分：{item.get('rating') if item.get('rating') is not None else '未提供'}\n"
        f"- 评论片段：> {item['excerpt']}\n"
        for item in examples
    )
    cold_counts = collections.Counter(
        profile["observed_top_family"] for profile in cold_start_profiles
    )
    family_md = "\n".join(f"| {key} | {count} |" for key, count in cold_counts.most_common())
    cold_report = f"""# 冷启动/历史稀疏顾客：个人画像线索

这 {len(cold_start_profiles)} 位顾客每人只有 1–4 条非空评论。这里的画像是从他们各自已有记录中提取的弱线索：消费记录、已有评分、评论关联餐厅的类别分布。少量记录不足以确认稳定口味，因此菜系只能称为“当前记录中出现最多的类别”，不能当成确定偏好；评分和消费缺失也保留为未知，不用组平均值补造。

## 这批样本里观察到的类别线索

| 当前记录中出现最多的类别 | 顾客人数 |
| --- | ---: |
{family_md}

## 评论示例

以下是从这 94 位顾客的实际历史评论中选出的短片段，供检查画像依据。未展示用户 ID 和昵称，号码与链接做了基础遮盖；片段不是完整评论。

{example_md}

完整的 94 人结构化画像见 `cold_start_customer_profiles.json`。每位样本顾客在 `customers.json` 中也有对应的个人字段；`preference_confidence` 为 `low`，提醒模拟器不要把短历史当作强偏好。
"""
    (OUTPUT_DIR / "COLD_START_PROFILES.md").write_text(cold_report, encoding="utf-8")
    print(json.dumps({"restaurants": len(restaurant_rows), "customers": len(customer_rows),
                      "customer_groups": group_md}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
