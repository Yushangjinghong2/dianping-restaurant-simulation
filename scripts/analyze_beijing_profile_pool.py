"""Estimate feasible Beijing restaurant/customer portrait pool sizes."""

import collections
import gzip
import random
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "datasets" / "Dianping_Beijing_Subset" / "reviews.jsonl.gz"
REPORT = ROOT / "datasets" / "Dianping_Beijing_Subset" / "PROFILE_POOL_FEASIBILITY.md"
SEED = 20260929
REPEATS = 100
SCENARIOS = ((20, 100), (50, 300), (100, 500))


def quantiles(values):
    ordered = sorted(values)
    return ordered[9], ordered[49], ordered[89]


def main():
    restaurant_counts = collections.Counter()
    customer_counts = collections.Counter()
    pair_counts = collections.Counter()
    restaurant_customers = collections.defaultdict(set)
    contentful_reviews = 0

    with gzip.open(DATA, "rt", encoding="utf-8") as handle:
        for line in handle:
            review = __import__("json").loads(line)
            if not review.get("content"):
                continue
            contentful_reviews += 1
            restaurant_id = str(review["restaurant_id"])
            customer_id = str(review["user_id"])
            restaurant_counts[restaurant_id] += 1
            customer_counts[customer_id] += 1
            pair_counts[(restaurant_id, customer_id)] += 1
            restaurant_customers[restaurant_id].add(customer_id)

    restaurant_pool = sorted(
        restaurant_id for restaurant_id, count in restaurant_counts.items()
        if count >= 20
    )
    customer_pool = {
        customer_id for customer_id, count in customer_counts.items() if count >= 5
    }
    pair_reviews_in_eligible_pool = 0
    for (restaurant_id, customer_id), count in pair_counts.items():
        if restaurant_id in restaurant_pool and customer_id in customer_pool:
            pair_reviews_in_eligible_pool += count

    rng = random.Random(SEED)
    rows = []
    for restaurant_size, customer_size in SCENARIOS:
        candidate_counts = []
        sampled_review_counts = []
        covered_restaurant_counts = []
        customer_history_counts = []
        restaurant_history_medians = []
        for _ in range(REPEATS):
            selected_restaurants = set(rng.sample(restaurant_pool, restaurant_size))
            candidates = sorted(
                set().union(*(restaurant_customers[restaurant_id] & customer_pool
                              for restaurant_id in selected_restaurants))
            )
            candidate_counts.append(len(candidates))
            selected_customers = set(rng.sample(candidates, customer_size))
            matched_rows = sum(
                pair_counts[(restaurant_id, customer_id)]
                for restaurant_id in selected_restaurants
                for customer_id in selected_customers
            )
            sampled_review_counts.append(matched_rows)
            covered_restaurant_counts.append(sum(
                any((restaurant_id, customer_id) in pair_counts
                    for customer_id in selected_customers)
                for restaurant_id in selected_restaurants
            ))
            customer_history_counts.extend(
                customer_counts[customer_id] for customer_id in selected_customers
            )
            restaurant_history_medians.append(statistics.median(
                restaurant_counts[restaurant_id] for restaurant_id in selected_restaurants
            ))

        rows.append({
            "restaurant_size": restaurant_size,
            "customer_size": customer_size,
            "candidate_p10_median_p90": quantiles(candidate_counts),
            "matched_review_p10_median_p90": quantiles(sampled_review_counts),
            "covered_restaurant_p10_median_p90": quantiles(covered_restaurant_counts),
            "customer_history_median": statistics.median(customer_history_counts),
            "restaurant_history_median": statistics.median(restaurant_history_medians),
        })

    independent_expectations = []
    for scenario in rows:
        restaurant_size = scenario["restaurant_size"]
        customer_size = scenario["customer_size"]
        expected = (
            pair_reviews_in_eligible_pool
            * restaurant_size / len(restaurant_pool)
            * customer_size / len(customer_pool)
        )
        independent_expectations.append(expected)

    stats = {
        "nonempty_review_rows": contentful_reviews,
        "restaurants_with_nonempty_reviews": len(restaurant_counts),
        "customers_with_nonempty_reviews": len(customer_counts),
        "restaurants_with_at_least_20_nonempty_reviews": len(restaurant_pool),
        "customers_with_at_least_5_nonempty_reviews": len(customer_pool),
        "restaurants_with_more_than_200_nonempty_reviews": sum(
            count > 200 for count in restaurant_counts.values()
        ),
        "customers_with_more_than_20_nonempty_reviews": sum(
            count > 20 for count in customer_counts.values()
        ),
        "matched_rows_with_both_eligibility_thresholds": pair_reviews_in_eligible_pool,
        "scenarios": rows,
        "independent_sampling_expected_matched_reviews": independent_expectations,
    }

    table_rows = []
    for result in rows:
        c10, c50, c90 = result["candidate_p10_median_p90"]
        r10, r50, r90 = result["matched_review_p10_median_p90"]
        s10, s50, s90 = result["covered_restaurant_p10_median_p90"]
        table_rows.append(
            f"| {result['restaurant_size']} / {result['customer_size']} "
            f"| {c50:,}（{c10:,}–{c90:,}） | {r50:,}（{r10:,}–{r90:,}） "
            f"| {s50}/{result['restaurant_size']}（{s10}–{s90}） "
            f"| {result['restaurant_history_median']:.0f} | {result['customer_history_median']:.0f} |"
        )
    independent_rows = [
        f"| {result['restaurant_size']} / {result['customer_size']} | {expected:.1f} |"
        for result, expected in zip(rows, independent_expectations)
    ]

    report = f"""# 北京数据：餐厅与顾客画像池规模可行性

本报告只用北京子集中的**非空评论正文**估计画像信息量；空正文不计入画像历史。数据底库未改动，也没有生成或抽取固定实验画像名单。

## 可用候选规模

| 指标 | 数量 |
| --- | ---: |
| 有非空评论的餐厅 | {len(restaurant_counts):,} |
| 有非空评论的顾客 | {len(customer_counts):,} |
| 餐厅至少 20 条非空评论 | {len(restaurant_pool):,} |
| 顾客至少 5 条非空评论 | {len(customer_pool):,} |
| 餐厅超过 200 条非空评论 | {stats['restaurants_with_more_than_200_nonempty_reviews']:,} |
| 顾客超过 20 条非空评论 | {stats['customers_with_more_than_20_nonempty_reviews']:,} |

这说明对真实画像有帮助的是非空正文。此前按评论记录数筛出的 43 家“超过 200 条”餐厅包含空正文；按可用于画像的非空正文计算，实际为 **{stats['restaurants_with_more_than_200_nonempty_reviews']} 家**。

## 画像池规模试算

抽样方式：固定种子 {SEED}，每种规模重复 {REPEATS} 次。先从至少有 20 条非空评论的餐厅中均匀抽店，再从这些店的真实评论者中，抽取在整个北京数据里至少有 5 条非空评论的顾客。顾客画像使用其北京范围内完整历史，餐厅画像使用该店完整非空评论。表中区间为 100 次试算的第 10、50、90 百分位（中位数及范围）。

| 餐厅 / 顾客池 | 可选真实评论者（中位数；P10–P90） | 池内双方匹配评论数（中位数；P10–P90） | 有至少一条池内评论的餐厅（中位数；P10–P90） | 入池餐厅非空评论中位数 | 入池顾客北京历史中位数 |
| ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(table_rows)}

## 为什么不建议双方独立随机抽

若分别从全部合格餐厅和顾客中独立抽样，二者历史评论很少落在同一批实体上。按现有关系网络的期望值，池内双方匹配评论数约为：

| 餐厅 / 顾客池 | 独立抽样时预期匹配评论数 |
| ---: | ---: |
{chr(10).join(independent_rows)}

因此，若实验需要顾客和餐厅之间有真实历史关联，建议用“先选餐厅、再从真实评论者中选顾客”的关联抽样；顾客画像则汇总其全北京历史，而非只用池内评论。若只需要独立的顾客和餐厅画像而不要求历史上互相评论过，可以独立抽样，但不要把缺少历史关联误认为画像缺失。

## 建议

先用 **20 家餐厅 + 100 位顾客**做框架测试：每家店至少有 20 条可读评论，顾客至少有 5 条全市历史；试算中多数餐厅都能被抽到的顾客覆盖，个体完整历史中位数约 19 条。若需更多选择多样性，再扩到 50 / 300。不要用“餐厅 >200 且顾客 >20”作为硬门槛；该组合会过度缩小样本。抽最终名单时可再按菜系、价格和餐厅评论量分层，避免随机样本偏向某几个热门业态。

复算脚本：`../../scripts/analyze_beijing_profile_pool.py`。详细口径为非空评论正文；评论记录之间按顾客 ID 与餐厅 ID 关联。
"""
    REPORT.write_text(report, encoding="utf-8")
    print(f"Wrote {REPORT}")
    print("\n".join(table_rows))
    print("Independent expected matched reviews:", independent_expectations)


if __name__ == "__main__":
    main()
