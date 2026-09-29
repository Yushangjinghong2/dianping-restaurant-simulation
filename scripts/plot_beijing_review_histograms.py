"""Plot per-restaurant and per-customer review-count histograms."""

import collections
import gzip
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "datasets" / "Dianping_Beijing_Subset"
FIGURES = DATA / "figures"
BIN_LABELS = ["1", "2", "3–4", "5–9", "10–19", "20–49", "50–99", "100+"]


def setup_font():
    for path in (Path("C:/Windows/Fonts/msyh.ttc"), Path("C:/Windows/Fonts/simhei.ttf")):
        if path.exists():
            font_manager.fontManager.addfont(str(path))
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(path)).get_name()
            break
    plt.rcParams["axes.unicode_minus"] = False


def bucket_counts(counter):
    counts = [0] * len(BIN_LABELS)
    for value in counter.values():
        if value == 1:
            index = 0
        elif value == 2:
            index = 1
        elif value <= 4:
            index = 2
        elif value <= 9:
            index = 3
        elif value <= 19:
            index = 4
        elif value <= 49:
            index = 5
        elif value <= 99:
            index = 6
        else:
            index = 7
        counts[index] += 1
    return counts


def plot_histogram(filename, title, values, color, entity_label):
    fig, ax = plt.subplots(figsize=(9, 5.2))
    bars = ax.bar(BIN_LABELS, values, color=color, width=0.72)
    ax.set_title(title, fontsize=15, fontweight="bold")
    ax.set_xlabel("每个" + entity_label + "的评论记录数")
    ax.set_ylabel(entity_label + "数量")
    ax.grid(axis="y", alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    ax.yaxis.set_major_formatter(lambda value, _: f"{int(value):,}")
    for bar in bars:
        height = int(bar.get_height())
        ax.annotate(
            f"{height:,}",
            (bar.get_x() + bar.get_width() / 2, height),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    fig.tight_layout()
    fig.savefig(FIGURES / filename, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main():
    setup_font()
    FIGURES.mkdir(parents=True, exist_ok=True)
    restaurant_reviews = collections.Counter()
    customer_reviews = collections.Counter()
    invalid_user_rows = 0

    with gzip.open(DATA / "reviews.jsonl.gz", "rt", encoding="utf-8") as handle:
        for line in handle:
            review = json.loads(line)
            restaurant_id = review.get("restaurant_id")
            if restaurant_id not in (None, ""):
                restaurant_reviews[str(restaurant_id)] += 1
            user_id = review.get("user_id")
            if user_id not in (None, "", -1, "-1"):
                customer_reviews[str(user_id)] += 1
            else:
                invalid_user_rows += 1

    restaurant_bins = bucket_counts(restaurant_reviews)
    customer_bins = bucket_counts(customer_reviews)
    plot_histogram(
        "beijing-restaurant-review-count-histogram.png",
        "北京餐厅累计评论数分布",
        restaurant_bins,
        "#2F6B8A",
        "餐厅",
    )
    plot_histogram(
        "beijing-customer-review-count-histogram.png",
        "北京顾客累计评论数分布",
        customer_bins,
        "#D1873A",
        "顾客",
    )

    stats_path = DATA / "statistics.json"
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    stats["review_count_distributions"] = {
        "bin_labels": BIN_LABELS,
        "restaurants_with_reviews": len(restaurant_reviews),
        "restaurants_by_review_count_bin": dict(zip(BIN_LABELS, restaurant_bins)),
        "customers_with_valid_user_id": len(customer_reviews),
        "customers_by_review_count_bin": dict(zip(BIN_LABELS, customer_bins)),
        "review_rows_with_missing_or_unknown_user_id": invalid_user_rows,
        "count_basis": "all linked review rows, including rows with empty review content",
    }
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats["review_count_distributions"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
