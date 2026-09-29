"""Plot counts of sampled restaurant and customer archetype profiles."""

import json
from pathlib import Path

import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
POOL = ROOT / "datasets" / "Dianping_Beijing_Subset" / "sampled_portrait_pool"
OUT = POOL / "figures"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    restaurants = json.loads((POOL / "restaurants.json").read_text(encoding="utf-8"))
    customers = json.loads((POOL / "customers.json").read_text(encoding="utf-8"))
    summary = json.loads((POOL / "sampling_summary.json").read_text(encoding="utf-8"))

    restaurant_counts = {}
    for row in restaurants:
        label = f"{row['profile_family']}\n{row['price_tier']}"
        restaurant_counts[label] = restaurant_counts.get(label, 0) + 1
    labels = list(restaurant_counts)
    values = [restaurant_counts[label] for label in labels]

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(13, 6.5))
    bars = ax.bar(range(len(labels)), values, color="#3977A8")
    ax.set_title("20家抽样餐厅：典型画像类别数量")
    ax.set_ylabel("餐厅数量")
    ax.set_xlabel("餐厅画像（菜系大类 × 人均消费档）")
    ax.set_xticks(range(len(labels)), labels, rotation=35, ha="right")
    ax.set_ylim(0, max(values, default=1) + 1.5)
    ax.bar_label(bars, padding=3)
    ax.grid(axis="y", alpha=0.22)
    fig.tight_layout()
    fig.savefig(OUT / "sampled_restaurant_archetype_counts.png", dpi=180)
    plt.close(fig)

    groups = [row for row in summary["customer_group_distribution"] if row["sampled_agents"] > 0]
    groups.sort(key=lambda row: row["sampled_agents"], reverse=True)
    labels = [row["archetype"].replace(" × ", "\n× ") for row in groups]
    counts = [row["sampled_agents"] for row in groups]
    population_shares = [row["population_share"] * 100 for row in groups]
    positions = list(range(len(groups)))
    fig, ax = plt.subplots(figsize=(14, 8))
    bars = ax.barh(positions, counts, color="#D27846")
    ax.set_yticks(positions, labels)
    ax.invert_yaxis()
    ax.set_xlabel("Agent数量（共120位）")
    ax.set_title("120位顾客Agent：典型画像群体与抽样数量")
    ax.set_xlim(0, max(counts, default=1) + 15)
    for bar, count, share in zip(bars, counts, population_shares):
        ax.text(bar.get_width() + 0.6, bar.get_y() + bar.get_height() / 2,
                f"{count}位  |  总体占比 {share:.2f}%", va="center", fontsize=8.5)
    ax.grid(axis="x", alpha=0.22)
    fig.tight_layout()
    fig.savefig(OUT / "sampled_customer_agent_archetype_counts.png", dpi=180)
    plt.close(fig)

    print("\n".join(str(path) for path in sorted(OUT.glob("*.png"))))


if __name__ == "__main__":
    main()
