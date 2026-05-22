from __future__ import annotations

from collections import defaultdict

import analytics


def group_rows_by_date(rows: list[dict]) -> dict:
    rows_by_date = defaultdict(list)

    for row in rows:
        rows_by_date[row["date"]].append(row)

    return dict(rows_by_date)


def calculate_total_duration_for_exercise(rows_for_exercise: list[dict]) -> int:
    total_duration = 0

    for row in rows_for_exercise:
        duration = row.get("duration_sec")

        if duration is None:
            continue

        total_duration += int(duration)

    return total_duration


def build_daily_stats_from_workouts(
    workout_rows: list[dict],
    user_id: int = 1,
    reference_values: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    rows_by_date = group_rows_by_date(workout_rows)

    daily_exercise_stats = []
    daily_muscle_stats = []

    for training_date, rows_for_date in rows_by_date.items():
        result = analytics.calculate_session_scores(
            rows_for_date,
            reference_values=reference_values,
        )

        rows_by_normalized_exercise = defaultdict(list)

        for row in rows_for_date:
            normalized_exercise = analytics.normalize_exercise_name(row.get("exercise"))
            rows_by_normalized_exercise[normalized_exercise].append(row)

        for exercise_row in result["exercise_summary"]:
            exercise = exercise_row["exercise"]
            source_rows = rows_by_normalized_exercise.get(exercise, [])

            daily_exercise_stats.append(
                {
                    "user_id": user_id,
                    "date": training_date,
                    "exercise": exercise,
                    "exercise_type": exercise_row.get("type"),
                    "sets": exercise_row.get("sets"),
                    "working_sets": exercise_row.get("working_sets"),
                    "heavy_sets": exercise_row.get("heavy_sets"),
                    "target_sets": exercise_row.get("target_sets"),
                    "total_reps": exercise_row.get("total_reps"),
                    "total_duration_sec": calculate_total_duration_for_exercise(source_rows),
                    "total_volume": exercise_row.get("total_volume"),
                    "max_weight": exercise_row.get("max_weight"),
                    "working_weight": exercise_row.get("working_weight"),
                    "best_estimated_1rm": exercise_row.get("best_estimated_1rm"),
                    "avg_intensity": exercise_row.get("avg_intensity"),
                    "score_units": exercise_row.get("score_units"),
                    "target_units": exercise_row.get("target_units"),
                    "rating_10": exercise_row.get("rating_10"),
                    "algorithmic_effort": exercise_row.get("algorithmic_effort"),
                }
            )

        for muscle_row in result["muscle_summary"]:
            daily_muscle_stats.append(
                {
                    "user_id": user_id,
                    "date": training_date,
                    "muscle": muscle_row.get("muscle"),
                    "score_units": muscle_row.get("score_units"),
                    "target_units": muscle_row.get("target_units"),
                    "rating_10": muscle_row.get("rating_10"),
                }
            )

    return daily_exercise_stats, daily_muscle_stats
