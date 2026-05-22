from __future__ import annotations

import analytics
import db
import reference_builder


def rebuild_all_references(user_id: int = 1) -> int:
    workout_rows = db.get_all_workouts(user_id=user_id)

    db.create_exercise_reference_values_table()
    db.clear_exercise_reference_values(user_id=user_id)

    if not workout_rows:
        return 0

    reference_rows = reference_builder.build_reference_values_from_workouts(
        workout_rows=workout_rows,
        user_id=user_id,
    )
    db.insert_exercise_reference_values(reference_rows)

    return len(reference_rows)


def rebuild_references_for_exercises(
    exercise_keys,
    user_id: int = 1,
) -> int:
    # MVP: history is small, so rebuild all references to keep cross-date scoring consistent.
    return rebuild_all_references(user_id=user_id)


def get_reference_values(user_id: int = 1) -> dict:
    db.create_exercise_reference_values_table()
    reference_values = db.get_exercise_reference_values(user_id=user_id)

    return {
        analytics.normalize_exercise_name(exercise): row
        for exercise, row in reference_values.items()
    }
