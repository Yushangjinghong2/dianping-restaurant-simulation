"""Build richer customer profiles for sparse clusters and higher-evidence users."""

import collections
import csv
import datetime
import gzip
import json
import math
import statistics
from pathlib import Path

from build_beijing_archetypes import family, number


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "datasets" / "Dianping_Beijing_Subset"
POOL_DIR = DATA_DIR / "sampled_portrait_pool"
CLUSTER_DIR = POOL_DIR / "sparse_customer_clusters"
PROFILE_CSV = POOL_DIR / "customer_behavior_profiles.csv"
REPORT = POOL_DIR / "CUSTOMER_BEHAVIOR_MODEL.md"


def read_jsonl_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def quantile(values, p):
    values = sorted(values)
    if not values:
        return None
    return values[min(int(p * (len(values) - 1)), len(values) - 1)]


def median(values):
    return round(float(statistics.median(values)), 3) if values else None


def evidence_tier(count):
    if count < 5:
        return "少量记录：低置信"
    if count < 10:
        return "初步画像：仍偏低"
    if count < 20:
        return "中等证据"
    if count < 50:
        return "较强证据"
    return "高证据"


def rating_style(residual):
    if residual is None:
        return "评分不足"
    if residual <= -0.35:
        return "相对严格（比餐厅常见评分低）"
    if residual >= 0.35:
        return "相对宽容（比餐厅常见评分高）"
    return "接近餐厅常见评分"


def build_user_profile(user_id, rows, cost_cuts):
    count = len(rows)
    family_counts = collections.Counter(row["family"] for row in rows)
    category_counts = collections.Counter(row["category"] for row in rows if row["category"])
    family_share = {key: round(value / count, 4) for key, value in family_counts.items()}
    top_family, top_count = family_counts.most_common(1)[0]
    dominant_share = top_count / count
    if dominant_share >= 0.60:
        taste_pattern = f"明显偏向{top_family}（基于去过/评论过的餐厅）"
    elif dominant_share >= 0.40:
        taste_pattern = f"略偏向{top_family}，但接触菜系较广"
    else:
        taste_pattern = "菜系接触较分散，暂未见单一主导类型"
    costs = [row["cost"] for row in rows if row["cost"] is not None]
    ratings = [row["rating"] for row in rows if row["rating"] is not None]
    residuals = [row["rating_residual"] for row in rows if row["rating_residual"] is not None]
    flavors = [row["flavor"] for row in rows if row["flavor"] is not None]
    environments = [row["environment"] for row in rows if row["environment"] is not None]
    services = [row["service"] for row in rows if row["service"] is not None]
    q25, q75 = quantile(costs, 0.25), quantile(costs, 0.75)
    typical_spend = statistics.median(costs) if costs else None
    if typical_spend is None:
        spend_band = "消费记录不足"
    elif typical_spend <= cost_cuts[0]:
        spend_band = "偏低客单"
    elif typical_spend <= cost_cuts[1]:
        spend_band = "中等客单"
    else:
        spend_band = "偏高客单"
    iqr = (q75 - q25) if q25 is not None and q75 is not None else None
    if iqr is None:
        spend_variability = "消费波动未知"
    elif iqr <= 20:
        spend_variability = "记录中的消费较集中"
    elif iqr <= 60:
        spend_variability = "记录中的消费有一定弹性"
    else:
        spend_variability = "记录中的消费跨度较大"
    avg_rating = statistics.mean(ratings) if ratings else None
    avg_residual = statistics.mean(residuals) if residuals else None
    rating_bands = {
        "1–2分": sum(value <= 2 for value in ratings),
        "3分": sum(value == 3 for value in ratings),
        "4–5分": sum(value >= 4 for value in ratings),
    }
    aspect_means = {
        "口味字段均值_原始1到4等级": round(float(statistics.mean(flavors)), 3) if flavors else None,
        "环境字段均值_原始1到4等级": round(float(statistics.mean(environments)), 3) if environments else None,
        "服务字段均值_原始1到4等级": round(float(statistics.mean(services)), 3) if services else None,
    }
    weekdays = [row["weekday"] for row in rows if row["weekday"] is not None]
    weekend_share = round(sum(day >= 5 for day in weekdays) / len(weekdays), 3) if weekdays else None
    months = [row["month"] for row in rows if row["month"] is not None]
    top_categories = [
        {"category": category, "reviews": value}
        for category, value in category_counts.most_common(5)
    ]
    return {
        "user_id": user_id,
        "history_count": count,
        "evidence_tier": evidence_tier(count),
        "distinct_restaurants": len({row["restaurant_id"] for row in rows}),
        "taste_pattern": taste_pattern,
        "family_review_distribution": dict(family_counts),
        "family_review_share": family_share,
        "top_restaurant_categories": top_categories,
        "dominant_family_share": round(dominant_share, 4),
        "cuisine_diversity_count": len(family_counts),
        "spend_profile": {
            "typical_per_review_spend_median_rmb": round(float(typical_spend), 2) if typical_spend is not None else None,
            "per_review_spend_p25_rmb": round(float(q25), 2) if q25 is not None else None,
            "per_review_spend_p75_rmb": round(float(q75), 2) if q75 is not None else None,
            "spend_band": spend_band,
            "variability_iqr_rmb": round(float(iqr), 2) if iqr is not None else None,
            "spend_variability": spend_variability,
            "spend_record_coverage": round(len(costs) / count, 3),
        },
        "rating_profile": {
            "mean_overall_rating_1_to_5": round(float(avg_rating), 3) if avg_rating is not None else None,
            "overall_rating_distribution": rating_bands,
            "mean_difference_from_visited_restaurant_average": round(float(avg_residual), 3) if avg_residual is not None else None,
            "rating_style": rating_style(avg_residual),
            "rating_evidence_count": len(residuals),
        },
        "aspect_score_means_raw_scale_1_to_4": aspect_means,
        "reviewing_pattern": {
            "weekend_share_of_review_posting_dates": weekend_share,
            "first_review_date": min((row["date"] for row in rows if row["date"]), default=None),
            "last_review_date": max((row["date"] for row in rows if row["date"]), default=None),
            "month_variety_count": len(set(months)),
        },
        "caution": "历史行为和消费记录的描述，不等同于客观收入、稳定偏好或到店时间。评分宽严按其评分相对被评餐厅总体均值的差异估算。",
    }


def main():
    restaurant_metadata = {
        str(row["restaurant_id"]): row
        for row in read_jsonl_gz(DATA_DIR / "restaurants.jsonl.gz")
    }
    # First pass: establish each restaurant's observed average score.
    restaurant_rating_sum = collections.Counter()
    restaurant_rating_count = collections.Counter()
    for row in read_jsonl_gz(DATA_DIR / "reviews.jsonl.gz"):
        if not row.get("content"):
            continue
        rating = number(row.get("overall_rating"), 1, 5)
        if rating is not None:
            rid = str(row.get("restaurant_id"))
            restaurant_rating_sum[rid] += rating
            restaurant_rating_count[rid] += 1
    restaurant_means = {
        rid: restaurant_rating_sum[rid] / count
        for rid, count in restaurant_rating_count.items()
    }

    users = collections.defaultdict(list)
    for row in read_jsonl_gz(DATA_DIR / "reviews.jsonl.gz"):
        if not row.get("content"):
            continue
        uid = str(row.get("user_id"))
        rid = str(row.get("restaurant_id"))
        shop = restaurant_metadata.get(rid, {})
        rating = number(row.get("overall_rating"), 1, 5)
        date = row.get("date") or ""
        try:
            weekday = datetime.date.fromisoformat(date).weekday()
        except ValueError:
            weekday = None
        users[uid].append({
            "restaurant_id": rid,
            "family": family(shop.get("category")),
            "category": shop.get("category"),
            "cost": number(row.get("cost"), 0.01, 5000),
            "rating": rating,
            "rating_residual": rating - restaurant_means[rid] if rating is not None and rid in restaurant_means else None,
            "flavor": number(row.get("flavor_rating"), 1, 4),
            "environment": number(row.get("environment_rating"), 1, 4),
            "service": number(row.get("service_rating"), 1, 4),
            "date": date or None,
            "weekday": weekday,
            "month": date[:7] if len(date) >= 7 else None,
        })

    population_cost_cuts = [39.5, 52.5]
    high_customer_ids = {uid for uid, rows in users.items() if len(rows) >= 5}
    sample_path = POOL_DIR / "customers.json"
    sampled_customers = json.loads(sample_path.read_text(encoding="utf-8"))
    sampled_ids = {row["user_id"] for row in sampled_customers}
    sparse_sample_ids = {row["user_id"] for row in sampled_customers if row.get("profile_type") == "cold_start"}

    with (POOL_DIR / "customer_behavior_profiles.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "user_id", "history_count", "evidence_tier", "distinct_restaurants",
            "taste_pattern", "family_review_distribution", "family_review_share",
            "top_restaurant_categories", "dominant_family_share", "cuisine_diversity_count",
            "spend_profile", "rating_profile", "aspect_score_means_raw_scale_1_to_4",
            "reviewing_pattern", "caution",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for uid in sorted(high_customer_ids):
            profile = build_user_profile(uid, users[uid], population_cost_cuts)
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
                             for key, value in profile.items()})

    high_groups = collections.defaultdict(list)
    with PROFILE_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            shares = json.loads(row["family_review_share"])
            preferred_family = max(shares, key=shares.get) if shares else "口味/菜系未知"
            spend = json.loads(row["spend_profile"])
            rating = json.loads(row["rating_profile"])
            aspects = json.loads(row["aspect_score_means_raw_scale_1_to_4"])
            key = (preferred_family, spend["spend_band"], rating["rating_style"])
            high_groups[key].append({
                "history_count": int(row["history_count"]),
                "spend_median": spend["typical_per_review_spend_median_rmb"],
                "rating_mean": rating["mean_overall_rating_1_to_5"],
                "rating_residual": rating["mean_difference_from_visited_restaurant_average"],
                "family_shares": shares,
                "aspect_scores": aspects,
                "evidence_tier": row["evidence_tier"],
            })
    high_activity_archetypes = []
    for key, members in high_groups.items():
        all_families = set().union(*(member["family_shares"] for member in members))
        family_shares = {
            family_name: round(statistics.mean(member["family_shares"].get(family_name, 0) for member in members), 4)
            for family_name in all_families
        }
        aspect_summary = {}
        for aspect_name in ("口味字段均值_原始1到4等级", "环境字段均值_原始1到4等级", "服务字段均值_原始1到4等级"):
            aspect_values = [member["aspect_scores"][aspect_name] for member in members
                             if member["aspect_scores"][aspect_name] is not None]
            aspect_summary[aspect_name] = median(aspect_values)
        high_activity_archetypes.append({
            "archetype": " × ".join(key),
            "preferred_family": key[0],
            "spend_band": key[1],
            "rating_style": key[2],
            "customers": len(members),
            "population_share_of_5plus_review_customers": round(len(members) / len(high_customer_ids), 6),
            "total_reviews": sum(member["history_count"] for member in members),
            "history_count_median": median([member["history_count"] for member in members]),
            "median_personal_spend_rmb": median([member["spend_median"] for member in members if member["spend_median"] is not None]),
            "median_personal_rating_mean_1_to_5": median([member["rating_mean"] for member in members if member["rating_mean"] is not None]),
            "median_rating_difference_from_restaurant_average": median([member["rating_residual"] for member in members if member["rating_residual"] is not None]),
            "customer_balanced_family_shares": family_shares,
            "aspect_score_medians_raw_scale_1_to_4": aspect_summary,
            "evidence_tier_counts": dict(collections.Counter(member["evidence_tier"] for member in members)),
            "support": "typical" if len(members) >= 100 else "low_support",
        })
    high_activity_archetypes.sort(key=lambda row: (-row["customers"], row["archetype"]))

    cluster_assignment_path = CLUSTER_DIR / "customer_cluster_assignments.csv"
    cluster_by_user = {}
    with cluster_assignment_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            cluster_by_user[row["user_id"]] = int(row["cluster_id"])

    # Summarize the full sparse population by embedding cluster, using
    # customer-equal summaries alongside review-level evidence counters.
    cluster_stats = collections.defaultdict(lambda: {
        "customers": 0, "review_count": 0, "history_counts": [],
        "user_median_spends": [], "user_median_ratings": [], "user_rating_residuals": [],
        "rating_styles": collections.Counter(), "taste_patterns": collections.Counter(),
        "families": collections.Counter(), "raw_categories": collections.Counter(),
        "user_family_share_sums": collections.Counter(),
        "review_rating_bands": collections.Counter(), "review_costs": [],
        "review_residuals": [], "aspects": {"flavor": [], "environment": [], "service": []},
        "weekend_days": 0, "dated_reviews": 0,
    })
    sampled_profile_by_id = {}
    high_sample_profiles = {}
    high_tier_counts = collections.Counter()
    rating_styles_high = collections.Counter()
    for uid, rows in users.items():
        profile = build_user_profile(uid, rows, population_cost_cuts)
        if len(rows) >= 5:
            high_tier_counts[profile["evidence_tier"]] += 1
            rating_styles_high[profile["rating_profile"]["rating_style"]] += 1
            if uid in sampled_ids:
                high_sample_profiles[uid] = profile
            continue
        cluster_id = cluster_by_user.get(uid)
        if cluster_id is None:
            continue
        if uid in sparse_sample_ids:
            sampled_profile_by_id[uid] = profile
        stat = cluster_stats[cluster_id]
        stat["customers"] += 1
        stat["review_count"] += len(rows)
        stat["history_counts"].append(len(rows))
        stat["taste_patterns"][profile["taste_pattern"]] += 1
        stat["rating_styles"][profile["rating_profile"]["rating_style"]] += 1
        for family_name, share in profile["family_review_share"].items():
            stat["user_family_share_sums"][family_name] += share
        if profile["spend_profile"]["typical_per_review_spend_median_rmb"] is not None:
            stat["user_median_spends"].append(profile["spend_profile"]["typical_per_review_spend_median_rmb"])
        if profile["rating_profile"]["mean_overall_rating_1_to_5"] is not None:
            stat["user_median_ratings"].append(profile["rating_profile"]["mean_overall_rating_1_to_5"])
        residual = profile["rating_profile"]["mean_difference_from_visited_restaurant_average"]
        if residual is not None:
            stat["user_rating_residuals"].append(residual)
        for row in rows:
            stat["families"][row["family"]] += 1
            if row["category"]:
                stat["raw_categories"][row["category"]] += 1
            if row["rating"] is not None:
                stat["review_rating_bands"]["1–2分" if row["rating"] <= 2 else "3分" if row["rating"] == 3 else "4–5分"] += 1
                if row["rating_residual"] is not None:
                    stat["review_residuals"].append(row["rating_residual"])
            if row["cost"] is not None:
                stat["review_costs"].append(row["cost"])
            for key in stat["aspects"]:
                value = row[key]
                if value is not None:
                    stat["aspects"][key].append(value)
            if row["weekday"] is not None:
                stat["dated_reviews"] += 1
                stat["weekend_days"] += row["weekday"] >= 5

    # Update the 120 sampled agents: high-history users use individual portraits;
    # sparse users retain their own facts plus a group-level cluster prior.
    cluster_data = json.loads((CLUSTER_DIR / "cluster_profiles.json").read_text(encoding="utf-8"))
    cluster_profiles = {item["cluster_id"]: item for item in cluster_data["clusters"]}
    for cid, stat in cluster_stats.items():
        family_shares = {
            key: round(value / stat["customers"], 4)
            for key, value in stat["user_family_share_sums"].items()
        }
        dominant_family = max(family_shares, key=family_shares.get) if family_shares else None
        residual_median = median(stat["user_rating_residuals"])
        cluster_profiles[cid]["behavior_model"] = {
            "population_customers": stat["customers"],
            "population_reviews": stat["review_count"],
            "history_count_median": median(stat["history_counts"]),
            "customer_balanced_taste_share": family_shares,
            "most_common_family_by_customer_balanced_share": dominant_family,
            "top_raw_categories_by_review": [{"category": k, "reviews": v} for k, v in stat["raw_categories"].most_common(8)],
            "taste_patterns": dict(stat["taste_patterns"].most_common()),
            "spend_profile": {
                "customer_median_of_personal_medians_rmb": median(stat["user_median_spends"]),
                "personal_median_spend_p25_p75_rmb": [quantile(stat["user_median_spends"], 0.25), quantile(stat["user_median_spends"], 0.75)],
                "review_level_spend_p25_p50_p75_rmb": [quantile(stat["review_costs"], p) for p in (0.25, 0.5, 0.75)],
            },
            "rating_profile": {
                "overall_rating_style_by_customer": dict(stat["rating_styles"].most_common()),
                "customer_median_difference_from_restaurant_average": residual_median,
                "customer_balanced_rating_style": rating_style(residual_median),
                "review_rating_bands": dict(stat["review_rating_bands"]),
                "aspect_rating_medians_raw_scale_1_to_4": {key: median(values) for key, values in stat["aspects"].items()},
            },
            "reviewing_pattern": {
                "review_posting_weekend_share": round(stat["weekend_days"] / stat["dated_reviews"], 4) if stat["dated_reviews"] else None,
            },
        }

    summary_lines = []
    cluster_table = []
    for cid, stat in cluster_stats.items():
        cp = cluster_profiles[cid]
        behavior = cp["behavior_model"]
        top_families = sorted(behavior["customer_balanced_taste_share"].items(), key=lambda x: -x[1])[:3]
        family_desc = "、".join(f"{name} {share:.0%}" for name, share in top_families)
        spend = behavior["spend_profile"]["customer_median_of_personal_medians_rmb"]
        strictness = behavior["rating_profile"]["customer_balanced_rating_style"]
        cluster_table.append(
            f"| {cid} | {cp['cluster_name']} | {stat['customers']:,} | {family_desc} | "
            f"{spend if spend is not None else '未知'} | {strictness} |"
        )
        summary_lines.append(
            f"| {cid} | {stat['customers']:,} | {family_desc} | {spend if spend is not None else '未知'} | {strictness} |"
        )

    # Save updated cluster model and detailed high-evidence individual portraits.
    cluster_data["behavior_model_version"] = 1
    cluster_data["clusters"] = [cluster_profiles[cid] for cid in sorted(cluster_profiles)]
    (CLUSTER_DIR / "cluster_profiles.json").write_text(json.dumps(cluster_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (POOL_DIR / "high_activity_archetypes.json").write_text(
        json.dumps({
            "population_definition": "Beijing customers with at least 5 nonempty review texts",
            "customer_count": len(high_customer_ids),
            "grouping": "dominant reviewed cuisine family × personal median spend tier × relative rating style",
            "typical_group_minimum_customers": 100,
            "groups": high_activity_archetypes,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    sampled_profile_by_id.update(high_sample_profiles)
    for customer in sampled_customers:
        profile = sampled_profile_by_id.get(customer["user_id"])
        if profile:
            customer["detailed_behavior_profile"] = profile
            customer["portrait_evidence_tier"] = profile["evidence_tier"]
    sample_path.write_text(json.dumps(sampled_customers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cold_profile_path = POOL_DIR / "cold_start_customer_profiles.json"
    cold_profiles = json.loads(cold_profile_path.read_text(encoding="utf-8"))
    for customer in cold_profiles:
        profile = sampled_profile_by_id.get(customer["user_id"])
        if profile:
            customer["detailed_behavior_profile"] = profile
            cluster_id = customer.get("embedding_cluster_id")
            if cluster_id in cluster_profiles:
                customer["cluster_behavior_prior"] = cluster_profiles[cluster_id].get("behavior_model")
    cold_profile_path.write_text(json.dumps(cold_profiles, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    typical_high_groups = [group for group in high_activity_archetypes if group["support"] == "typical"]
    high_group_table = "\n".join(
        f"| {group['archetype']} | {group['customers']:,} | {group['population_share_of_5plus_review_customers']:.1%} | "
        f"{group['history_count_median']:g} | {group['median_personal_spend_rmb'] if group['median_personal_spend_rmb'] is not None else '未知'} | "
        f"{group['median_personal_rating_mean_1_to_5'] if group['median_personal_rating_mean_1_to_5'] is not None else '未知'} |"
        for group in typical_high_groups[:24]
    )
    report = f"""# 顾客多维行为画像建模

## 建模对象与输出

在现有 20 餐厅、120 顾客 Agent 抽样上补充多维画像，同时对北京池中所有评论至少 5 条的 28,629 位顾客计算个人画像。1–4 条评论的 102,037 位顾客沿用 94-means 文本簇，并在每簇上补充消费、评分、菜系与评论时间特征。高评论数顾客画像单独保留到 CSV，供后续挑选或加权抽样。

## 画像维度

- 口味/菜系：按顾客评论过的餐厅类别汇总菜系大类分布、最常见类型和集中程度。这是到访/评论行为的代理，不直接等于生理口味或忌口。
- 日常餐饮消费：描述已记录评论对应消费额的中位数、四分位范围、低/中/高消费档及记录覆盖率。它不是个人收入或完整日常消费。
- 评分宽严：先计算顾客给分，再与其所评餐厅的全体评论平均分比较。低于店均较多标为“相对严格”，高于较多标为“相对宽容”，接近则标为“接近常见评分”。这是相对宽严，不是绝对性格。
- 评分习惯：保留 1–2、3、4–5 分的评论数量，以及平均整体评分。
- 口味、环境、服务：报告数据原字段的均值/中位数，明确为原始 1–4 等级，不称为星级。
- 评论规律：使用评论发布日期的周末占比、最早/最晚日期和月份覆盖。日期是评论发布日期，不保证等于实际就餐时间。
- 证据强度：评论条数 5–9、10–19、20–49、50+ 分别标为初步、中等、较强、高证据；1–4 条仍是低置信，并使用聚类群体先验补充。

## 高评论顾客的画像证据量

北京池中可建立个人行为画像的顾客共 {len(high_customer_ids):,} 位。评论条数分档：

| 画像证据档 | 顾客数 |
| --- | ---: |
{chr(10).join(f'| {key} | {value:,} |' for key, value in high_tier_counts.most_common())}

在个人评分宽严估计中，相对严格 {rating_styles_high['相对严格（比餐厅常见评分低）']:,} 人、接近餐厅常见评分 {rating_styles_high['接近餐厅常见评分']:,} 人、相对宽容 {rating_styles_high['相对宽容（比餐厅常见评分高）']:,} 人；这只是按可用评论条数计算的用户数量，未对低证据个人作强结论。

## 高证据顾客的典型群体

对 5 条及以上评论的顾客，再按“常评论菜系 × 消费档 × 相对评分宽严”分组。以下展示人数至少 100 的常见画像组；它们的人数自然不均衡，不对各类做等额抽样。

| 高证据顾客画像 | 顾客数 | 占高证据顾客比例 | 个人评论数中位数 | 消费中位数（元） | 个人平均评分中位数 |
| --- | ---: | ---: | ---: | ---: | ---: |
{high_group_table}

## 94 个低评论人群簇的行为补充

以下口味比例按簇内每位顾客的菜系分布等权汇总；消费和评分宽严也先形成个人特征再汇总。每位顾客只有 1–4 条评论，因此应把它理解为“这群人的总体先验”，不是对簇内每个人都成立的标签。

| 簇 | 文本簇主题 | 顾客数 | 主要菜系行为占比 | 个人消费中位数的组中位数（元） | 群体评分宽严 |
| ---: | --- | ---: | --- | ---: | --- |
{chr(10).join(cluster_table)}

## 可复用文件

- `customer_behavior_profiles.csv`：所有 28,629 位至少 5 条评论顾客的个人多维画像。消费、评分和分布列以 JSON 格式保存在单元格中。
- `high_activity_archetypes.json`：上述高证据顾客群体画像的数量比例与详细多维汇总。
- `customers.json`：120 位抽样 Agent 的画像已更新；评论较多的用户使用个人画像，低评论用户额外附上所在簇的群体画像先验。
- `cold_start_customer_profiles.json`：94 位低评论 Agent 的详细个人弱线索和群体先验。
- `sparse_customer_clusters/cluster_profiles.json`：94 簇多维群体画像机器可读数据。
- `sparse_customer_clusters/CLUSTER_PROFILES.md`：文本簇画像及匿名评论样例。

建模边界：评论文字和评分只反映用户选择留下的餐饮反馈；样本偏差、评论行为差异和历史时间跨度会影响画像。评论多提高画像证据量，不等于人格判断更准确。
"""
    REPORT.write_text(report, encoding="utf-8")

    marker = "<!-- customer-behavior-model -->"
    cluster_report_path = CLUSTER_DIR / "CLUSTER_PROFILES.md"
    cluster_report = cluster_report_path.read_text(encoding="utf-8")
    appendix = f"""\n\n{marker}\n## 94 个文本簇的行为画像补充\n\n菜系比例按簇内顾客等权汇总。消费、评分宽严来自个人历史；低评论人群仍只作群体级先验。\n\n| 簇 | 人数 | 主要菜系行为占比 | 消费中位数的组中位数（元） | 评分宽严 |\n| ---: | ---: | --- | ---: | --- |\n{chr(10).join(summary_lines)}\n\n更细的口味分布、消费波动、评分分布和证据档说明见 `../CUSTOMER_BEHAVIOR_MODEL.md`。\n"""
    if marker in cluster_report:
        cluster_report = cluster_report.split(marker)[0].rstrip()
    cluster_report_path.write_text(cluster_report + appendix, encoding="utf-8")
    print(json.dumps({"high_history_profiles": len(high_customer_ids),
                      "sampled_high_history_profiles": len(high_sample_profiles),
                      "sampled_sparse_profiles": len(sparse_sample_ids),
                      "clusters_enriched": len(cluster_profiles),
                      "csv": str(PROFILE_CSV), "report": str(REPORT)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
