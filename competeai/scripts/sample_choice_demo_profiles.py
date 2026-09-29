"""Sample anonymized restaurant and customer baselines from merged Dianping data."""

import argparse
import gzip
import json
import random
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
DATA_DIR = WORKSPACE_ROOT / "datasets" / "Dianping_Three_Source_Merged"
OUTPUT_PATH = PROJECT_ROOT / "competeai" / "examples" / "choice_demo_profiles.json"
OWNER_NAMES = ["Qin", "Lin", "Kai", "Mei"]
CUSTOMER_NAMES = [
    "Alice", "Bob", "Charlie", "Diana", "Ethan",
    "Fiona", "George", "Hannah", "Ian", "Judy",
]
DEFAULT_SEED = 2026


def positive_amount(value):
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount if 0 < amount <= 2000 else None


def main(seed):
    rng = random.Random(seed)
    restaurants = {}
    with gzip.open(DATA_DIR / "restaurants.jsonl.gz", "rt", encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            restaurant_id = str(row.get("restaurant_id") or "").strip()
            category = str(row.get("category") or "").strip()
            city = str(row.get("city") or "").strip()
            average_cost = positive_amount(row.get("average_cost"))
            if restaurant_id and category and city and average_cost:
                restaurants[restaurant_id] = {
                    "category": category,
                    "city": city,
                    "average_cost": average_cost,
                    "source": row.get("source", "unknown"),
                }

    review_counts = Counter()
    rating_stats = defaultdict(lambda: [0.0, 0])
    user_counts = Counter()

    def visit_reviews(callback):
        with gzip.open(DATA_DIR / "reviews.jsonl.gz", "rt", encoding="utf-8") as source:
            for line in source:
                review = json.loads(line)
                restaurant_id = str(review.get("restaurant_id") or "").strip()
                restaurant = restaurants.get(restaurant_id)
                if restaurant:
                    callback(review, restaurant)

    def collect_counts(review, restaurant):
        restaurant_id = str(review.get("restaurant_id"))
        review_counts[restaurant_id] += 1
        try:
            rating = float(review.get("overall_rating"))
        except (TypeError, ValueError):
            rating = None
        if rating is not None and 0 <= rating <= 5:
            rating_stats[restaurant_id][0] += rating
            rating_stats[restaurant_id][1] += 1
        user_id = str(review.get("user_id") or "").strip()
        if user_id:
            user_counts[user_id] += 1

    visit_reviews(collect_counts)

    restaurant_candidates = [
        restaurant_id for restaurant_id, count in review_counts.items()
        if count >= 30 and rating_stats[restaurant_id][1]
    ]
    rng.shuffle(restaurant_candidates)
    selected_restaurants, seen_categories = [], set()
    for restaurant_id in restaurant_candidates:
        category = restaurants[restaurant_id]["category"]
        if category not in seen_categories:
            selected_restaurants.append(restaurant_id)
            seen_categories.add(category)
        if len(selected_restaurants) == len(OWNER_NAMES):
            break
    if len(selected_restaurants) < len(OWNER_NAMES):
        for restaurant_id in restaurant_candidates:
            if restaurant_id not in selected_restaurants:
                selected_restaurants.append(restaurant_id)
            if len(selected_restaurants) == len(OWNER_NAMES):
                break
    if len(selected_restaurants) < len(OWNER_NAMES):
        raise RuntimeError("Not enough restaurants have 30+ linked reviews")

    eligible_users = [user_id for user_id, count in user_counts.items() if count >= 5]
    if len(eligible_users) < len(CUSTOMER_NAMES):
        raise RuntimeError("Not enough users have 5+ linked reviews")
    selected_users = rng.sample(eligible_users, len(CUSTOMER_NAMES))
    selected_user_set = set(selected_users)
    user_categories = defaultdict(Counter)
    user_costs = defaultdict(lambda: [0.0, 0])
    visited_venue_costs = defaultdict(lambda: [0.0, 0])

    def collect_sampled_histories(review, restaurant):
        user_id = str(review.get("user_id") or "").strip()
        if user_id not in selected_user_set:
            return
        user_categories[user_id][restaurant["category"]] += 1
        amount = positive_amount(review.get("cost"))
        if amount:
            user_costs[user_id][0] += amount
            user_costs[user_id][1] += 1
        visited_venue_costs[user_id][0] += restaurant["average_cost"]
        visited_venue_costs[user_id][1] += 1

    visit_reviews(collect_sampled_histories)

    sampled_restaurants = {}
    for owner, restaurant_id in zip(OWNER_NAMES, selected_restaurants):
        profile = restaurants[restaurant_id]
        rating_sum, rating_count = rating_stats[restaurant_id]
        sampled_restaurants[owner] = {
            "category": profile["category"],
            "city": profile["city"],
            "average_cost": round(profile["average_cost"], 2),
            "baseline_review_count": review_counts[restaurant_id],
            "baseline_rating": round((rating_sum / rating_count) * 2, 2),
            "source": profile["source"],
        }

    sampled_customers = {}
    for customer, user_id in zip(CUSTOMER_NAMES, selected_users):
        categories = user_categories[user_id]
        preferred_categories = [
            category for category, _ in sorted(
                categories.items(), key=lambda item: (-item[1], item[0])
            )[:3]
        ]
        total_cost, cost_count = user_costs[user_id]
        if cost_count:
            price_reference = total_cost / cost_count
            price_basis = "mean of recorded review-level spending"
        else:
            total_cost, cost_count = visited_venue_costs[user_id]
            price_reference = total_cost / cost_count if cost_count else None
            price_basis = "mean spend of reviewed restaurants (fallback estimate)"
        sampled_customers[customer] = {
            "preferred_categories": preferred_categories,
            "history_review_count": user_counts[user_id],
            "price_reference": round(price_reference, 2) if price_reference else None,
            "price_basis": price_basis,
        }

    profile_data = {
        "profile_type": "anonymized_aggregates_from_real_historical_data",
        "source_dataset": "Dianping_Three_Source_Merged",
        "generated_on": date.today().isoformat(),
        "random_seed": seed,
        "sampling": {
            "restaurant_min_review_count": 30,
            "customer_min_review_count": 5,
            "restaurant_method": "uniform random sample; prefer distinct categories",
            "customer_method": "uniform random sample from eligible reviewer IDs",
            "retained_fields": "aggregated categories, city, price, ratings and review counts only; no IDs or review text",
        },
        "restaurants": sampled_restaurants,
        "customers": sampled_customers,
    }
    OUTPUT_PATH.write_text(
        json.dumps(profile_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote anonymized profile set: {OUTPUT_PATH}")
    for name, profile in sampled_restaurants.items():
        print(
            f"restaurant {name}: {profile['city']} / {profile['category']}; "
            f"reviews={profile['baseline_review_count']}; cost={profile['average_cost']}; "
            f"rating={profile['baseline_rating']}"
        )
    for name, profile in sampled_customers.items():
        print(
            f"customer {name}: reviews={profile['history_review_count']}; "
            f"categories={profile['preferred_categories']}; "
            f"price_reference={profile['price_reference']}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    main(parser.parse_args().seed)
