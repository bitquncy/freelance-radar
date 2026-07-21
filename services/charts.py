"""Chart generation for vacancy statistics."""
import io
from typing import Dict, Any, Optional, List
from datetime import datetime

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from services.logger_config import get_logger

logger = get_logger(__name__)


def generate_vacancy_stats_chart(stats: Dict[str, Any]) -> Optional[bytes]:
    """Generate a pie chart of vacancy status distribution.

    Args:
        stats: Dictionary from get_vacancy_stats.

    Returns:
        PNG image bytes or None on failure.
    """
    try:
        total = stats.get("total", 0)
        if total == 0:
            return None

        unseen = stats.get("unseen", 0)
        responded = stats.get("responded", 0)
        filtered = stats.get("filtered_out", 0)
        seen = max(0, total - unseen - responded - filtered)

        labels = []
        sizes = []
        colors = []
        explode = []

        if unseen > 0:
            labels.append(f"Новые\n{unseen}")
            sizes.append(unseen)
            colors.append("#4CAF50")
            explode.append(0.05)
        if seen > 0:
            labels.append(f"Просмотрены\n{seen}")
            sizes.append(seen)
            colors.append("#2196F3")
            explode.append(0)
        if responded > 0:
            labels.append(f"Откликнуты\n{responded}")
            sizes.append(responded)
            colors.append("#9C27B0")
            explode.append(0.05)
        if filtered > 0:
            labels.append(f"Отфильтрованы\n{filtered}")
            sizes.append(filtered)
            colors.append("#F44336")
            explode.append(0)

        if not sizes:
            return None

        fig, ax = plt.subplots(figsize=(8, 6))
        wedges, texts, autotexts = ax.pie(
            sizes,
            explode=explode,
            labels=labels,
            colors=colors,
            autopct=lambda pct: f"{pct:.1f}%" if pct > 5 else "",
            shadow=False,
            startangle=90,
            textprops={"fontsize": 11},
        )
        ax.set_title(f"Распределение вакансий (всего: {total})", fontsize=14, fontweight="bold")

        buf = io.BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    except (ValueError, TypeError, OSError, RuntimeError) as e:
        logger.error("chart.stats_generation_failed", error=str(e))
        return None


def generate_source_distribution_chart(by_source: Dict[str, int]) -> Optional[bytes]:
    """Generate a horizontal bar chart of vacancies by source.

    Args:
        by_source: Dict mapping source name to count.

    Returns:
        PNG image bytes or None on failure.
    """
    try:
        if not by_source:
            return None

        sources = list(by_source.keys())
        counts = list(by_source.values())

        fig, ax = plt.subplots(figsize=(8, max(4, len(sources) * 0.6)))
        bars = ax.barh(sources, counts, color="steelblue")

        for bar, count in zip(bars, counts):
            ax.text(
                bar.get_width() + 0.5,
                bar.get_y() + bar.get_height() / 2,
                str(count),
                va="center",
                fontsize=10,
            )

        ax.set_xlabel("Количество вакансий", fontsize=11)
        ax.set_title("Вакансии по источникам", fontsize=14, fontweight="bold")
        ax.invert_yaxis()
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    except (ValueError, TypeError, OSError, RuntimeError) as e:
        logger.error("chart.source_generation_failed", error=str(e))
        return None


def generate_priority_distribution_chart(
    high: int, medium: int, low: int
) -> Optional[bytes]:
    """Generate a bar chart of priority distribution.

    Args:
        high: Number of high priority vacancies.
        medium: Number of medium priority vacancies.
        low: Number of low priority vacancies.

    Returns:
        PNG image bytes or None on failure.
    """
    try:
        total = high + medium + low
        if total == 0:
            return None

        labels = ["🔥 High", "⭐ Medium", "📌 Low"]
        counts = [high, medium, low]
        colors = ["#F44336", "#FF9800", "#9E9E9E"]

        fig, ax = plt.subplots(figsize=(7, 5))
        bars = ax.bar(labels, counts, color=colors, edgecolor="white", linewidth=1.5)

        for bar, count in zip(bars, counts):
            height = bar.get_height()
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                height + total * 0.01,
                f"{count}\n({count / total * 100:.1f}%)",
                ha="center",
                va="bottom",
                fontsize=11,
                fontweight="bold",
            )

        ax.set_ylabel("Количество", fontsize=11)
        ax.set_title("Распределение по приоритету", fontsize=14, fontweight="bold")
        ax.set_ylim(0, max(counts) * 1.2 if counts else 1)
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    except (ValueError, TypeError, OSError, RuntimeError) as e:
        logger.error("chart.priority_generation_failed", error=str(e))
        return None


def generate_daily_activity_chart(daily_counts: List[tuple]) -> Optional[bytes]:
    """Generate a line chart of daily vacancy activity.

    Args:
        daily_counts: List of (date_str, count) tuples.

    Returns:
        PNG image bytes or None on failure.
    """
    try:
        if not daily_counts:
            return None

        dates = [datetime.strptime(d, "%Y-%m-%d") for d, _ in daily_counts]
        counts = [c for _, c in daily_counts]

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(dates, counts, marker="o", linewidth=2, markersize=6, color="steelblue")
        ax.fill_between(dates, counts, alpha=0.3, color="steelblue")

        ax.set_xlabel("Дата", fontsize=11)
        ax.set_ylabel("Новых вакансий", fontsize=11)
        ax.set_title("Активность по дням", fontsize=14, fontweight="bold")

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, len(dates) // 7)))
        plt.xticks(rotation=45, ha="right")
        plt.grid(True, alpha=0.3)
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    except (ValueError, TypeError, OSError, RuntimeError) as e:
        logger.error("chart.activity_generation_failed", error=str(e))
        return None
