from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

import db
import stats_builder


def main():
    print("Loading workouts...")
    workout_rows = db.get_all_workouts()

    if not workout_rows:
        print("No workouts found. Nothing to rebuild.")
        return

    print(f"Loaded workout rows: {len(workout_rows)}")

    print("Building daily stats...")
    daily_exercise_stats, daily_muscle_stats = stats_builder.build_daily_stats_from_workouts(
        workout_rows=workout_rows,
        user_id=1,
    )

    print(f"Daily exercise stat rows: {len(daily_exercise_stats)}")
    print(f"Daily muscle stat rows: {len(daily_muscle_stats)}")

    print("Clearing old daily stats...")
    db.clear_daily_stats()

    print("Inserting daily exercise stats...")
    db.insert_daily_exercise_stats(daily_exercise_stats)

    print("Inserting daily muscle stats...")
    db.insert_daily_muscle_stats(daily_muscle_stats)

    print("Done. Daily stats rebuilt.")


if __name__ == "__main__":
    main()