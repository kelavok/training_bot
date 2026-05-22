from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

import reference_service
import db


def main():
    print("Rebuilding exercise reference values...")
    user_ids = db.get_workout_user_ids()

    if not user_ids:
        print("No users with workouts found. Nothing to rebuild.")
        return

    total_rows_count = 0

    for user_id in user_ids:
        rows_count = reference_service.rebuild_all_references(user_id=user_id)
        total_rows_count += rows_count
        print(f"User {user_id}: reference rows rebuilt: {rows_count}")

    print(f"Reference rows rebuilt total: {total_rows_count}")
    print("Done. Exercise reference values rebuilt.")


if __name__ == "__main__":
    main()
