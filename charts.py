from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt

import analytics



def group_rows_by_date(rows: list[dict]) -> dict:
    rows_by_date = defaultdict(list)

    for row in rows:
        rows_by_date[row["date"]].append(row)

    return dict(rows_by_date)


def build_muscle_trend_data(
    rows: list[dict],
    top_n: int = 8,
    reference_values: dict | None = None,
) -> tuple[list, list[str], dict]:
    rows_by_date = group_rows_by_date(rows)

    dates = sorted(rows_by_date.keys())

    daily_scores = {}
    total_units_by_muscle = defaultdict(float)

    # If a muscle receives only a tiny secondary contribution,
    # we do not treat it as actually trained on that date.
    # Example: Romanian Deadlift may touch back a little,
    # but it should not create a "back day" point on the trend chart.
    MIN_ACTUAL_MUSCLE_SHARE_OF_TARGET = 0.2

    for training_date in dates:
        result = analytics.calculate_session_scores(
            rows_by_date[training_date],
            reference_values=reference_values,
        )

        muscle_scores = {}

        for muscle_row in result["muscle_summary"]:
            muscle = muscle_row["muscle"]
            rating = muscle_row["rating_10"]
            units = muscle_row["score_units"]
            target_units = muscle_row["target_units"]

            if target_units > 0:
                actual_share = units / target_units
            else:
                actual_share = 0

            # Do not create a real data point from tiny secondary carryover.
            if actual_share < MIN_ACTUAL_MUSCLE_SHARE_OF_TARGET:
                continue

            muscle_scores[muscle] = rating
            total_units_by_muscle[muscle] += units

        daily_scores[training_date] = muscle_scores

    selected_muscles = [
        muscle
        for muscle, _ in sorted(
            total_units_by_muscle.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:top_n]
    ]

    return dates, selected_muscles, daily_scores


def save_muscle_trend_chart(
    rows: list[dict],
    output_path: str | Path,
    top_n: int = 8,
    reference_values: dict | None = None,
) -> Path:
    output_path = Path(output_path)

    dates, selected_muscles, daily_scores = build_muscle_trend_data(
        rows=rows,
        top_n=top_n,
        reference_values=reference_values,
    )

    if not dates or not selected_muscles:
        raise ValueError("Недостаточно данных для построения графика.")

    x_labels = [str(date) for date in dates]
    x_positions = list(range(len(dates)))

    plt.figure(figsize=(12, 7))

    for muscle in selected_muscles:
        carried_y_values = []
        actual_x_values = []
        actual_y_values = []

        last_known_value = None
        has_any_value = False

        for i, date in enumerate(dates):
            current_score = daily_scores.get(date, {}).get(muscle)

            if current_score is not None:
                last_known_value = current_score
                has_any_value = True

                actual_x_values.append(i)
                actual_y_values.append(current_score)

            carried_y_values.append(last_known_value)

        if not has_any_value:
            continue

        # Линия показывает последнее известное значение.
        # Но без маркеров, чтобы не врать, будто группа тренировалась в этот день.
        line = plt.plot(
            x_positions,
            carried_y_values,
            linewidth=2,
            label=muscle,
        )[0]

        # Маркеры ставим только на реальные даты тренировки этой группы.
        plt.scatter(
            actual_x_values,
            actual_y_values,
            color=line.get_color(),
            s=45,
        )

    plt.title("Muscle group training score over time")
    plt.xlabel("Training date")
    plt.ylabel("Score, 0–10")
    plt.ylim(0, 10.5)
    plt.xticks(x_positions, x_labels, rotation=45, ha="right")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()

    plt.savefig(output_path, dpi=150)
    plt.close()

    return output_path


def build_session_score_history(
    rows: list[dict],
    reference_values: dict | None = None,
) -> list[dict]:
    rows_by_date = group_rows_by_date(rows)
    dates = sorted(rows_by_date.keys())

    history = []

    for training_date in dates:
        result = analytics.calculate_session_scores(
            rows_by_date[training_date],
            reference_values=reference_values,
        )

        history.append(
            {
                "date": training_date,
                "session_score": result["session_score"],
                "result": result,
            }
        )

    return history


def save_latest_score_dashboard(
    rows: list[dict],
    output_path: str | Path,
    reference_values: dict | None = None,
) -> Path:
    output_path = Path(output_path)

    history = build_session_score_history(
        rows,
        reference_values=reference_values,
    )

    if not history:
        raise ValueError("Недостаточно данных для построения графика.")

    latest = history[-1]
    latest_result = latest["result"]
    latest_date = latest["date"]
    latest_score = latest["session_score"]

    previous_score = history[-2]["session_score"] if len(history) >= 2 else None

    if previous_score is not None:
        score_delta = round(latest_score - previous_score, 1)

        if previous_score != 0:
            score_delta_pct = round((score_delta / previous_score) * 100, 1)
        else:
            score_delta_pct = None
    else:
        score_delta = None
        score_delta_pct = None

    muscle_summary = latest_result["muscle_summary"]

    if not muscle_summary:
        raise ValueError("Нет данных по мышечным группам для последней тренировки.")

    muscles = [row["muscle"] for row in muscle_summary]
    ratings = [row["rating_10"] for row in muscle_summary]
    units = [row["score_units"] for row in muscle_summary]

    total_units = sum(units)

    history_dates = [str(row["date"]) for row in history]
    history_scores = [row["session_score"] for row in history]

    fig = plt.figure(figsize=(14, 9))

    ax_big = fig.add_subplot(2, 2, 1)
    ax_bar = fig.add_subplot(2, 2, 2)
    ax_pie = fig.add_subplot(2, 2, 3)
    ax_line = fig.add_subplot(2, 2, 4)

    ax_big.axis("off")

    ax_big.text(
        0.5,
        0.68,
        f"{latest_score}/10",
        ha="center",
        va="center",
        fontsize=42,
        fontweight="bold",
    )

    ax_big.text(
        0.5,
        0.48,
        f"Session score · {latest_date}",
        ha="center",
        va="center",
        fontsize=14,
    )

    if score_delta is not None:
        if score_delta > 0:
            delta_text = f"+{score_delta} points"
        else:
            delta_text = f"{score_delta} points"

        if score_delta_pct is not None:
            if score_delta_pct > 0:
                pct_text = f"+{score_delta_pct}%"
            else:
                pct_text = f"{score_delta_pct}%"

            delta_text = f"{delta_text} / {pct_text}"

        ax_big.text(
            0.5,
            0.32,
            f"vs previous: {delta_text}",
            ha="center",
            va="center",
            fontsize=13,
        )
    else:
        ax_big.text(
            0.5,
            0.32,
            "No previous session for comparison",
            ha="center",
            va="center",
            fontsize=13,
        )

    ax_bar.barh(muscles, ratings)
    ax_bar.set_title("Muscle group rating")
    ax_bar.set_xlabel("Score, 0–10")
    ax_bar.set_xlim(0, 10)
    ax_bar.invert_yaxis()
    ax_bar.grid(True, axis="x", alpha=0.3)

    if total_units > 0:
        ax_pie.pie(
            units,
            labels=muscles,
            autopct="%1.0f%%",
            startangle=90,
        )
        ax_pie.set_title("Share of score units")
    else:
        ax_pie.axis("off")
        ax_pie.text(
            0.5,
            0.5,
            "No score units",
            ha="center",
            va="center",
        )

    ax_line.plot(history_dates, history_scores, marker="o")
    ax_line.set_title("Session score trend")
    ax_line.set_xlabel("Training date")
    ax_line.set_ylabel("Score, 0–10")
    ax_line.set_ylim(0, 10.5)
    ax_line.tick_params(axis="x", rotation=45)
    ax_line.grid(True, alpha=0.3)

    fig.suptitle("Latest workout analytics", fontsize=16, fontweight="bold")
    fig.tight_layout()

    plt.savefig(output_path, dpi=150)
    plt.close(fig)

    return output_path
