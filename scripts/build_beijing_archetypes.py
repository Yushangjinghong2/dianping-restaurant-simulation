"""Build aggregate restaurant and customer archetypes from Beijing Dianping."""

import collections
import gzip
import json
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "datasets" / "Dianping_Beijing_Subset"
RESTAURANTS_FILE = DATA_DIR / "restaurants.jsonl.gz"
REVIEWS_FILE = DATA_DIR / "reviews.jsonl.gz"
MIN_RESTAURANT_REVIEWS = 5
MIN_CUSTOMER_REVIEWS = 5
MIN_TYPICAL_RESTAURANTS = 30
MIN_TYPICAL_CUSTOMERS = 100


def read_jsonl_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def family(category):
    """Map raw restaurant category labels into broad interpretable families."""
    value = str(category or "").strip()
    groups = (
        ("火锅/麻辣", ("火锅", "香锅", "麻辣", "串串")),
        ("烧烤/烤制", ("烧烤", "烤鸭", "烤鱼", "烤肉", "铁板烧")),
        ("东亚/东南亚料理", ("韩国", "日本", "寿司", "泰国", "越南", "东南亚", "印度")),
        ("西餐/披萨/牛排", ("西式简餐", "西餐", "披萨", "比萨", "牛排", "意大利", "法国", "俄罗斯", "中东")),
        ("快餐/小吃/面食", ("快餐", "小吃", "粉面", "面馆", "包子", "粥店", "饺子", "馄饨", "煎饼", "米线", "米粉")),
        ("自助/海鲜", ("自助", "海鲜")),
    )
    for family_name, keywords in groups:
        if any(keyword in value for keyword in keywords):
            return family_name
    if not value or value.lower() in {"unknown", "null", "none"} or value == "其他/未知" or value == "其他":
        return "其他/未知"
    return "中式地方菜/家常菜"


def number(value, minimum=None, maximum=None):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if minimum is not None and result < minimum:
        return None
    if maximum is not None and result > maximum:
        return None
    return result


def quantile(values, proportion):
    ordered = sorted(values)
    if not ordered:
        return None
    return ordered[int(proportion * (len(ordered) - 1))]


def price_tier(value, cuts):
    if value is None:
        return "消费未知"
    if value <= cuts[0]:
        return "低价"
    if value <= cuts[1]:
        return "中价"
    return "高价"


def median(values):
    return round(statistics.median(values), 2) if values else None


def mean(values):
    return round(statistics.mean(values), 3) if values else None


def share(numerator, denominator):
    return round(numerator / denominator, 3) if denominator else None


def segment_name(key):
    return " × ".join(key)


def main():
    restaurant_data = {
        str(row["restaurant_id"]): row for row in read_jsonl_gz(RESTAURANTS_FILE)
    }
    restaurant_reviews = collections.defaultdict(list)
    customer_reviews = collections.defaultdict(list)
    customer_family_counts = collections.defaultdict(collections.Counter)
    customer_category_counts = collections.defaultdict(collections.Counter)

    nonempty_reviews = 0
    for review in read_jsonl_gz(REVIEWS_FILE):
        if not review.get("content"):
            continue
        restaurant_id = str(review["restaurant_id"])
        customer_id = str(review["user_id"])
        restaurant = restaurant_data.get(restaurant_id, {})
        raw_category = restaurant.get("category") or "其他/未知"
        category_family = family(raw_category)
        rating = number(review.get("overall_rating"), 1, 5)
        cost = number(review.get("cost"), 0.01, 5000)
        restaurant_reviews[restaurant_id].append(rating)
        customer_reviews[customer_id].append({
            "rating": rating,
            "cost": cost,
            "family": category_family,
            "raw_category": raw_category,
        })
        customer_family_counts[customer_id][category_family] += 1
        customer_category_counts[customer_id][raw_category] += 1
        nonempty_reviews += 1

    # Restaurant price tiers are empirical tertiles among restaurants with
    # enough readable comments to contribute a per-shop profile.
    restaurant_costs = {
        restaurant_id: number(restaurant_data[restaurant_id].get("average_cost"), 0.01, 5000)
        for restaurant_id, reviews in restaurant_reviews.items()
        if len(reviews) >= MIN_RESTAURANT_REVIEWS
    }
    valid_restaurant_costs = [value for value in restaurant_costs.values() if value is not None]
    restaurant_price_cuts = [quantile(valid_restaurant_costs, p) for p in (1 / 3, 2 / 3)]

    restaurant_groups = collections.defaultdict(list)
    low_evidence_restaurants = 0
    for restaurant_id, ratings in restaurant_reviews.items():
        if len(ratings) < MIN_RESTAURANT_REVIEWS:
            low_evidence_restaurants += 1
            continue
        record = restaurant_data[restaurant_id]
        category_family = family(record.get("category"))
        cost = restaurant_costs.get(restaurant_id)
        key = (category_family, price_tier(cost, restaurant_price_cuts))
        valid_ratings = [value for value in ratings if value is not None]
        average_rating = mean(valid_ratings)
        shop_profile = {
            "review_count": len(ratings),
            "cost": cost,
            "average_rating": average_rating,
            "negative_share": share(sum(value <= 2 for value in valid_ratings), len(valid_ratings)),
            "positive_share": share(sum(value >= 4 for value in valid_ratings), len(valid_ratings)),
            "raw_category": record.get("category") or "其他/未知",
        }
        restaurant_groups[key].append(shop_profile)

    restaurant_archetypes = []
    for key, members in restaurant_groups.items():
        costs = [member["cost"] for member in members if member["cost"] is not None]
        shop_ratings = [member["average_rating"] for member in members if member["average_rating"] is not None]
        raw_categories = collections.Counter(member["raw_category"] for member in members)
        total_reviews = sum(member["review_count"] for member in members)
        restaurant_archetypes.append({
            "archetype": segment_name(key),
            "category_family": key[0],
            "price_tier": key[1],
            "restaurants": len(members),
            "total_nonempty_reviews": total_reviews,
            "reviews_per_restaurant_median": median([member["review_count"] for member in members]),
            "average_cost_median_rmb": median(costs),
            "average_cost_p10_p90_rmb": [quantile(costs, 0.10), quantile(costs, 0.90)] if costs else None,
            "shop_mean_rating_median_1_to_5": median(shop_ratings),
            "shop_mean_rating_p25_p75_1_to_5": [quantile(shop_ratings, 0.25), quantile(shop_ratings, 0.75)] if shop_ratings else None,
            "negative_share_median_across_shops": median([m["negative_share"] for m in members if m["negative_share"] is not None]),
            "positive_share_median_across_shops": median([m["positive_share"] for m in members if m["positive_share"] is not None]),
            "top_raw_categories_by_restaurant_count": [
                {"category": category, "restaurants": count}
                for category, count in raw_categories.most_common(5)
            ],
            "support": "typical" if len(members) >= MIN_TYPICAL_RESTAURANTS else "low_support",
        })
    restaurant_archetypes.sort(key=lambda item: (-item["restaurants"], item["archetype"]))

    # Customer spend is the median positive per-review spend for each person;
    # activity is reported as confidence evidence, not used to invent identity.
    user_spends = {}
    customer_preference_family = {}
    customer_preference_strength = {}
    customer_preferred_raw = {}
    for customer_id, reviews in customer_reviews.items():
        if len(reviews) < MIN_CUSTOMER_REVIEWS:
            continue
        spends = [review["cost"] for review in reviews if review["cost"] is not None]
        if spends:
            user_spends[customer_id] = median(spends)
        family_counts = customer_family_counts[customer_id]
        top_family, top_count = family_counts.most_common(1)[0]
        top_share = top_count / len(reviews)
        customer_preference_family[customer_id] = (
            top_family if top_share >= 0.40 else "口味/菜系分散"
        )
        customer_preference_strength[customer_id] = top_share
        customer_preferred_raw[customer_id] = customer_category_counts[customer_id].most_common(1)[0][0]

    spend_cuts = [quantile(list(user_spends.values()), p) for p in (1 / 3, 2 / 3)]
    customer_groups = collections.defaultdict(list)
    low_history_users = 0
    low_history_reviews = 0
    for customer_id, reviews in customer_reviews.items():
        if len(reviews) < MIN_CUSTOMER_REVIEWS:
            low_history_users += 1
            low_history_reviews += len(reviews)
            continue
        spend = user_spends.get(customer_id)
        key = (
            customer_preference_family[customer_id],
            price_tier(spend, spend_cuts),
        )
        valid_ratings = [review["rating"] for review in reviews if review["rating"] is not None]
        customer_groups[key].append({
            "review_count": len(reviews),
            "spend": spend,
            "mean_rating": mean(valid_ratings),
            "negative_share": share(sum(value <= 2 for value in valid_ratings), len(valid_ratings)),
            "positive_share": share(sum(value >= 4 for value in valid_ratings), len(valid_ratings)),
            "preference_strength": customer_preference_strength[customer_id],
            "family_count": len(customer_family_counts[customer_id]),
            "raw_preferred_category": customer_preferred_raw[customer_id],
        })

    customer_archetypes = []
    for key, members in customer_groups.items():
        spends = [member["spend"] for member in members if member["spend"] is not None]
        ratings = [member["mean_rating"] for member in members if member["mean_rating"] is not None]
        raw_categories = collections.Counter(member["raw_preferred_category"] for member in members)
        history_bands = collections.Counter()
        for member in members:
            count = member["review_count"]
            history_bands["5–9"] += 5 <= count <= 9
            history_bands["10–19"] += 10 <= count <= 19
            history_bands["20+"] += count >= 20
        customer_archetypes.append({
            "archetype": segment_name(key),
            "preferred_family": key[0],
            "spend_tier": key[1],
            "customers": len(members),
            "total_nonempty_reviews": sum(member["review_count"] for member in members),
            "history_per_customer_median": median([member["review_count"] for member in members]),
            "history_bands": {
                band: {"customers": count, "share": share(count, len(members))}
                for band, count in history_bands.items()
            },
            "median_personal_spend_rmb": median(spends),
            "personal_spend_p10_p90_rmb": [quantile(spends, 0.10), quantile(spends, 0.90)] if spends else None,
            "personal_mean_rating_median_1_to_5": median(ratings),
            "negative_share_median_across_customers": median([m["negative_share"] for m in members if m["negative_share"] is not None]),
            "positive_share_median_across_customers": median([m["positive_share"] for m in members if m["positive_share"] is not None]),
            "dominant_family_share_median": median([member["preference_strength"] for member in members]),
            "category_families_per_customer_median": median([member["family_count"] for member in members]),
            "top_raw_preferred_categories": [
                {"category": category, "customers": count}
                for category, count in raw_categories.most_common(5)
            ],
            "support": "typical" if len(members) >= MIN_TYPICAL_CUSTOMERS else "low_support",
        })
    customer_archetypes.sort(key=lambda item: (-item["customers"], item["archetype"]))

    customer_low_history_profile = {
        "archetype": "冷启动/历史稀疏顾客",
        "customers": low_history_users,
        "total_nonempty_reviews": low_history_reviews,
        "history_per_customer_median": median([
            len(reviews) for reviews in customer_reviews.values()
            if len(reviews) < MIN_CUSTOMER_REVIEWS
        ]),
        "profile_use": "Do not assign an individual stable cuisine or style from fewer than five comments; use only as a low-confidence/cold-start cohort.",
    }
    sparse_restaurants = {
        "restaurants_with_1_to_4_nonempty_reviews": low_evidence_restaurants,
    }

    customer_price_coverage = len(user_spends)
    restaurant_profile = {
        "source": "Dianping_Beijing_Subset",
        "method": {
            "nonempty_reviews_only": True,
            "restaurant_min_reviews": MIN_RESTAURANT_REVIEWS,
            "customer_min_reviews": MIN_CUSTOMER_REVIEWS,
            "restaurant_price_tertiles_rmb": restaurant_price_cuts,
            "customer_median_spend_tertiles_rmb": spend_cuts,
            "typical_group_minimum_restaurants": MIN_TYPICAL_RESTAURANTS,
            "category_family_mapping": "manual keyword mapping; see ARCHETYPE_PROFILES.md",
            "group_aggregation": "restaurant-level summaries use each shop equally; customer-level summaries use each customer equally",
        },
        "counts": {
            "restaurants_with_nonempty_reviews": len(restaurant_reviews),
            "restaurants_profiled_with_at_least_5_reviews": sum(len(v) >= MIN_RESTAURANT_REVIEWS for v in restaurant_reviews.values()),
            "restaurants_in_low_evidence_pool": low_evidence_restaurants,
            "customers_with_nonempty_reviews": len(customer_reviews),
            "customers_profiled_with_at_least_5_reviews": sum(len(v) >= MIN_CUSTOMER_REVIEWS for v in customer_reviews.values()),
            "customers_in_cold_start_pool": low_history_users,
            "customers_with_spend_evidence": customer_price_coverage,
            "nonempty_review_rows": nonempty_reviews,
        },
        "price_tier_definitions": {
            "restaurant_average_cost_rmb": {"low_max": restaurant_price_cuts[0], "mid_max": restaurant_price_cuts[1], "high_min_exclusive": restaurant_price_cuts[1]},
            "customer_median_review_cost_rmb": {"low_max": spend_cuts[0], "mid_max": spend_cuts[1], "high_min_exclusive": spend_cuts[1]},
        },
        "typical_groups": [item for item in restaurant_archetypes if item["support"] == "typical"],
        "low_support_groups": [item for item in restaurant_archetypes if item["support"] != "typical"],
        "low_evidence_pool": sparse_restaurants,
    }
    customer_profile = {
        "source": "Dianping_Beijing_Subset",
        "method": {
            "nonempty_reviews_only": True,
            "customer_min_reviews": MIN_CUSTOMER_REVIEWS,
            "customer_median_spend_tertiles_rmb": spend_cuts,
            "typical_group_minimum_customers": MIN_TYPICAL_CUSTOMERS,
            "dominant_family_minimum_share": 0.40,
            "category_family_mapping": "inherited from reviewed restaurant category; see ARCHETYPE_PROFILES.md",
            "no_demographic_inference": True,
        },
        "counts": {
            "customers_with_nonempty_reviews": len(customer_reviews),
            "customers_profiled_with_at_least_5_reviews": sum(len(v) >= MIN_CUSTOMER_REVIEWS for v in customer_reviews.values()),
            "customers_in_cold_start_pool": low_history_users,
            "customers_with_spend_evidence": customer_price_coverage,
            "nonempty_review_rows": nonempty_reviews,
        },
        "typical_groups": [item for item in customer_archetypes if item["support"] == "typical"],
        "low_support_groups": [item for item in customer_archetypes if item["support"] != "typical"],
        "cold_start_group": customer_low_history_profile,
    }

    (DATA_DIR / "restaurant_archetypes.json").write_text(
        json.dumps(restaurant_profile, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (DATA_DIR / "customer_archetypes.json").write_text(
        json.dumps(customer_profile, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    restaurant_table = "\n".join(
        f"| {item['archetype']} | {item['restaurants']:,} | {item['total_nonempty_reviews']:,} | "
        f"{item['average_cost_median_rmb'] or '—'} | {item['shop_mean_rating_median_1_to_5'] or '—'} | "
        f"{(item['negative_share_median_across_shops'] or 0) * 100:.1f}% |"
        for item in restaurant_profile["typical_groups"]
    ) or "| 暂无 | 0 | 0 | — | — | — |"
    customer_table = "\n".join(
        f"| {item['archetype']} | {item['customers']:,} | {item['total_nonempty_reviews']:,} | "
        f"{item['history_per_customer_median']} | {item['median_personal_spend_rmb'] or '—'} | "
        f"{item['personal_mean_rating_median_1_to_5'] or '—'} |"
        for item in customer_profile["typical_groups"]
    ) or "| 暂无 | 0 | 0 | — | — | — |"

    report = f"""# 北京数据：同类餐厅与顾客典型画像

数据来源：北京筛选子集。只用**非空评论正文**及关联的结构化餐厅/评论字段；本报告生成的是群体画像，不是对某一家真实餐厅或某一位真实顾客的断言。

## 分组口径

- 餐厅：至少 5 条非空评论后进入画像池；按餐饮大类 × 人均消费三分位分组。消费界线取该画像池有效商户人均消费的三分位点：低价 ≤ RMB {restaurant_price_cuts[0]}，中价 ≤ RMB {restaurant_price_cuts[1]}，高价高于 RMB {restaurant_price_cuts[1]}；消费缺失单列。
- 顾客：至少 5 条非空评论后建立个人行为特征；按最常评论的大类偏好 × 个人评论消费中位数分组。若最常见大类占个人历史不足 40%，归为“口味/菜系分散”。顾客消费档的三分位界线为 RMB {spend_cuts[0]} 和 RMB {spend_cuts[1]}；消费缺失单列。
- 典型餐厅组至少包含 {MIN_TYPICAL_RESTAURANTS} 家餐厅，典型顾客组至少包含 {MIN_TYPICAL_CUSTOMERS} 人。未达规模的小组仍保存在 JSON 中并标为低支持，不作为稳定典型组。
- 价格和评分摘要按商户或顾客等权汇总，不让单个高评论实体支配整个同类画像。评分使用 1–5 星；负面占比定义为 1–2 星。

餐饮大类按餐厅原始类别用规则映射：火锅/麻辣、烧烤/烤制、东亚/东南亚料理、西餐/披萨/牛排、快餐/小吃/面食、自助/海鲜；其余归为中式地方菜/家常菜，未知类别单列。这是可检查、可修改的分析口径，不是数据源原生标签。

## 餐厅典型画像

有效餐厅评论 {sum(len(v) >= MIN_RESTAURANT_REVIEWS for v in restaurant_reviews.values()):,} 家；其中 {len(restaurant_profile['typical_groups'])} 个典型组，另有 {len(restaurant_profile['low_support_groups'])} 个低支持小组。少于 5 条非空评论的餐厅共 {low_evidence_restaurants:,} 家，未强行推断单店画像。

| 同类餐厅画像 | 餐厅数 | 非空评论数 | 人均消费中位数（元） | 单店平均评分中位数（星） | 单店差评占比中位数 |
| --- | ---: | ---: | ---: | ---: | ---: |
{restaurant_table}

评分和差评比例先在单店内计算，再跨店等权汇总；这是为了描述“典型同类餐厅”，避免评论最多的店把组画像变成自身画像。

## 顾客典型画像

有非空评论的顾客 {len(customer_reviews):,} 人；至少有 5 条非空评论、可建立个人偏好特征的顾客 {sum(len(v) >= MIN_CUSTOMER_REVIEWS for v in customer_reviews.values()):,} 人，消费字段可用者 {customer_price_coverage:,} 人。共有 {len(customer_profile['typical_groups'])} 个典型顾客组，另有 {len(customer_profile['low_support_groups'])} 个低支持组。

| 同类顾客画像 | 顾客数 | 非空评论数 | 个人历史评论中位数 | 个人消费中位数（元） | 个人平均评分中位数（星） |
| --- | ---: | ---: | ---: | ---: | ---: |
{customer_table}

另有 **{low_history_users:,} 位冷启动/低历史顾客**（每人仅 1–4 条非空评论，共 {low_history_reviews:,} 条）；他们作为一类保留，但不从稀少记录给每个人贴稳定的菜系偏好标签。

## 怎么用于模拟

可以把每个典型组当成一个“虚拟餐厅/虚拟顾客”的初始画像来源，再按组内价格、评分、评论历史分布抽取具体参数。若模拟目标是多家具体门店，应从典型餐厅组中抽出若干代表组；若目标是顾客多样性，可按顾客组比例抽样，并为冷启动顾客保留较宽泛的先验。群体画像是现实分布的压缩表达，不代表组内每个人/每家店都相同。

数据不含可靠的人口属性，也没有直接的“不吃辣”等个人标签；不能从这些分组推断年龄、性别、收入或具体口味强度。分组汇总文件：`restaurant_archetypes.json`、`customer_archetypes.json`。复算脚本：`../../scripts/build_beijing_archetypes.py`。
"""
    (DATA_DIR / "ARCHETYPE_PROFILES.md").write_text(report, encoding="utf-8")
    print(json.dumps({
        "restaurant_typical_groups": len(restaurant_profile["typical_groups"]),
        "restaurant_low_support_groups": len(restaurant_profile["low_support_groups"]),
        "customer_typical_groups": len(customer_profile["typical_groups"]),
        "customer_low_support_groups": len(customer_profile["low_support_groups"]),
        "restaurant_price_cuts": restaurant_price_cuts,
        "customer_price_cuts": spend_cuts,
        "restaurant_candidates": restaurant_profile["counts"]["restaurants_profiled_with_at_least_5_reviews"],
        "customer_candidates": customer_profile["counts"]["customers_profiled_with_at_least_5_reviews"],
        "cold_start_customers": low_history_users,
    }, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
