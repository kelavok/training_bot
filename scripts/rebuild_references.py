from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

import reference_service


def main():
    print("Rebuilding exercise reference values...")
    rows_count = reference_service.rebuild_all_references(user_id=1)
    print(f"Reference rows rebuilt: {rows_count}")
    print("Done. Exercise reference values rebuilt.")


if __name__ == "__main__":
    main()
