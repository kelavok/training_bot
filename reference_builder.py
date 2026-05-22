from __future__ import annotations

from collections import defaultdict
from statistics import median

import analytics


def group_rows_by_exercise(rows: list[dict]) -> dict[str, list[dict]]:
    rows_by_exercise = defaultdict(list)

    for row in rows:
        exercise = analytics.normalize_exercise_name(row.get("exercise"))
        rows_by_exercise[exercise].append(dict(row))

    return dict(rows_by_exercise)


def group_rows_by_date(rows: list[dict]) -> dict:
    rows_by_date = defaultdict(list)

    for row in rows:
        rows_by_date[row.get("date")].append(row)

    return dict(rows_by_date)


def calculate_weighted_reference(exercise: str, rows: list[dict], user_id: int) -> dict:
    weighted_rows = [
        row
        for row in rows
        if analytics.to_float(row.get("weight_kg")) > 0
        and analytics.to_int(row.get("reps")) > 0
    ]

    best_top_weight = max(
        (analytics.to_float(row.get("weight_kg")) for row in weighted_rows),
        default=0.0,
    )
    best_e1rm = max(
        (
            analytics.epley_estimated_1rm(
                analytics.to_float(row.get("weight_kg")),
                analytics.to_int(row.get("reps")),
            )
            for row in weighted_rows
        ),
        default=0.0,
    )

    working_weights = []
    volume_by_date = defaultdict(float)

    for training_date, rows_for_date in group_rows_by_date(weighted_rows).items():
        top_weight_for_date = max(
            analytics.to_float(row.get("weight_kg"))
            for row in rows_for_date
        )

        for row in rows_for_date:
            reps = analytics.to_int(row.get("reps"))
            weight = analytics.to_float(row.get("weight_kg"))
            volume_by_date[training_date] += reps * weight

            if (
                reps >= 4
                and weight >= top_weight_for_date * analytics.LIGHT_RELATIVE_TO_TOP_THRESHOLD
            ):
                working_weights.append(weight)

    best_working_weight = max(working_weights, default=0.0)
    best_volume_day = max(volume_by_date.values(), default=0.0)

    reference_candidates = [
        value
        for value in [
            best_e1rm,
            best_working_weight / analytics.DEFAULT_WORKING_PERCENT
            if best_working_weight > 0
            else 0.0,
            best_top_weight,
        ]
        if value > 0
    ]
    reference_value = max(reference_candidates, default=1.0)

    return {
        "user_id": user_id,
        "exercise": exercise,
        "exercise_type": "weighted",
        "reference_value": round(reference_value, 2),
        "reference_source": "db_weighted_history",
        "best_e1rm": round(best_e1rm, 2) if best_e1rm else None,
        "best_working_weight": round(best_working_weight, 2) if best_working_weight else None,
        "best_volume_day": round(best_volume_day, 2) if best_volume_day else None,
        "best_reps_per_set": None,
        "best_duration_sec": None,
        "sample_sessions": len({
            row.get("date")
            for row in weighted_rows
            if row.get("date") is not None
        }),
    }


def calculate_reps_reference(
    exercise: str,
    rows: list[dict],
    exercise_type: str,
    user_id: int,
) -> dict:
    reps_by_date = defaultdict(list)

    for row in rows:
        reps = analytics.to_int(row.get("reps"))
        if reps > 0:
            reps_by_date[row.get("date")].append(reps)

    session_medians = [
        median(reps_values)
        for reps_values in reps_by_date.values()
        if reps_values
    ]
    best_reps_per_set = max(
        (max(reps_values) for reps_values in reps_by_date.values() if reps_values),
        default=0,
    )

    reference_value = max(session_medians, default=best_reps_per_set or 1)

    return {
        "user_id": user_id,
        "exercise": exercise,
        "exercise_type": exercise_type,
        "reference_value": round(float(reference_value), 2),
        "reference_source": "db_reps_history",
        "best_e1rm": None,
        "best_working_weight": None,
        "best_volume_day": None,
        "best_reps_per_set": round(float(best_reps_per_set), 2) if best_reps_per_set else None,
        "best_duration_sec": None,
        "sample_sessions": len([
            training_date
            for training_date, reps_values in reps_by_date.items()
            if training_date is not None and reps_values
        ]),
    }


def calculate_static_reference(exercise: str, rows: list[dict], user_id: int) -> dict:
    durations_by_date = defaultdict(list)

    for row in rows:
        duration = analytics.to_int(row.get("duration_sec"))
        if duration > 0:
            durations_by_date[row.get("date")].append(duration)

    session_medians = [
        median(duration_values)
        for duration_values in durations_by_date.values()
        if duration_values
    ]
    best_duration_sec = max(
        (
            max(duration_values)
            for duration_values in durations_by_date.values()
            if duration_values
        ),
        default=0,
    )

    reference_value = max(session_medians, default=best_duration_sec or 1)

    return {
        "user_id": user_id,
        "exercise": exercise,
        "exercise_type": "static",
        "reference_value": round(float(reference_value), 2),
        "reference_source": "db_static_history",
        "best_e1rm": None,
        "best_working_weight": None,
        "best_volume_day": None,
        "best_reps_per_set": None,
        "best_duration_sec": int(best_duration_sec) if best_duration_sec else None,
        "sample_sessions": len([
            training_date
            for training_date, duration_values in durations_by_date.items()
            if training_date is not None and duration_values
        ]),
    }


def build_reference_values_from_workouts(
    workout_rows: list[dict],
    user_id: int = 1,
) -> list[dict]:
    rows_by_exercise = group_rows_by_exercise(workout_rows)
    reference_rows = []

    for exercise, rows in sorted(rows_by_exercise.items()):
        exercise_type = analytics.EXERCISE_TYPES.get(exercise, "weighted")

        if exercise_type == "static":
            reference_row = calculate_static_reference(
                exercise=exercise,
                rows=rows,
                user_id=user_id,
            )
        elif exercise_type in {"bodyweight", "reps_based"}:
            reference_row = calculate_reps_reference(
                exercise=exercise,
                rows=rows,
                exercise_type=exercise_type,
                user_id=user_id,
            )
        else:
            reference_row = calculate_weighted_reference(
                exercise=exercise,
                rows=rows,
                user_id=user_id,
            )

        reference_rows.append(reference_row)

    return reference_rows
