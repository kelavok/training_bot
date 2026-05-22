from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt

import analytics
import db
import stats_formatter
import stats_view_service


CHART_COLORS = {
    "blue": "#2F6FDC",
    "green": "#2FA66A",
    "orange": "#F28C38",
    "red": "#D9534F",
    "purple": "#7E57C2",
    "gray": "#5F6B7A",
}


def setup_chart_style():
    plt.style.use("default")
    plt.rcParams.update(
        {
            "axes.grid": True,
            "grid.alpha": 0.25,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
        }
    )


def save_figure(fig, output_path: str | Path) -> Path:
    output_path = Path(output_path)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    return output_path


def add_bar_labels(ax, values, fmt="{:.1f}"):
    if not values:
        return

    max_value = max(values) or 1

    for index, value in enumerate(values):
        ax.text(
            value + max_value * 0.015,
            index,
            fmt.format(value),
            va="center",
            fontsize=9,
        )


def get_period_exercise_rows(period, user_id: int = 1):
    return db.get_exercise_stats_for_period(
        user_id=user_id,
        start_date=period.start_date,
        end_date=period.end_date,
    )


def get_period_muscle_rows(period, user_id: int = 1):
    return db.get_muscle_stats_for_period(
        user_id=user_id,
        start_date=period.start_date,
        end_date=period.end_date,
    )


def build_session_score_by_date(exercise_rows) -> list[dict]:
    rows_by_date = defaultdict(list)

    for row in exercise_rows:
        rows_by_date[row["date"]].append(row)

    history = []

    for training_date in sorted(rows_by_date.keys()):
        rows_for_date = rows_by_date[training_date]
        weighted_sum = 0.0
        weight_total = 0.0

        for row in rows_for_date:
            units = analytics.to_float(row["score_units"])
            rating = analytics.to_float(row["rating_10"])

            if units <= 0:
                continue

            weighted_sum += rating * units
            weight_total += units

        session_score = weighted_sum / weight_total if weight_total > 0 else 0.0

        history.append(
            {
                "date": training_date,
                "session_score": round(session_score, 1),
            }
        )

    return history


def save_period_dashboard(
    period_token: str | None,
    output_path: str | Path,
    user_id: int = 1,
) -> Path:
    setup_chart_style()

    overview = stats_view_service.build_overview(period_token=period_token, user_id=user_id)
    period = overview["period"]
    exercise_rows = get_period_exercise_rows(period, user_id=user_id)
    history = build_session_score_by_date(exercise_rows)

    if not exercise_rows:
        raise ValueError("Нет данных для dashboard за выбранный период.")

    top_muscles = overview["top_muscles"]
    top_exercises = overview["top_exercises"]

    fig = plt.figure(figsize=(14, 10))
    grid = fig.add_gridspec(2, 2, height_ratios=[1, 1.2])

    ax_summary = fig.add_subplot(grid[0, 0])
    ax_score = fig.add_subplot(grid[0, 1])
    ax_muscles = fig.add_subplot(grid[1, 0])
    ax_exercises = fig.add_subplot(grid[1, 1])

    basic = overview["basic"]
    ax_summary.axis("off")
    summary_lines = [
        f"Training days: {basic['training_days']}",
        f"Exercises: {basic['unique_exercises']}",
        f"Sets: {basic['total_sets']}",
        f"Working sets: {overview['working_sets']}",
        f"Heavy sets: {overview['heavy_sets']}",
        f"Volume: {analytics.to_float(basic['total_volume']):.1f} kg",
        f"Avg exercise score: {overview['avg_exercise_rating']:.1f}/10",
    ]
    ax_summary.text(
        0,
        0.95,
        "\n".join(summary_lines),
        va="top",
        fontsize=13,
        linespacing=1.5,
    )
    ax_summary.set_title("Period summary", loc="left", fontweight="bold")

    dates = [str(row["date"]) for row in history]
    scores = [row["session_score"] for row in history]
    ax_score.plot(dates, scores, marker="o", color=CHART_COLORS["blue"])
    ax_score.set_ylim(0, 10.5)
    ax_score.set_ylabel("Score")
    ax_score.set_title("Session score by training day", fontweight="bold")
    ax_score.tick_params(axis="x", rotation=45)

    muscle_names = [row["muscle"] for row in top_muscles][::-1]
    muscle_values = [analytics.to_float(row["score_units"]) for row in top_muscles][::-1]
    ax_muscles.barh(muscle_names, muscle_values, color=CHART_COLORS["green"])
    ax_muscles.set_title("Top muscles by score units", fontweight="bold")
    ax_muscles.set_xlabel("Score units")
    add_bar_labels(ax_muscles, muscle_values, fmt="{:.2f}")

    exercise_names = [row["exercise"] for row in top_exercises][::-1]
    exercise_values = [analytics.to_float(row["score_units"]) for row in top_exercises][::-1]
    ax_exercises.barh(exercise_names, exercise_values, color=CHART_COLORS["orange"])
    ax_exercises.set_title("Top exercises by score units", fontweight="bold")
    ax_exercises.set_xlabel("Score units")
    add_bar_labels(ax_exercises, exercise_values, fmt="{:.2f}")

    fig.suptitle(
        f"Training dashboard: {stats_formatter.format_period(period)}",
        fontsize=16,
        fontweight="bold",
    )

    return save_figure(fig, output_path)


def save_top_chart(
    target: str,
    metric: str,
    period_token: str | None,
    limit: int,
    output_path: str | Path,
    user_id: int = 1,
) -> Path:
    setup_chart_style()

    if target in {"exercise", "exercises"}:
        data = stats_view_service.build_top_exercises(
            period_token=period_token,
            metric=metric,
            limit=limit,
            user_id=user_id,
        )
        label_key = "exercise"
        color = CHART_COLORS["orange"]
        title_target = "exercises"
    else:
        data = stats_view_service.build_top_muscles(
            period_token=period_token,
            metric=metric,
            limit=limit,
            user_id=user_id,
        )
        label_key = "muscle"
        color = CHART_COLORS["green"]
        title_target = "muscles"

    rows = data["rows"]

    if not rows:
        raise ValueError("Нет данных для top chart за выбранный период.")

    labels = [row[label_key] for row in rows][::-1]
    values = [analytics.to_float(row.get(metric, row.get("metric_value"))) for row in rows][::-1]

    fig, ax = plt.subplots(figsize=(12, max(5, len(labels) * 0.55)))
    ax.barh(labels, values, color=color)
    ax.set_xlabel(stats_formatter.METRIC_LABELS.get(metric, metric))
    ax.set_title(
        f"Top {title_target}: {stats_formatter.METRIC_LABELS.get(metric, metric)}\n"
        f"{stats_formatter.format_period(data['period'])}",
        fontweight="bold",
    )
    add_bar_labels(ax, values, fmt="{:.2f}")

    return save_figure(fig, output_path)


def save_exercise_chart(
    exercise_input: str,
    period_token: str | None,
    output_path: str | Path,
    user_id: int = 1,
) -> Path:
    setup_chart_style()

    data = stats_view_service.build_exercise_detail(
        exercise_input=exercise_input,
        period_token=period_token,
        user_id=user_id,
    )
    rows = data["rows"]

    if not rows:
        raise ValueError(f"Нет данных по упражнению {data['exercise']} за выбранный период.")

    dates = [str(row["date"]) for row in rows]
    exercise_type = rows[-1]["exercise_type"]

    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
    ax_top, ax_units, ax_rating = axes

    if exercise_type == "static":
        duration = [analytics.to_float(row["total_duration_sec"]) for row in rows]
        ax_top.bar(dates, duration, color=CHART_COLORS["purple"])
        ax_top.set_ylabel("Seconds")
        ax_top.set_title("Duration", fontweight="bold")
    elif exercise_type in {"bodyweight", "reps_based"}:
        reps = [analytics.to_float(row["total_reps"]) for row in rows]
        ax_top.plot(dates, reps, marker="o", color=CHART_COLORS["blue"])
        ax_top.set_ylabel("Reps")
        ax_top.set_title("Total reps", fontweight="bold")
    else:
        e1rm = [analytics.to_float(row["best_estimated_1rm"]) for row in rows]
        working_weight = [
            analytics.to_float(row["working_weight"])
            if row["working_weight"] is not None
            else None
            for row in rows
        ]
        ax_top.plot(dates, e1rm, marker="o", label="best e1RM", color=CHART_COLORS["blue"])
        ax_top.plot(
            dates,
            working_weight,
            marker="o",
            label="working weight",
            color=CHART_COLORS["green"],
        )
        ax_top.set_ylabel("kg")
        ax_top.set_title("Strength trend", fontweight="bold")
        ax_top.legend()

    units = [analytics.to_float(row["score_units"]) for row in rows]
    volume = [analytics.to_float(row["total_volume"]) for row in rows]
    ax_units.bar(dates, units, color=CHART_COLORS["orange"], label="score units")
    ax_units.set_ylabel("Units")
    ax_units.set_title("Score units", fontweight="bold")

    if any(volume):
        ax_volume = ax_units.twinx()
        ax_volume.plot(dates, volume, marker="o", color=CHART_COLORS["gray"], label="volume")
        ax_volume.set_ylabel("Volume kg")

    ratings = [analytics.to_float(row["rating_10"]) for row in rows]
    ax_rating.plot(dates, ratings, marker="o", color=CHART_COLORS["red"])
    ax_rating.set_ylim(0, 10.5)
    ax_rating.set_ylabel("Score")
    ax_rating.set_title("Rating", fontweight="bold")
    ax_rating.tick_params(axis="x", rotation=45)

    reference = data["reference"]
    reference_text = ""
    if reference:
        reference_text = (
            f" | reference {analytics.to_float(reference['reference_value']):.1f} "
            f"({reference['reference_source']})"
        )

    fig.suptitle(
        f"{data['exercise']} progress: {stats_formatter.format_period(data['period'])}"
        f"{reference_text}",
        fontsize=15,
        fontweight="bold",
    )

    return save_figure(fig, output_path)


def save_muscle_chart(
    muscle_input: str,
    period_token: str | None,
    output_path: str | Path,
    user_id: int = 1,
) -> Path:
    setup_chart_style()

    data = stats_view_service.build_muscle_detail(
        muscle_input=muscle_input,
        period_token=period_token,
        user_id=user_id,
    )
    rows = data["rows"]

    if not rows:
        raise ValueError(f"Нет данных по мышце {data['muscle']} за выбранный период.")

    dates = [str(row["date"]) for row in rows]
    units = [analytics.to_float(row["score_units"]) for row in rows]
    ratings = [analytics.to_float(row["rating_10"]) for row in rows]

    fig, ax_units = plt.subplots(figsize=(12, 7))
    ax_rating = ax_units.twinx()

    ax_units.bar(dates, units, color=CHART_COLORS["green"], alpha=0.75, label="score units")
    ax_rating.plot(dates, ratings, marker="o", color=CHART_COLORS["red"], label="rating")

    ax_units.set_ylabel("Score units")
    ax_rating.set_ylabel("Rating 0-10")
    ax_rating.set_ylim(0, 10.5)
    ax_units.tick_params(axis="x", rotation=45)

    lines_1, labels_1 = ax_units.get_legend_handles_labels()
    lines_2, labels_2 = ax_rating.get_legend_handles_labels()
    ax_units.legend(lines_1 + lines_2, labels_1 + labels_2, loc="upper left")

    ax_units.set_title(
        f"{data['muscle']} muscle trend: {stats_formatter.format_period(data['period'])}",
        fontweight="bold",
    )

    return save_figure(fig, output_path)


def save_muscle_trend_chart_from_aggregates(
    period_token: str | None,
    output_path: str | Path,
    top_n: int = 8,
    user_id: int = 1,
) -> Path:
    setup_chart_style()

    period = stats_view_service.resolve_period(period_token, user_id=user_id)
    rows = get_period_muscle_rows(period, user_id=user_id)

    if not rows:
        raise ValueError("Нет данных по мышцам за выбранный период.")

    total_units_by_muscle = defaultdict(float)
    rows_by_muscle = defaultdict(dict)
    dates = sorted({row["date"] for row in rows})

    for row in rows:
        muscle = row["muscle"]
        total_units_by_muscle[muscle] += analytics.to_float(row["score_units"])
        rows_by_muscle[muscle][row["date"]] = analytics.to_float(row["rating_10"])

    selected_muscles = [
        muscle
        for muscle, _ in sorted(
            total_units_by_muscle.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:top_n]
    ]

    fig, ax = plt.subplots(figsize=(13, 7))
    x_labels = [str(training_date) for training_date in dates]

    for muscle in selected_muscles:
        values = []
        for training_date in dates:
            values.append(rows_by_muscle[muscle].get(training_date))

        ax.plot(x_labels, values, marker="o", linewidth=2, label=muscle)

    ax.set_ylim(0, 10.5)
    ax.set_ylabel("Rating 0-10")
    ax.set_title(
        f"Muscle trend: {stats_formatter.format_period(period)}",
        fontweight="bold",
    )
    ax.tick_params(axis="x", rotation=45)
    ax.legend()

    return save_figure(fig, output_path)
