import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import FuncFormatter


ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "datasets"
OUT = DATASETS / "figures"
STATS = json.loads((DATASETS / "all_datasets_profile_stats.json").read_text(encoding="utf-8"))
BINS = ["1", "2", "3–4", "5–9", "10–19", "20–49", "50–99", "100+"]
COLORS = ["#2F6B8A", "#D1873A", "#6A8E5B"]


def configure_font():
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
    ]
    for path in candidates:
        if path.exists():
            font_manager.fontManager.addfont(str(path))
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(path)).get_name()
            break
    plt.rcParams["axes.unicode_minus"] = False


def add_value_labels(ax, bars):
    for bar in bars:
        value = int(bar.get_height())
        if value:
            ax.annotate(
                f"{value:,}",
                (bar.get_x() + bar.get_width() / 2, value),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=8,
                rotation=35,
            )


def categorical_figure(filename, title, panels):
    fig, axes = plt.subplots(1, len(panels), figsize=(7 * len(panels), 5), squeeze=False)
    for index, (panel_title, values, xlabels) in enumerate(panels):
        ax = axes[0][index]
        bars = ax.bar(xlabels, values, color=COLORS[index % len(COLORS)], width=0.72)
        ax.set_title(panel_title, fontsize=12)
        ax.set_xlabel("记录数区间")
        ax.set_ylabel("实体数量")
        ax.tick_params(axis="x", rotation=35)
        ax.grid(axis="y", alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{int(x):,}"))
        add_value_labels(ax, bars)
    fig.suptitle(title, fontsize=15, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(OUT / filename, dpi=180, bbox_inches="tight")
    plt.close(fig)


def history_values(node):
    source = node["history_bins"]
    keys = ["1", "2", "3-4", "5-9", "10-19", "20-49", "50-99", "100+"]
    return [source[key] for key in keys]


def sandwich_figure():
    receipts = STATS["Sandwich_Analytics"]["receipts_per_store"]["entity_values"]
    items = STATS["Sandwich_Analytics"]["item_rows_per_store"]["entity_values"]
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    for ax, values, name, color in (
        (axes[0], receipts, "每家门店小票数", COLORS[0]),
        (axes[1], items, "每家门店菜品明细行数", COLORS[1]),
    ):
        ax.hist(values, bins=6, color=color, edgecolor="white")
        ax.set_title(name, fontsize=12)
        ax.set_xlabel("记录数量")
        ax.set_ylabel("门店数量")
        ax.grid(axis="y", alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x / 10000:.0f}万"))
    fig.suptitle("Sandwich Analytics 门店交易量分布", fontsize=15, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(OUT / "sandwich-analytics-histogram.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def restaurant_style_figure(restaurant_only):
    styles = restaurant_only["restaurant_metadata"]["top_styles"]
    labels = list(styles.keys())[:20]
    values = [styles[label] for label in labels]
    fig, ax = plt.subplots(figsize=(14, 7))
    bars = ax.bar(labels, values, color=COLORS[2], width=0.72)
    ax.set_title("Yongfeng 高置信度餐厅子集：主要餐厅类型数量", fontsize=15, fontweight="bold")
    ax.set_xlabel("餐厅类型（style）")
    ax.set_ylabel("商户元数据数量")
    ax.tick_params(axis="x", rotation=48)
    ax.grid(axis="y", alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{int(x):,}"))
    add_value_labels(ax, bars)
    fig.tight_layout()
    fig.savefig(OUT / "yongfeng-restaurant-style-histogram.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    configure_font()
    yongfeng = json.loads(
        (DATASETS / "Yongfeng_Dianping" / "statistics.json").read_text(encoding="utf-8")
    )
    categorical_figure(
        "yongfeng-dianping-histogram.png",
        "Yongfeng Dianping 原始数据评论数量分布",
        [
            ("每名用户的非空评论数", history_values(yongfeng["reviews"]["users_with_text"]), BINS),
            ("每个商户的非空评论数", history_values(yongfeng["reviews"]["businesses_with_text"]), BINS),
        ],
    )
    restaurant_only = json.loads(
        (DATASETS / "Yongfeng_Dianping" / "restaurant_only_statistics.json").read_text(encoding="utf-8")
    )
    categorical_figure(
        "yongfeng-restaurant-only-histogram.png",
        "Yongfeng 高置信度餐厅子集评论数量分布",
        [
            ("每名用户的非空餐厅评论数", history_values(restaurant_only["reviews"]["users_with_text"]), BINS),
            ("每家餐厅的非空评论数", history_values(restaurant_only["reviews"]["restaurants_with_text"]), BINS),
        ],
    )
    restaurant_style_figure(restaurant_only)
    merged = json.loads(
        (DATASETS / "Dianping_Merged_Restaurants" / "profile_statistics.json").read_text(encoding="utf-8")
    )
    categorical_figure(
        "dianping-merged-histogram.png",
        f"合并后 Dianping：{merged['review_rows']:,} 条评论，{merged['restaurants_with_reviews']:,} 家有评论餐厅",
        [
            ("每名用户的评论数", history_values(merged["users"]), BINS),
            ("每家餐厅的评论数", history_values(merged["restaurants"]), BINS),
        ],
    )
    categorical_figure(
        "yf-dianping-histogram.png",
        "yf_dianping 评论数量分布",
        [
            ("每名用户的非空评论数", history_values(STATS["yf_dianping"]["users"]), BINS),
            ("每个商户的非空评论数", history_values(STATS["yf_dianping"]["businesses"]), BINS),
        ],
    )
    categorical_figure(
        "stanford-dianping-histogram.png",
        "Stanford Dianping 评论数量分布",
        [
            ("每名用户的评论数", history_values(STATS["stanford"]["users"]), BINS),
            ("每家餐厅的评论数", history_values(STATS["stanford"]["restaurants"]), BINS),
        ],
    )
    categorical_figure(
        "pku-dianping-histogram.png",
        "北大广州粤菜评论数量分布",
        [
            ("每个评论者显示名称的评论数", history_values(STATS["pku"]["users_by_display_name"]), BINS),
            ("每家餐厅的评论数", history_values(STATS["pku"]["restaurants"]), BINS),
        ],
    )
    categorical_figure(
        "asap-histogram.png",
        "ASAP 评论星级分布",
        [("各星级评论数量", list(STATS["ASAP"]["stars"].values()), ["1星", "2星", "3星", "4星", "5星"])],
    )
    categorical_figure(
        "sequentialrec-histogram.png",
        "SequentialRec 行为数量分布",
        [
            ("每名用户的行为数", history_values(STATS["SequentialRec"]["users"]), BINS),
            ("每家餐厅的行为数", history_values(STATS["SequentialRec"]["restaurants"]), BINS),
        ],
    )
    categorical_figure(
        "socialrec-histogram.png",
        "SocialRec 评分与好友数量分布",
        [
            ("每名用户的评分数", history_values(STATS["SocialRec"]["users_with_ratings"]), BINS),
            ("每家餐厅的评分数", history_values(STATS["SocialRec"]["restaurants"]), BINS),
            ("每名用户的好友数", history_values(STATS["SocialRec"]["friend_degree"]), BINS),
        ],
    )
    sandwich_figure()


if __name__ == "__main__":
    main()
