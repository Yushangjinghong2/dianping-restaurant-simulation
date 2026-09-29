"""Rule-based restaurant choice with independent, reproducible sampling."""

import hashlib
import math
import random


def _number(value, default=0.0):
    try:
        if value in (None, "", "NULL", "null"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _minmax(values):
    if not values:
        return {}
    low = min(values.values())
    high = max(values.values())
    if math.isclose(low, high):
        return {key: 0.5 for key in values}
    return {key: (value - low) / (high - low) for key, value in values.items()}


def _average_menu_price(menu):
    prices = [
        _number(item.get("price"), default=-1.0)
        for item in (menu or [])
        if isinstance(item, dict)
    ]
    prices = [price for price in prices if price > 0]
    return sum(prices) / len(prices) if prices else None


class RestaurantChoicePolicy:
    """Select a restaurant by softmax utility plus uniform exploration."""

    def __init__(self, config=None):
        config = dict(config or {})
        self.epsilon = min(max(_number(config.get("epsilon"), 0.05), 0.0), 1.0)
        self.repeat_penalty = max(_number(config.get("repeat_penalty"), 0.8), 0.0)
        self.price_penalty = max(_number(config.get("price_penalty"), 0.5), 0.0)
        self.preference_strength = max(_number(config.get("preference_strength"), 0.5), 0.0)
        self.recommendation_strength = max(
            _number(config.get("recommendation_strength"), 1.0), 0.0
        )
        self.weights = config.get("recommendation_weights", {})
        self.weights = {
            "review_count": max(_number(self.weights.get("review_count"), 0.35), 0.0),
            "recent_diners": max(_number(self.weights.get("recent_diners"), 0.35), 0.0),
            "rating": max(_number(self.weights.get("rating"), 0.30), 0.0),
        }
        weight_sum = sum(self.weights.values())
        if weight_sum == 0:
            self.weights = {key: 1 / 3 for key in self.weights}
        else:
            self.weights = {key: value / weight_sum for key, value in self.weights.items()}
        self.seed = int(_number(config.get("seed"), 2026))
        self.exploration_floor = min(
            max(_number(config.get("exploration_floor"), self.epsilon), 0.0), 1.0
        )

    def choose(
        self,
        customer_name,
        restaurants,
        visit_counts=None,
        price_reference=None,
        preference_keywords=None,
        turn=1,
        preference_categories=None,
        spice_preference="medium",
    ):
        """Return a restaurant and a trace of the probability calculation.

        ``restaurants`` maps display names to structured restaurant data. Each
        record may contain ``restaurant_id``, ``menu``, ``review_count``,
        ``recent_diners`` and ``rating``.
        """
        if not restaurants:
            raise ValueError("At least one restaurant is required for choice")

        visit_counts = visit_counts or {}
        preference_keywords = [
            str(keyword).casefold().strip()
            for keyword in (preference_keywords or [])
            if str(keyword).strip()
        ]
        preference_categories = [
            str(category).casefold().strip()
            for category in (preference_categories or [])
            if str(category).strip()
        ]
        review_values = {
            name: math.log1p(max(_number(data.get("review_count")), 0.0))
            for name, data in restaurants.items()
        }
        diner_values = {
            name: math.log1p(max(_number(data.get("recent_diners")), 0.0))
            for name, data in restaurants.items()
        }
        scaled_reviews = _minmax(review_values)
        scaled_diners = _minmax(diner_values)

        utilities = {}
        trace = {}
        for name, data in restaurants.items():
            restaurant_id = str(data.get("restaurant_id", name))
            visits = max(_number(visit_counts.get(restaurant_id)), 0.0)
            review_signal = scaled_reviews[name]
            diner_signal = scaled_diners[name]
            rating_signal = min(max(_number(data.get("rating"), 5.0) / 10.0, 0.0), 1.0)
            recommendation = (
                self.weights["review_count"] * review_signal
                + self.weights["recent_diners"] * diner_signal
                + self.weights["rating"] * rating_signal
            )
            repeat_cost = self.repeat_penalty * math.log1p(visits)

            menu_text = " ".join(
                f"{item.get('name', '')} {item.get('description', '')}"
                for item in (data.get("menu") or [])
                if isinstance(item, dict)
            ).casefold()
            taste_match = (
                sum(keyword in menu_text for keyword in preference_keywords)
                / len(preference_keywords)
                if preference_keywords
                else 0.5
            )
            restaurant_categories = [data.get("category")]
            tags = data.get("tags", [])
            if isinstance(tags, str):
                restaurant_categories.append(tags)
            else:
                restaurant_categories.extend(tags or [])
            normalized_restaurant_categories = [
                str(category).casefold().strip()
                for category in restaurant_categories
                if category and str(category).strip()
            ]
            category_match = float(any(
                preference == category
                or preference in category
                or category in preference
                for preference in preference_categories
                for category in normalized_restaurant_categories
            ))
            if preference_categories:
                taste_match = (
                    (taste_match + category_match) / 2
                    if preference_keywords
                    else category_match
                )

            restaurant_price = _average_menu_price(data.get("menu"))
            price_cost = 0.0
            if price_reference and restaurant_price:
                price_cost = self.price_penalty * abs(
                    math.log(restaurant_price / price_reference)
                )

            spice_penalty = 0.0
            menu_has_spicy = any(
                any(tag in f"{item.get('name', '')} {item.get('description', '')}".casefold()
                    for tag in ("spicy", "chili", "chilli", "hot pot", "辣"))
                for item in (data.get("menu") or []) if isinstance(item, dict)
            )
            if menu_has_spicy and str(spice_preference).lower() in ("none", "low"):
                spice_penalty = 0.2 if str(spice_preference).lower() == "low" else 0.35

            utility = (
                self.recommendation_strength * recommendation
                + self.preference_strength * taste_match
                - repeat_cost
                - price_cost
                - spice_penalty
            )
            utilities[name] = utility
            trace[name] = {
                "restaurant_id": restaurant_id,
                "utility": utility,
                "recommendation_score": recommendation,
                "taste_match": taste_match,
                "category_match": category_match,
                "review_signal": review_signal,
                "recent_diner_signal": diner_signal,
                "rating_signal": rating_signal,
                "repeat_cost": repeat_cost,
                "price_cost": price_cost,
                "spice_penalty": spice_penalty,
                "menu_average_price": restaurant_price,
            }

        max_utility = max(utilities.values())
        exp_utilities = {
            name: math.exp(value - max_utility) for name, value in utilities.items()
        }
        exp_sum = sum(exp_utilities.values())
        softmax = {name: value / exp_sum for name, value in exp_utilities.items()}
        candidate_count = len(restaurants)
        probabilities = {
            name: (1 - self.epsilon) * softmax[name] + self.epsilon / candidate_count
            for name in restaurants
        }
        # Keep every restaurant meaningfully discoverable, even when the
        # recommendation signals become highly concentrated.
        probabilities = {
            name: (1 - self.exploration_floor) * probabilities[name]
            + self.exploration_floor / candidate_count
            for name in restaurants
        }
        probability_sum = sum(probabilities.values())
        probabilities = {
            name: probability / probability_sum
            for name, probability in probabilities.items()
        }

        seed_material = f"{self.seed}:{customer_name}:{turn}".encode("utf-8")
        rng_seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big")
        rng = random.Random(rng_seed)
        selected = rng.choices(
            list(probabilities), weights=list(probabilities.values()), k=1
        )[0]

        return {
            "restaurant": selected,
            "probabilities": probabilities,
            "features": trace,
            "turn": turn,
            "seed": self.seed,
        }
