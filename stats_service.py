from __future__ import annotations

import db
import stats_builder


def rebuild_stats_for_date(training_date, user_id: int = 1) -> tuple[int, int]:
    workout_rows = db.get_workouts_by_date(training_date)

    db.clear_daily_stats_for_date(training_date)

    if not workout_rows:
        return 0, 0

    daily_exercise_stats, daily_muscle_stats = stats_builder.build_daily_stats_from_workouts(
        workout_rows=workout_rows,
        user_id=user_id,
    )

    db.insert_daily_exercise_stats(daily_exercise_stats)
    db.insert_daily_muscle_stats(daily_muscle_stats)

    return len(daily_exercise_stats), len(daily_muscle_stats)


def rebuild_stats_for_dates(training_dates, user_id: int = 1) -> dict:
    result = {}

    for training_date in sorted(set(training_dates)):
        exercise_count, muscle_count = rebuild_stats_for_date(
            training_date=training_date,
            user_id=user_id,
        )

        result[str(training_date)] = {
            "exercise_stats": exercise_count,
            "muscle_stats": muscle_count,
        }

    return result
