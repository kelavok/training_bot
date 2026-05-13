from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any
from difflib import get_close_matches

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL


ALLOWED_FIELDS = {
    "user_id",
    "date",
    "exercise",
    "category",
    "reps",
    "weight_kg",
    "rest_sec_after",
    "duration_sec",
    "rpe",
    "notes",
}


SYSTEM_INSTRUCTIONS = """
You convert free-form workout notes into structured rows for a PostgreSQL table named workouts.

Return only valid JSON. No markdown. No comments.

The database table is workouts with these fields:
user_id: integer, required
date: string in YYYY-MM-DD format, required
exercise: string, required
category: string or null
reps: integer or null
weight_kg: number or null
rest_sec_after: integer or null
duration_sec: integer or null
rpe: integer or null
notes: string or null

Rules:
1. Return a JSON object with key "rows".
2. "rows" must be a list of set-level rows.
3. One set = one row.
4. Do not include id. PostgreSQL generates it automatically.
5. If date is not explicitly provided by the user, use the provided default_date.
6. If user gives one rest value for an exercise, apply it to all sets of that exercise.
7. If rest is not provided, use null.
8. If duration is not relevant or missing, use 0.
9. If weight is bodyweight or no added weight, use 0.
10. Preserve exercise names in readable English Title Case, for example "Bench Press", "Romanian Deadlift", "Pull-ups".
11. Use simple categories: chest, back, legs, shoulders, biceps, triceps, core, calves, glutes, hamstrings, quads.
12. Do not invent sets, weights, reps, RPE, rest, or duration that the user did not describe.
13. If something is uncertain, put the uncertainty in notes.
14. If the user says warm-up, разминка, разминочный, разминочная, put "warm-up" in notes.
15. For static exercises like plank, reps must be 0, weight_kg must be 0, duration_sec must contain seconds.
16. Interpret Russian workout shorthand like "50 на 10", "50х10", "50 x 10" as weight_kg 50 and reps 10.
17. Interpret "3 по 30" or "3x30" for bodyweight/core reps as 3 rows with reps 30 and weight_kg 0, unless weight is explicitly given.
18. If the user writes "по 6 кг" for dumbbells, use weight_kg = 6, not 12, unless the user explicitly says total weight.
19. For unilateral exercises such as one-arm dumbbell row, dumbbell lunge, single-arm movements, or exercises described as "на каждую", "each side", or "per side", do NOT duplicate rows for left and right side. One described set equals one database row. Put "each side" in notes if useful.
20. You will receive existing_exercises, a list of exercise names already present in the database.
21. If the user's exercise clearly matches one of existing_exercises by meaning, use the exact existing database name.
22. Do not create a new synonym if a matching exercise already exists.
23. If several existing exercises are possible and the user's wording is ambiguous, do not guess.
24. Example: if existing_exercises contains "Back Squat" and "Front Squat", and the user writes "front squat" or "фронтальный присед", return "Front Squat".
25. Example: if existing_exercises contains "Back Squat" and "Front Squat", and the user writes "back squat", "присед со штангой на спине", or clearly describes a back squat, return "Back Squat".
26. Example: if existing_exercises contains "Back Squat" and "Front Squat", and the user only writes "squat" or "присед", return "Squat" and put "uncertain exercise variant" in notes.


"""


def get_client() -> genai.Client:
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set in .env")

    return genai.Client(api_key=GEMINI_API_KEY)


def extract_json_object(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")

        if start == -1 or end == -1 or end <= start:
            raise ValueError("Gemini response does not contain valid JSON.")

        return json.loads(text[start:end + 1])


def normalize_date(value: Any, default_date: date) -> str:
    if not value:
        return default_date.isoformat()

    if isinstance(value, date):
        return value.isoformat()

    value_str = str(value).strip()

    if not value_str:
        return default_date.isoformat()

    try:
        return datetime.strptime(value_str, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return default_date.isoformat()


def to_int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_exercise_for_matching(name: str) -> str:
    normalized = name.strip().lower()

    replacements = {
        "-": " ",
        "_": " ",
        "ё": "е",
    }

    for old, new in replacements.items():
        normalized = normalized.replace(old, new)

    while "  " in normalized:
        normalized = normalized.replace("  ", " ")

    return normalized.strip()


def match_existing_exercise_name(
    parsed_name: str,
    existing_exercises: list[str] | None,
) -> str:
    if not existing_exercises:
        return parsed_name

    parsed_clean = normalize_exercise_for_matching(parsed_name)

    normalized_map = {
        normalize_exercise_for_matching(existing): existing
        for existing in existing_exercises
    }

    if parsed_clean in normalized_map:
        return normalized_map[parsed_clean]

    close_matches = get_close_matches(
        parsed_clean,
        normalized_map.keys(),
        n=1,
        cutoff=0.92,
    )

    if close_matches:
        return normalized_map[close_matches[0]]

    return parsed_name

def normalize_row(
    row: dict,
    default_date: date,
    user_id: int = 1,
    existing_exercises: list[str] | None = None,
) -> dict:
    cleaned = {key: row.get(key) for key in ALLOWED_FIELDS}

    cleaned["user_id"] = user_id
    cleaned["date"] = normalize_date(cleaned.get("date"), default_date)

    exercise = cleaned.get("exercise")

    if not exercise or not str(exercise).strip():
        raise ValueError("Parsed row has empty exercise.")

    parsed_exercise = str(exercise).strip()

    cleaned["exercise"] = match_existing_exercise_name(


        parsed_name=parsed_exercise,
        existing_exercises=existing_exercises,
    )

    category = cleaned.get("category")
    cleaned["category"] = str(category).strip().lower() if category else None

    cleaned["reps"] = to_int_or_none(cleaned.get("reps"))
    cleaned["weight_kg"] = to_float_or_none(cleaned.get("weight_kg"))
    cleaned["rest_sec_after"] = to_int_or_none(cleaned.get("rest_sec_after"))
    cleaned["duration_sec"] = to_int_or_none(cleaned.get("duration_sec"))
    cleaned["rpe"] = to_int_or_none(cleaned.get("rpe"))

    notes = cleaned.get("notes")
    cleaned["notes"] = str(notes).strip() if notes else None

    if cleaned["reps"] is None:
        cleaned["reps"] = 0

    if cleaned["weight_kg"] is None:
        cleaned["weight_kg"] = 0

    if cleaned["duration_sec"] is None:
        cleaned["duration_sec"] = 0

    return cleaned


def parse_workout_with_gemini(
    text: str,
    default_date: date | None = None,
    user_id: int = 1,
    existing_exercises: list[str] | None = None,
) -> list[dict]:
    if default_date is None:
        default_date = date.today()

    client = get_client()

    prompt_payload = {
        "default_date": default_date.isoformat(),
        "user_id": user_id,
        "existing_exercises": existing_exercises or [],
        "workout_text": text,
    }

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=json.dumps(prompt_payload, ensure_ascii=False),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTIONS,
            temperature=0,
            response_mime_type="application/json",
        ),
    )

    parsed = extract_json_object(response.text)
    rows_raw = parsed.get("rows")

    if not isinstance(rows_raw, list):
        raise ValueError("Gemini response must contain a list under key 'rows'.")

    rows = [
    normalize_row(
        row,
        default_date=default_date,
        user_id=user_id,
        existing_exercises=existing_exercises,
    )
    for row in rows_raw
    ]

    if not rows:
        raise ValueError("Gemini returned zero workout rows.")

    return rows