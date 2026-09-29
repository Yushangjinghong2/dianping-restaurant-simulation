"""Embed and cluster Beijing customers with only 1–4 readable reviews."""

import collections
import gzip
import json
import re
import statistics
from pathlib import Path

import jieba
import numpy as np
import torch
from sklearn.cluster import MiniBatchKMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from threadpoolctl import threadpool_limits
from transformers import AutoModel, AutoTokenizer

from build_beijing_archetypes import family, number


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "datasets" / "Dianping_Beijing_Subset"
POOL_DIR = DATA_DIR / "sampled_portrait_pool"
OUT_DIR = POOL_DIR / "sparse_customer_clusters"
MODEL_ID = "BAAI/bge-small-zh-v1.5"
K = 94
SEED = 20260929
MAX_LENGTH = 256
BATCH_SIZE = 96

STOPWORDS = set("""我们 你们 他们 大家 自己 这里 那里 这个 那个 一个 有点 还是 真的 感觉 觉得 比较 非常 特别 不是 但是 而且 因为 所以 如果 以后 之前 之后 里面 外面 一般 可能 还是 可以 不错 好吃 好喝 还可以 没有 以及 还有 以及 什么 怎么 这样 那样 一下 一些 一种 时候 今天 昨天 周末 这家 那家 吃饭 吃了 点了 来了 去了 觉得 看到 知道 说是 就是 而已 吧 呢 啊 哦 哈哈 哈哈 哈哈 的 了 着 过 和 与 在 是 很 都 又 更 最 被 把 给 对 从 到 上 下 中 及 或 等 也 但 而 其 该 本次 本人 个人 推荐 评论 大众点评 店里 店家 服务 味道 环境 价格 人均 菜品 菜色 服务员 老板 餐厅 饭店 饭馆 用餐 消费 评价""".split())


def read_jsonl_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def safe_excerpt(text, limit=90):
    text = re.sub(r"(?:\+?\d[\d\s-]{7,}\d)", "[号码已隐去]", text)
    text = re.sub(r"https?://\S+|www\.\S+", "[链接已隐去]", text)
    text = re.sub(r"@[\w\u4e00-\u9fff-]+", "[用户信息已隐去]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def embed_documents(documents):
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModel.from_pretrained(MODEL_ID, use_safetensors=True).to("cuda").eval()
    vectors = np.empty((len(documents), model.config.hidden_size), dtype=np.float32)
    with torch.inference_mode():
        for start in range(0, len(documents), BATCH_SIZE):
            batch = tokenizer(
                documents[start:start + BATCH_SIZE],
                padding=True,
                truncation=True,
                max_length=MAX_LENGTH,
                return_tensors="pt",
            ).to("cuda")
            output = model(**batch).last_hidden_state
            mask = batch["attention_mask"].unsqueeze(-1).to(output.dtype)
            pooled = (output * mask).sum(1) / mask.sum(1).clamp(min=1)
            pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
            vectors[start:start + len(batch["input_ids"])] = pooled.cpu().numpy()
            if start and start % (BATCH_SIZE * 500) == 0:
                print(f"Embedded {start:,}/{len(documents):,}")
    return vectors


def main():
    restaurants = {
        str(row["restaurant_id"]): row
        for row in read_jsonl_gz(DATA_DIR / "restaurants.jsonl.gz")
    }
    by_user = collections.defaultdict(list)
    for review in read_jsonl_gz(DATA_DIR / "reviews.jsonl.gz"):
        content = str(review.get("content") or "").strip()
        if not content:
            continue
        cid = str(review.get("user_id") or "")
        rid = str(review.get("restaurant_id") or "")
        shop = restaurants.get(rid, {})
        by_user[cid].append({
            "content": content,
            "date": review.get("date"),
            "rating": number(review.get("overall_rating"), 1, 5),
            "flavor_rating": number(review.get("flavor_rating"), 1, 5),
            "environment_rating": number(review.get("environment_rating"), 1, 5),
            "service_rating": number(review.get("service_rating"), 1, 5),
            "cost": number(review.get("cost"), 0.01, 5000),
            "restaurant_id": rid,
            "restaurant_category": shop.get("category"),
            "family": family(shop.get("category")),
        })
    users = sorted(cid for cid, rows in by_user.items() if 1 <= len(rows) <= 4)
    documents = ["\n".join(row["content"][:500] for row in by_user[cid]) for cid in users]
    print(f"Low-activity customers: {len(users):,}; comment rows: {sum(len(by_user[cid]) for cid in users):,}")
    print(f"Loading {MODEL_ID} and generating embeddings on CUDA")
    vectors = embed_documents(documents)

    with threadpool_limits(limits=8):
        clusterer = MiniBatchKMeans(
            n_clusters=K,
            random_state=SEED,
            batch_size=2048,
            n_init=3,
            max_iter=120,
            reassignment_ratio=0.01,
        )
        labels = clusterer.fit_predict(vectors)

    def tokenize(text):
        return [word for word in jieba.lcut(text) if len(word.strip()) > 1 and word not in STOPWORDS]

    vectorizer = TfidfVectorizer(
        tokenizer=tokenize,
        token_pattern=None,
        lowercase=False,
        max_features=5000,
        min_df=30,
        max_df=0.65,
        sublinear_tf=True,
    )
    tfidf = vectorizer.fit_transform(documents)
    feature_names = vectorizer.get_feature_names_out()
    profiles = []
    assignments = []
    for cluster_id in range(K):
        indices = np.flatnonzero(labels == cluster_id)
        if not len(indices):
            continue
        counts = collections.Counter()
        raw_categories = collections.Counter()
        ratings, flavor_ratings, environment_ratings, service_ratings, costs, histories = [], [], [], [], [], []
        for idx in indices:
            rows = by_user[users[idx]]
            histories.append(len(rows))
            counts.update(row["family"] for row in rows)
            raw_categories.update(row["restaurant_category"] or "类别未知" for row in rows)
            ratings.extend(row["rating"] for row in rows if row["rating"] is not None)
            flavor_ratings.extend(row["flavor_rating"] for row in rows if row["flavor_rating"] is not None)
            environment_ratings.extend(row["environment_rating"] for row in rows if row["environment_rating"] is not None)
            service_ratings.extend(row["service_rating"] for row in rows if row["service_rating"] is not None)
            costs.extend(row["cost"] for row in rows if row["cost"] is not None)
        mean_tfidf = np.asarray(tfidf[indices].mean(axis=0)).ravel()
        top_term_ids = mean_tfidf.argsort()[-10:][::-1]
        top_terms = [str(feature_names[index]) for index in top_term_ids if mean_tfidf[index] > 0]
        family_rows = counts.most_common()
        dominant_family, dominant_count = family_rows[0]
        raw_category_rows = raw_categories.most_common(6)
        median_rating = float(statistics.median(ratings)) if ratings else None
        sentiment_label = (
            "整体偏正面" if median_rating is not None and median_rating >= 4
            else "评价偏中性/混合" if median_rating is not None and median_rating > 3
            else "整体偏负面" if median_rating is not None
            else "评分缺失较多"
        )
        # Cluster exemplars are the embedded customer histories closest to centroid.
        centroid = clusterer.cluster_centers_[cluster_id]
        similarities = vectors[indices] @ centroid / max(np.linalg.norm(centroid), 1e-12)
        exemplar_indices = indices[np.argsort(similarities)[-2:][::-1]]
        examples = []
        for idx in exemplar_indices:
            row = by_user[users[idx]][0]
            examples.append({
                "review_count": len(by_user[users[idx]]),
                "restaurant_category": row["restaurant_category"],
                "excerpt": safe_excerpt(row["content"]),
            })
        cluster_name = f"{sentiment_label}｜" + "、".join(top_terms[:3])
        profile = {
            "cluster_id": int(cluster_id),
            "cluster_name": cluster_name,
            "customers": int(len(indices)),
            "population_share": round(len(indices) / len(users), 6),
            "reviews": int(sum(histories)),
            "history_per_customer_median": float(statistics.median(histories)),
            "restaurant_family_review_counts": dict(family_rows),
            "top_raw_restaurant_categories": [
                {"category": category, "review_count": count}
                for category, count in raw_category_rows
            ],
            "dominant_family_share_in_reviews": round(dominant_count / sum(counts.values()), 4),
            "median_review_rating": round(median_rating, 2) if median_rating is not None else None,
            "median_flavor_rating": round(float(statistics.median(flavor_ratings)), 2) if flavor_ratings else None,
            "median_environment_rating": round(float(statistics.median(environment_ratings)), 2) if environment_ratings else None,
            "median_service_rating": round(float(statistics.median(service_ratings)), 2) if service_ratings else None,
            "median_review_spend_rmb": round(float(statistics.median(costs)), 2) if costs else None,
            "top_text_terms": top_terms,
            "portrait_summary": (
                f"这一簇占低评论顾客的 {len(indices) / len(users):.1%}，群体评论评分整体表现为{sentiment_label}；"
                f"已有评论中较常关联{dominant_family}餐厅，评论主题词包括：{'、'.join(top_terms[:5])}。"
                f"组内顾客历史中位数为 {statistics.median(histories):g} 条；这些是群体线索，不能据此断言每个人都稳定偏好该类餐厅。"
            ),
            "representative_review_excerpts": examples,
        }
        profiles.append(profile)
        for idx in indices:
            assignments.append({"user_id": users[idx], "cluster_id": int(cluster_id), "cluster_name": cluster_name,
                                "history_count": len(by_user[users[idx]])})

    profiles.sort(key=lambda row: row["customers"], reverse=True)
    profile_by_id = {row["cluster_id"]: row for row in profiles}
    assignments_by_user = {row["user_id"]: row for row in assignments}
    sampled_path = POOL_DIR / "customers.json"
    sampled_customers = json.loads(sampled_path.read_text(encoding="utf-8"))
    for customer in sampled_customers:
        if customer["user_id"] in assignments_by_user:
            assignment = assignments_by_user[customer["user_id"]]
            customer["embedding_cluster_id"] = assignment["cluster_id"]
            customer["embedding_cluster"] = assignment["cluster_name"]
            customer["embedding_cluster_population_share"] = profile_by_id[assignment["cluster_id"]]["population_share"]
            customer["portrait_confidence"] = "low individual evidence; cluster gives a population-level pattern"
    sampled_cold_counts = collections.Counter(
        assignments_by_user[row["user_id"]]["cluster_id"]
        for row in sampled_customers
        if row.get("profile_type") == "cold_start" and row["user_id"] in assignments_by_user
    )
    for profile in profiles:
        profile["sampled_agents_from_this_cluster"] = sampled_cold_counts[profile["cluster_id"]]

    sampled_path.write_text(json.dumps(sampled_customers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cold_profiles_path = POOL_DIR / "cold_start_customer_profiles.json"
    cold_profiles = json.loads(cold_profiles_path.read_text(encoding="utf-8"))
    for profile in cold_profiles:
        assignment = assignments_by_user[profile["user_id"]]
        cluster = profile_by_id[assignment["cluster_id"]]
        profile["embedding_cluster_id"] = cluster["cluster_id"]
        profile["embedding_cluster"] = cluster["cluster_name"]
        profile["cluster_population_share"] = cluster["population_share"]
        profile["portrait_confidence"] = "low individual evidence; cluster is a group-level pattern"
    cold_profiles_path.write_text(json.dumps(cold_profiles, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "cluster_profiles.json").write_text(json.dumps({
        "source": "Dianping_Beijing_Subset",
        "population_definition": "customers with 1–4 nonempty Beijing reviews",
        "customer_count": len(users),
        "comment_count": sum(len(by_user[cid]) for cid in users),
        "embedding_model": MODEL_ID,
        "embedding_pooling": "attention-mask mean pooling, L2 normalized",
        "max_tokens_per_customer_document": MAX_LENGTH,
        "cluster_algorithm": "MiniBatchKMeans on customer-review-text embeddings",
        "cluster_count": K,
        "random_seed": SEED,
        "clusters": profiles,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assignment_path = OUT_DIR / "customer_cluster_assignments.csv"
    with assignment_path.open("w", encoding="utf-8-sig", newline="") as handle:
        import csv
        writer = csv.DictWriter(handle, fieldnames=["user_id", "cluster_id", "cluster_name", "history_count"])
        writer.writeheader()
        writer.writerows(assignments)

    table_rows = []
    detail_rows = []
    for profile in profiles:
        families = sorted(profile["restaurant_family_review_counts"].items(), key=lambda pair: -pair[1])[:3]
        family_text = "、".join(f"{key}（{value}条）" for key, value in families)
        raw_category_text = "、".join(
            f"{row['category']}（{row['review_count']}条）"
            for row in profile["top_raw_restaurant_categories"][:4]
        )
        table_rows.append(
            f"| {profile['cluster_id']} | {profile['cluster_name']} | {profile['customers']:,} | "
            f"{profile['population_share']:.1%} | {profile['history_per_customer_median']:g} | "
            f"{profile['median_review_spend_rmb'] if profile['median_review_spend_rmb'] is not None else '未知'} | "
            f"{profile['median_review_rating'] if profile['median_review_rating'] is not None else '未知'} |"
        )
        excerpts = "\n".join(
            f"> {example['excerpt']}（关联类别：{example['restaurant_category'] or '未知'}）"
            for example in profile["representative_review_excerpts"]
        )
        detail_rows.append(
            f"### 簇 {profile['cluster_id']}：{profile['cluster_name']}\n\n"
            f"- 人数：{profile['customers']:,}（低评论顾客中的 {profile['population_share']:.1%}）；"
            f"抽出的 94 位冷启动 Agent 中有 {profile['sampled_agents_from_this_cluster']} 位。\n"
            f"- 评论关联菜系大类（按评论条数）：{family_text}；较常见原始餐厅类别：{raw_category_text}。\n"
            f"- 高频文本主题词：{'、'.join(profile['top_text_terms'])}。\n"
            f"- 可观察记录：每人评论数中位数 {profile['history_per_customer_median']:g}，"
            f"整体评分中位数 {profile['median_review_rating'] if profile['median_review_rating'] is not None else '未知'}，"
            f"评论消费中位数 {profile['median_review_spend_rmb'] if profile['median_review_spend_rmb'] is not None else '未知'} 元。\n"
            f"- 群体画像：{profile['portrait_summary']}\n"
            f"- 代表性短评片段（仅作簇的可读例子，不代表全簇）：\n{excerpts}\n"
        )
    report = f"""# 低评论顾客的 Embedding 聚类画像

## 范围与方法

对象为北京原始池中有 1–4 条非空评论的 **{len(users):,} 位顾客**，其评论共 **{sum(len(by_user[cid]) for cid in users):,} 条**。将每位顾客已有评论合并为文本，用中文向量模型 `{MODEL_ID}` 生成向量，再用 MiniBatch K-Means 分为 {K} 组。每位顾客只有 1–4 条评论，聚类提供的是“相似评论人群”的可解释群体画像，不会把低个体证据伪装成高置信个人偏好。

模型由北京智源人工智能研究院发布，模型卡标注 MIT 许可；聚类与画像均在本地数据上运行。[模型卡](https://huggingface.co/{MODEL_ID})

## 聚类概览

| 簇 | 群体画像标签（类别倾向与文本主题） | 顾客数 | 在低评论人群中的占比 | 每人评论数中位数 | 消费中位数（元） | 评分中位数 |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(table_rows)}

占比是群体占比，不表示单个顾客偏好置信度。若一个顾客有多种菜系经历，嵌入模型仍按整段短历史的整体语义将其归到一个簇，因此不能当成细粒度“只爱某菜系”的标签。

## 各簇具体画像与评论例子

评论片段经过基础号码/链接遮盖，并移除用户标识；短片段可能仍包含原评论中的其他可识别语境，使用时请把它们当作仅供内部检查的样例。

{chr(10).join(detail_rows)}

## 对当前 94 位 Agent 的应用

已将聚类编号和群体标签写回抽样池的 `customers.json`；每位冷启动 Agent 仍保留自己的历史条数、消费/评分与类别分布，另加其所在的文本相似簇。抽中的各簇人数见本报告上表。簇画像可以作为初始人群先验；后续模拟中应允许个体逐步偏离簇中心。

完整簇摘要见 `cluster_profiles.json`，所有低评论顾客的映射见 `customer_cluster_assignments.csv`。脚本：`../../../../scripts/cluster_sparse_customer_reviews.py`。
"""
    (OUT_DIR / "CLUSTER_PROFILES.md").write_text(report, encoding="utf-8")
    (OUT_DIR / "cluster_profiles.json").write_text(json.dumps({
        "source": "Dianping_Beijing_Subset",
        "population_definition": "customers with 1–4 nonempty Beijing reviews",
        "customer_count": len(users),
        "comment_count": sum(len(by_user[cid]) for cid in users),
        "embedding_model": MODEL_ID,
        "embedding_pooling": "attention-mask mean pooling, L2 normalized",
        "max_tokens_per_customer_document": MAX_LENGTH,
        "cluster_algorithm": "MiniBatchKMeans on customer-review-text embeddings",
        "cluster_count": K,
        "random_seed": SEED,
        "clusters": profiles,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"customers_clustered": len(users), "clusters": len(profiles),
                      "sampled_cold_start_agents": sum(sampled_cold_counts.values()),
                      "cluster_sizes": [row["customers"] for row in profiles]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
