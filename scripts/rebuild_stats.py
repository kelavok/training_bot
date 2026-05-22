from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

import db
import reference_service
import stats_builder


def main():
    print("Loading users with workouts...")
    user_ids = db.get_workout_user_ids()

    if not user_ids:
        print("No users with workouts found. Nothing to rebuild.")
        return

    print("Clearing old daily stats...")
    db.clear_daily_stats()

    total_exercise_rows = 0
    total_muscle_rows = 0

    for user_id in user_ids:
        print(f"Loading workouts for user {user_id}...")
        workout_rows = db.get_all_workouts(user_id=user_id)
        print(f"Loaded workout rows: {len(workout_rows)}")

        print(f"Loading reference values for user {user_id}...")
        reference_values = reference_service.get_reference_values(user_id=user_id)
        print(f"Loaded reference values: {len(reference_values)}")

        print(f"Building daily stats for user {user_id}...")
        daily_exercise_stats, daily_muscle_stats = stats_builder.build_daily_stats_from_workouts(
            workout_rows=workout_rows,
            user_id=user_id,
            reference_values=reference_values,
        )

        print(f"User {user_id} daily exercise stat rows: {len(daily_exercise_stats)}")
        print(f"User {user_id} daily muscle stat rows: {len(daily_muscle_stats)}")

        print(f"Inserting daily exercise stats for user {user_id}...")
        db.insert_daily_exercise_stats(daily_exercise_stats)

        print(f"Inserting daily muscle stats for user {user_id}...")
        db.insert_daily_muscle_stats(daily_muscle_stats)

        total_exercise_rows += len(daily_exercise_stats)
        total_muscle_rows += len(daily_muscle_stats)

    print(f"Daily exercise stat rows total: {total_exercise_rows}")
    print(f"Daily muscle stat rows total: {total_muscle_rows}")
    print("Done. Daily stats rebuilt for all users.")


if __name__ == "__main__":
    main()
