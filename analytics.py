from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from statistics import mean, median
from typing import Any


DEFAULT_BODY_WEIGHT_KG = 75.0

# For weighted exercises, do NOT put default reference maxes here unless they are confirmed.
# If an exercise has no confirmed reference, the algorithm will infer it from the current session.
#
# Later this dictionary should move to DB:
# exercise_reference_values / exercise_reference_maxes.
CONFIRMED_REFERENCE_VALUES = {
    # Keep only values that are genuinely confirmed by prior data or manually accepted.
    # Weighted exercises not listed here will get provisional references from the current session.

    "bench_press": 65.0,
    "deadlift": 110.0,
    "squat": 60.0,
    "romanian_deadlift": 55.0,
    "barbell_row": 60.0,

    # Bodyweight / reps / static references.
    # For bodyweight exercises this means reference reps, not kilograms.
    "pullups": 10.0,
    "dips": 12.0,

    # For static exercises this means reference seconds.
    "plank": 60.0,

    # For reps-based core exercises this means reference reps per set.
    "crunches": 30.0,
    "russian_twist": 30.0,
    "leg_raise_elbows": 15.0,
    "incline_crunch": 30.0,
    "incline_crunch_side": 20.0,
}

EXERCISE_TYPES = {
    "bench_press": "weighted",
    "deadlift": "weighted",
    "squat": "weighted",
    "front_squat": "weighted",
    "romanian_deadlift": "weighted",
    "barbell_row": "weighted",
    "leg_press": "weighted",
    "standing_calf_raise": "weighted",
    "triceps_pushdown": "weighted",
    "barbell_curl": "weighted",
    "incline_db_press": "weighted",
    "rear_delt_fly": "weighted",
    "lateral_raises": "weighted",
    "kettlebell_shoulder_press": "weighted",

    "pullups": "bodyweight",
    "pull_ups": "bodyweight",
    "dips": "bodyweight",

    "plank": "static",
    "plank_elbows": "static",

    "crunches": "reps_based",
    "floor_crunch_with_ball": "reps_based",
    "russian_twist": "reps_based",
    "russian_twist_with_ball": "reps_based",
    "leg_raise_elbows": "reps_based",
    "incline_crunch": "reps_based",
    "incline_crunch_side": "reps_based",
}

MUSCLE_MAP = {
    "bench_press": {"chest": 1.0, "triceps": 0.45, "front_delts": 0.35},
    "incline_db_press": {"chest": 0.85, "front_delts": 0.45, "triceps": 0.25},

    "deadlift": {
        "posterior_chain": 1.0,
        "back": 0.7,
        "hamstrings": 0.7,
        "glutes": 0.7,
        "core": 0.35,
    },
    "romanian_deadlift": {
        "hamstrings": 1.0,
        "glutes": 0.75,
        "posterior_chain": 0.75,
        "back": 0.25,
    },
    "squat": {"quads": 1.0, "glutes": 0.65, "core": 0.25},
    "front_squat": {"quads": 1.0, "glutes": 0.45, "core": 0.35},
    "leg_press": {"quads": 1.0, "glutes": 0.45, "hamstrings": 0.20},
    "standing_calf_raise": {"calves": 1.0},

    "barbell_row": {"back": 1.0, "biceps": 0.35, "rear_delts": 0.25},
    "pullups": {"back": 1.0, "biceps": 0.55, "core": 0.20},
    "pull_ups": {"back": 1.0, "biceps": 0.55, "core": 0.20},

    "dips": {"chest": 0.75, "triceps": 1.0, "front_delts": 0.35},
    "triceps_pushdown": {"triceps": 1.0},
    "barbell_curl": {"biceps": 1.0},

    "kettlebell_shoulder_press": {"shoulders": 1.0, "front_delts": 0.65, "triceps": 0.25},
    "lateral_raises": {"side_delts": 1.0, "shoulders": 0.65},
    "rear_delt_fly": {"rear_delts": 1.0, "shoulders": 0.45},

    "plank": {"core": 1.0},
    "plank_elbows": {"core": 1.0},

    "crunches": {"core": 0.8},
    "floor_crunch_with_ball": {"core": 0.8},
    "russian_twist": {"core": 0.8, "obliques": 0.45},
    "russian_twist_with_ball": {"core": 0.8, "obliques": 0.45},
    "leg_raise_elbows": {"core": 1.0, "hip_flexors": 0.30},
    "incline_crunch": {"core": 0.85},
    "incline_crunch_side": {"core": 0.65, "obliques": 0.60},
}

# Units that roughly correspond to a solid 8/10 stimulus for one muscle group in one day.
TARGET_MUSCLE_UNITS = {
    "chest": 4.5,
    "back": 5.5,
    "quads": 5.0,
    "hamstrings": 4.5,
    "glutes": 4.5,
    "posterior_chain": 5.0,
    "triceps": 3.5,
    "biceps": 3.0,
    "front_delts": 3.0,
    "side_delts": 2.5,
    "rear_delts": 2.5,
    "shoulders": 4.0,
    "core": 4.0,
    "obliques": 2.5,
    "hip_flexors": 2.5,
    "calves": 4.5,
}

DEFAULT_TARGET_UNITS = 4.0

# A normal multi-set working load is assumed to be around 85% of technical/reference max.
# For a first session without history, this lets us infer a reference max from repeated working sets.
DEFAULT_WORKING_PERCENT = 0.85

# For classifying warm-up / working / heavy sets by weight inside the current exercise session.
WARMUP_RELATIVE_TO_TOP_THRESHOLD = 0.55
LIGHT_RELATIVE_TO_TOP_THRESHOLD = 0.70
HEAVY_RELATIVE_TO_TOP_THRESHOLD = 0.90


def normalize_exercise_name(name: str | None) -> str:
    if not name:
        return "unknown"

    normalized = name.strip().lower()
    normalized = normalized.replace("(", "").replace(")", "")
    normalized = normalized.replace("/", "_")
    normalized = normalized.replace("-", "_")
    normalized = normalized.replace(" ", "_")

    while "__" in normalized:
        normalized = normalized.replace("__", "_")

    return normalized.strip("_")


def to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default

    if isinstance(value, Decimal):
        return float(value)

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def to_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def epley_estimated_1rm(weight: float, reps: int) -> float:
    if weight <= 0 or reps <= 0:
        return 0.0

    return weight * (1 + reps / 30)


def infer_weighted_reference_from_current_session(rows_for_exercise: list[dict]) -> tuple[float, str]:
    """
    Infer initial reference max for a weighted exercise when there is no confirmed historical reference.

    Logic:
    1. If there is a clear heavy/top set: use estimated 1RM from that set.
    2. Otherwise, if there are repeated working weights: use median working weight / DEFAULT_WORKING_PERCENT.
    3. Otherwise, use the heaviest observed weight as a provisional reference.
    """

    weighted_rows = [
        row
        for row in rows_for_exercise
        if to_float(row.get("weight_kg")) > 0 and to_int(row.get("reps")) > 0
    ]

    if not weighted_rows:
        return 1.0, "fallback_no_weight"

    top_weight = max(to_float(row.get("weight_kg")) for row in weighted_rows)
    top_weight_rows = [
        row
        for row in weighted_rows
        if to_float(row.get("weight_kg")) == top_weight
    ]

    top_reps = max(to_int(row.get("reps")) for row in top_weight_rows)

    lower_weight_higher_rep_exists = any(
        to_float(row.get("weight_kg")) < top_weight
        and to_int(row.get("reps")) > top_reps
        for row in weighted_rows
    )

    # Clear top set: heavier weight, lower reps, usually 1-6 reps.
    if top_reps <= 6 and lower_weight_higher_rep_exists:
        return round(epley_estimated_1rm(top_weight, top_reps), 1), "provisional_top_set_e1rm"

    # Repeated working zone: use weights close enough to top weight.
    candidate_working_weights = [
        to_float(row.get("weight_kg"))
        for row in weighted_rows
        if to_float(row.get("weight_kg")) >= top_weight * LIGHT_RELATIVE_TO_TOP_THRESHOLD
        and to_int(row.get("reps")) >= 4
    ]

    if candidate_working_weights:
        working_weight = median(candidate_working_weights)
        inferred_reference = working_weight / DEFAULT_WORKING_PERCENT
        return round(inferred_reference, 1), "provisional_working_weight"

    return round(top_weight, 1), "provisional_top_weight"


def infer_reps_reference_from_current_session(rows_for_exercise: list[dict]) -> tuple[float, str]:
    reps_values = [
        to_int(row.get("reps"))
        for row in rows_for_exercise
        if to_int(row.get("reps")) > 0
    ]

    if not reps_values:
        return 1.0, "fallback_no_reps"

    return float(max(median(reps_values), 1)), "provisional_reps_median"


def infer_static_reference_from_current_session(rows_for_exercise: list[dict]) -> tuple[float, str]:
    duration_values = [
        to_int(row.get("duration_sec"))
        for row in rows_for_exercise
        if to_int(row.get("duration_sec")) > 0
    ]

    if not duration_values:
        return 1.0, "fallback_no_duration"

    return float(max(median(duration_values), 1)), "provisional_duration_median"


def get_reference_value(
    exercise: str,
    exercise_type: str,
    rows_for_exercise: list[dict],
) -> tuple[float, str]:
    if exercise in CONFIRMED_REFERENCE_VALUES:
        return CONFIRMED_REFERENCE_VALUES[exercise], "confirmed_manual"

    if exercise_type == "weighted":
        return infer_weighted_reference_from_current_session(rows_for_exercise)

    if exercise_type in {"bodyweight", "reps_based"}:
        return infer_reps_reference_from_current_session(rows_for_exercise)

    if exercise_type == "static":
        return infer_static_reference_from_current_session(rows_for_exercise)

    return infer_weighted_reference_from_current_session(rows_for_exercise)


def classify_weighted_set_by_top_weight(row: dict, top_weight: float) -> str:
    reps = to_int(row.get("reps"))
    weight = to_float(row.get("weight_kg"))

    if reps <= 0:
        return "invalid"

    if weight <= 0:
        return "warmup"

    if top_weight <= 0:
        return "unknown"

    relative_to_top = weight / top_weight

    if relative_to_top < WARMUP_RELATIVE_TO_TOP_THRESHOLD:
        return "warmup"

    if relative_to_top < LIGHT_RELATIVE_TO_TOP_THRESHOLD:
        return "light"

    if relative_to_top >= HEAVY_RELATIVE_TO_TOP_THRESHOLD:
        return "heavy"

    return "working"


def calculate_weighted_set_units(
    row: dict,
    reference_max: float,
    top_weight: float,
) -> tuple[float, float, bool, str]:
    reps = to_int(row.get("reps"))
    weight = to_float(row.get("weight_kg"))

    if reps <= 0 or weight <= 0 or reference_max <= 0:
        return 0.0, 0.0, False, "invalid"

    intensity = weight / reference_max
    set_class = classify_weighted_set_by_top_weight(row, top_weight)

    rep_factor = min(reps / 10, 1.35)
    intensity_factor = max(intensity, 0) ** 1.45

    # This is not based on notes.
    # A set is penalized only if it is much lighter than the top weight of the same exercise session
    # or if it is very light relative to reference max.
    relative_to_top = weight / top_weight if top_weight > 0 else 1.0

    light_penalty = 1.0
    if relative_to_top < WARMUP_RELATIVE_TO_TOP_THRESHOLD:
        light_penalty *= 0.35
    elif relative_to_top < LIGHT_RELATIVE_TO_TOP_THRESHOLD:
        light_penalty *= 0.70

    if intensity < 0.45:
        light_penalty *= 0.50

    working_set = (
        reps >= 4
        and intensity >= 0.55
        and relative_to_top >= LIGHT_RELATIVE_TO_TOP_THRESHOLD
    )

    units = intensity_factor * rep_factor * light_penalty

    return units, intensity, working_set, set_class


def calculate_bodyweight_set_units(
    row: dict,
    reference_reps: float,
) -> tuple[float, float, bool, str]:
    reps = to_int(row.get("reps"))
    added_weight = to_float(row.get("weight_kg"))

    if reps <= 0 or reference_reps <= 0:
        return 0.0, 0.0, False, "invalid"

    # For bodyweight exercises weight_kg is interpreted as added weight.
    # Later we may add assistance_kg as a separate DB column.
    # For now, negative weight_kg can represent assistance if you decide to log it that way.
    relative_load = max((DEFAULT_BODY_WEIGHT_KG + added_weight) / DEFAULT_BODY_WEIGHT_KG, 0.25)
    rep_factor = min(reps / reference_reps, 1.5)

    working_set = reps >= reference_reps * 0.55
    set_class = "working" if working_set else "light"

    if reps >= reference_reps * 0.90:
        set_class = "heavy"

    units = (relative_load ** 1.2) * rep_factor

    return units, relative_load, working_set, set_class


def calculate_static_set_units(
    row: dict,
    reference_seconds: float,
) -> tuple[float, float, bool, str]:
    duration = to_int(row.get("duration_sec"))

    if duration <= 0 or reference_seconds <= 0:
        return 0.0, 0.0, False, "invalid"

    duration_factor = min(duration / reference_seconds, 1.75)
    working_set = duration >= reference_seconds * 0.5

    if duration_factor >= 1.0:
        set_class = "heavy"
    elif working_set:
        set_class = "working"
    else:
        set_class = "light"

    units = duration_factor * 0.8

    return units, duration_factor, working_set, set_class


def calculate_reps_based_set_units(
    row: dict,
    reference_reps: float,
) -> tuple[float, float, bool, str]:
    reps = to_int(row.get("reps"))

    if reps <= 0 or reference_reps <= 0:
        return 0.0, 0.0, False, "invalid"

    rep_factor = min(reps / reference_reps, 1.75)
    working_set = reps >= reference_reps * 0.5

    if rep_factor >= 1.0:
        set_class = "heavy"
    elif working_set:
        set_class = "working"
    else:
        set_class = "light"

    units = rep_factor * 0.7

    return units, rep_factor, working_set, set_class


def rating_from_units(units: float, target_units: float) -> float:
    if target_units <= 0:
        target_units = DEFAULT_TARGET_UNITS

    # target_units is approximately 8/10.
    # 125% of target reaches 10/10.
    return round(min((units / target_units) * 8, 10), 1)


def calculate_algorithmic_effort_rating(
    exercise_units: float,
    target_units: float,
) -> int | None:
    """
    Internal algorithmic effort rating, not DB RPE.

    This is intentionally separate from the user's subjective RPE column.
    It can later be saved as algorithmic_rpe or effort_level if useful.
    """

    rating = rating_from_units(exercise_units, target_units)

    if rating <= 2:
        return 3
    if rating <= 4:
        return 5
    if rating <= 6:
        return 6
    if rating <= 8:
        return 7
    if rating <= 9:
        return 8

    return 9


def get_exercise_target_units(exercise_type: str, sets_count: int) -> float:
    """
    Exercise-level target for 8/10.

    This is still a temporary heuristic.
    Later it is better to move this to exercise-specific targets in DB.
    """

    if sets_count <= 0:
        return 3.0

    if exercise_type == "weighted":
        return max(3.0, sets_count * 0.95)

    if exercise_type == "bodyweight":
        return max(3.0, sets_count * 0.85)

    if exercise_type == "static":
        return max(2.5, sets_count * 0.80)

    if exercise_type == "reps_based":
        return max(2.5, sets_count * 0.75)

    return max(3.0, sets_count * 0.90)


def calculate_session_scores(rows: list[dict]) -> dict:
    if not rows:
        return {
            "date": None,
            "exercise_summary": [],
            "muscle_summary": [],
            "session_score": 0.0,
        }

    rows_by_exercise = defaultdict(list)

    for row in rows:
        exercise = normalize_exercise_name(row.get("exercise"))
        rows_by_exercise[exercise].append(dict(row))

    exercise_summary = []
    muscle_units = defaultdict(float)

    for exercise, exercise_rows in rows_by_exercise.items():
        exercise_type = EXERCISE_TYPES.get(exercise, "weighted")
        reference_value, reference_source = get_reference_value(
            exercise=exercise,
            exercise_type=exercise_type,
            rows_for_exercise=exercise_rows,
        )

        weighted_values = [
            to_float(row.get("weight_kg"))
            for row in exercise_rows
            if to_float(row.get("weight_kg")) > 0
        ]
        top_weight = max(weighted_values, default=0.0)

        set_units = []
        intensities_for_report = []
        working_weights = []
        set_classes = []

        total_reps = 0
        total_volume = 0.0
        max_weight = 0.0
        working_sets = 0
        heavy_sets = 0
        target_relevant_sets = 0
        best_estimated_1rm = 0.0

        for row in exercise_rows:
            reps = to_int(row.get("reps"))
            weight = to_float(row.get("weight_kg"))

            total_reps += reps
            total_volume += reps * weight
            max_weight = max(max_weight, weight)

            if exercise_type == "bodyweight":
                units, intensity, working_set, set_class = calculate_bodyweight_set_units(
                    row=row,
                    reference_reps=reference_value,
                )
            elif exercise_type == "static":
                units, intensity, working_set, set_class = calculate_static_set_units(
                    row=row,
                    reference_seconds=reference_value,
                )
            elif exercise_type == "reps_based":
                units, intensity, working_set, set_class = calculate_reps_based_set_units(
                    row=row,
                    reference_reps=reference_value,
                )
            else:
                units, intensity, working_set, set_class = calculate_weighted_set_units(
                    row=row,
                    reference_max=reference_value,
                    top_weight=top_weight,
                )

                if weight > 0 and reps > 0:
                    best_estimated_1rm = max(
                        best_estimated_1rm,
                        epley_estimated_1rm(weight, reps),
                    )

            set_units.append(units)
            set_classes.append(set_class)

            # Important:
            # avg_intensity should describe real work, not warm-up or invalid rows.
            if set_class in {"working", "heavy"} and intensity > 0:
                intensities_for_report.append(intensity)

            # Important:
            # target_units should be based only on sets that actually matter.
            # Warm-up / invalid rows should not make the exercise rating worse.
            if set_class in {"working", "heavy"}:
                target_relevant_sets += 1

            if working_set:
                working_sets += 1

                if exercise_type == "weighted" and weight > 0:
                    working_weights.append(weight)

            if set_class == "heavy":
                heavy_sets += 1

        exercise_units = round(sum(set_units), 2)
        working_weight = round(median(working_weights), 1) if working_weights else None
        avg_intensity = round(mean(intensities_for_report), 2) if intensities_for_report else 0.0

        muscle_distribution = MUSCLE_MAP.get(exercise)

        if not muscle_distribution:
            fallback_muscle = normalize_exercise_name(exercise_rows[0].get("category"))
            muscle_distribution = {fallback_muscle: 1.0}

        for muscle, share in muscle_distribution.items():
            muscle_units[muscle] += exercise_units * share

        # If there are working/heavy sets, use only them for target.
        # If not, fall back to total sets so that weird isolated data still produces a report.
        target_sets_count = target_relevant_sets if target_relevant_sets > 0 else len(exercise_rows)

        target_units = get_exercise_target_units(
            exercise_type=exercise_type,
            sets_count=target_sets_count,
        )

        exercise_rating = rating_from_units(exercise_units, target_units)
        algorithmic_effort = calculate_algorithmic_effort_rating(
            exercise_units=exercise_units,
            target_units=target_units,
        )

        exercise_summary.append(
            {
                "exercise": exercise,
                "type": exercise_type,
                "sets": len(exercise_rows),
                "working_sets": working_sets,
                "heavy_sets": heavy_sets,
                "target_sets": target_sets_count,
                "total_reps": total_reps,
                "total_volume": round(total_volume, 1),
                "max_weight": round(max_weight, 1),
                "reference_value": round(reference_value, 1),
                "reference_source": reference_source,
                "avg_intensity": avg_intensity,
                "working_weight": working_weight,
                "score_units": exercise_units,
                "target_units": round(target_units, 2),
                "rating_10": exercise_rating,
                "algorithmic_effort": algorithmic_effort,
                "best_estimated_1rm": round(best_estimated_1rm, 1) if best_estimated_1rm else None,
                "set_classes": set_classes,
            }
        )

    muscle_summary = []

    for muscle, units in sorted(muscle_units.items(), key=lambda item: item[1], reverse=True):
        target_units = TARGET_MUSCLE_UNITS.get(muscle, DEFAULT_TARGET_UNITS)

        muscle_summary.append(
            {
                "muscle": muscle,
                "score_units": round(units, 2),
                "target_units": target_units,
                "rating_10": rating_from_units(units, target_units),
            }
        )

    weighted_score_numerator = 0.0
    weighted_score_denominator = 0.0

    for row in muscle_summary:
        units = row["score_units"]
        target = row["target_units"]

        # Ignore tiny accidental traces.
        if units < target * 0.15:
            continue

        weighted_score_numerator += row["rating_10"] * units
        weighted_score_denominator += units

    session_score = (
        round(weighted_score_numerator / weighted_score_denominator, 1)
        if weighted_score_denominator > 0
        else 0.0
    )

    return {
        "date": rows[0].get("date"),
        "exercise_summary": exercise_summary,
        "muscle_summary": muscle_summary,
        "session_score": session_score,
    }


def format_session_score_report(result: dict) -> str:
    if not result or not result.get("exercise_summary"):
        return "Нет данных для расчёта score."

    lines = [
        f"Score тренировки за {result.get('date')}:",
        f"Итоговая оценка: {result.get('session_score')}/10",
        "",
        "По упражнениям:",
    ]

    for row in result["exercise_summary"]:
        working_weight = row["working_weight"] if row["working_weight"] is not None else "—"
        best_e1rm = row["best_estimated_1rm"] if row["best_estimated_1rm"] is not None else "—"

        lines.append(
            
            f"- {row['exercise']}: {row['rating_10']}/10 | "
            f"sets: {row['sets']} | target sets: {row.get('target_sets', row['sets'])} | "
            f"working sets: {row['working_sets']} | "
            f"heavy sets: {row['heavy_sets']} | "
            f"max: {row['max_weight']} | work weight: {working_weight} | "
            f"ref: {row['reference_value']} ({row['reference_source']}) | "
            f"avg intensity: {row['avg_intensity']} | "
            f"e1RM: {best_e1rm} | "
            f"units: {row['score_units']} | "
            f"algo effort: {row['algorithmic_effort']}"
        )

    lines.extend(["", "По мышечным группам:"])

    for row in result["muscle_summary"]:
        lines.append(
            f"- {row['muscle']}: {row['rating_10']}/10 | "
            f"units: {row['score_units']} / target: {row['target_units']}"
        )

    return "\n".join(lines)