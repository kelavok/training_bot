from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

import analytics
import db


PERIOD_ALIASES = {
    "7": "7d",
    "7d": "7d",
    "week": "7d",
    "неделя": "7d",
    "30": "30d",
    "30d": "30d",
    "month": "30d",
    "месяц": "30d",
    "90": "90d",
    "90d": "90d",
    "quarter": "90d",
    "квартал": "90d",
    "all": "all",
    "все": "all",
    "всё": "all",
}


@dataclass(frozen=True)
class Period:
    token: str
    label: str
    start_date: date | None
    end_date: date | None


def normalize_period_token(token: str | None) -> str:
    if not token:
        return "30d"

    normalized = token.strip().lower()
    return PERIOD_ALIASES.get(normalized, normalized)


def is_period_token(token: str | None) -> bool:
    if not token:
        return False

    normalized = normalize_period_token(token)

    return (
        normalized in {"7d", "30d", "90d", "all"}
        or (normalized.endswith("d") and normalized[:-1].isdigit())
        or (len(normalized) == 7 and normalized[4] == "-")
    )


def resolve_period(token: str | None = None, user_id: int = 1) -> Period:
    normalized = normalize_period_token(token)
    basic = db.get_basic_stats_for_period(user_id=user_id)
    latest_date = basic["last_date"] or date.today()

    if normalized == "all":
        return Period(
            token="all",
            label="все время",
            start_date=None,
            end_date=latest_date,
        )

    if normalized.endswith("d"):
        try:
            days = int(normalized[:-1])
        except ValueError:
            days = 30

        return Period(
            token=f"{days}d",
            label=f"{days} дней",
            start_date=latest_date - timedelta(days=days - 1),
            end_date=latest_date,
        )

    if len(normalized) == 7 and normalized[4] == "-":
        try:
            year, month = normalized.split("-")
            start_date = date(int(year), int(month), 1)
        except ValueError:
            return resolve_period("30d", user_id=user_id)

        if start_date.month == 12:
            next_month = date(start_date.year + 1, 1, 1)
        else:
            next_month = date(start_date.year, start_date.month + 1, 1)

        return Period(
            token=normalized,
            label=normalized,
            start_date=start_date,
            end_date=next_month - timedelta(days=1),
        )

    return resolve_period("30d", user_id=user_id)


def split_period_arg(args: list[str]) -> tuple[list[str], str]:
    if not args:
        return [], "30d"

    possible_period = normalize_period_token(args[-1])

    if is_period_token(possible_period):
        return args[:-1], possible_period

    return args, "30d"


def to_float(value, default: float = 0.0) -> float:
    return analytics.to_float(value, default=default)


def avg(values: list[float]) -> float:
    if not values:
        return 0.0

    return sum(values) / len(values)


def build_overview(period_token: str | None = None, user_id: int = 1) -> dict:
    period = resolve_period(period_token, user_id=user_id)
    basic = db.get_basic_stats_for_period(
        user_id=user_id,
        start_date=period.start_date,
        end_date=period.end_date,
    )
    exercise_rows = db.get_exercise_stats_for_period(
        user_id=user_id,
        start_date=period.start_date,
        end_date=period.end_date,
    )
    muscle_rows = db.get_muscle_stats_for_period(
        user_id=user_id,
        start_date=period.start_date,
        end_date=period.end_date,
    )

    return {
        "period": period,
        "basic": dict(basic),
        "top_exercises": aggregate_top_exercises(exercise_rows, metric="score_units", limit=5),
        "top_muscles": aggregate_top_muscles(muscle_rows, metric="score_units", limit=5),
        "avg_exercise_rating": avg([
            to_float(row["rating_10"])
            for row in exercise_rows
            if row["rating_10"] is not None
        ]),
        "working_sets": sum(row["working_sets"] or 0 for row in exercise_rows),
        "heavy_sets": sum(row["heavy_sets"] or 0 for row in exercise_rows),
    }


def aggregate_top_exercises(
    rows,
    metric: str = "score_units",
    limit: int = 10,
) -> list[dict]:
    grouped = defaultdict(list)

    for row in rows:
        grouped[row["exercise"]].append(row)

    summaries = []

    for exercise, exercise_rows in grouped.items():
        total_volume = sum(to_float(row["total_volume"]) for row in exercise_rows)
        score_units = sum(to_float(row["score_units"]) for row in exercise_rows)
        best_e1rm = max(
            (to_float(row["best_estimated_1rm"]) for row in exercise_rows),
            default=0.0,
        )
        best_working_weight = max(
            (to_float(row["working_weight"]) for row in exercise_rows),
            default=0.0,
        )

        summary = {
            "exercise": exercise,
            "sessions": len(exercise_rows),
            "sets": sum(row["sets"] or 0 for row in exercise_rows),
            "working_sets": sum(row["working_sets"] or 0 for row in exercise_rows),
            "heavy_sets": sum(row["heavy_sets"] or 0 for row in exercise_rows),
            "total_reps": sum(row["total_reps"] or 0 for row in exercise_rows),
            "total_volume": total_volume,
            "score_units": score_units,
            "avg_rating": avg([
                to_float(row["rating_10"])
                for row in exercise_rows
                if row["rating_10"] is not None
            ]),
            "best_e1rm": best_e1rm,
            "best_working_weight": best_working_weight,
            "last_date": max(row["date"] for row in exercise_rows),
        }
        summary["metric_value"] = summary.get(metric, score_units)
        summaries.append(summary)

    return sorted(
        summaries,
        key=lambda row: row.get("metric_value") or 0,
        reverse=True,
    )[:limit]


def aggregate_top_muscles(rows, metric: str = "score_units", limit: int = 10) -> list[dict]:
    grouped = defaultdict(list)

    for row in rows:
        grouped[row["muscle"]].append(row)

    summaries = []

    for muscle, muscle_rows in grouped.items():
        score_units = sum(to_float(row["score_units"]) for row in muscle_rows)
        avg_rating = avg([
            to_float(row["rating_10"])
            for row in muscle_rows
            if row["rating_10"] is not None
        ])
        best_rating = max(
            (to_float(row["rating_10"]) for row in muscle_rows),
            default=0.0,
        )

        summary = {
            "muscle": muscle,
            "days": len(muscle_rows),
            "score_units": score_units,
            "avg_rating": avg_rating,
            "best_rating": best_rating,
            "last_date": max(row["date"] for row in muscle_rows),
        }
        summary["metric_value"] = summary.get(metric, score_units)
        summaries.append(summary)

    return sorted(
        summaries,
        key=lambda row: row.get("metric_value") or 0,
        reverse=True,
    )[:limit]


def build_top_exercises(
    period_token: str | None = None,
    metric: str = "score_units",
    limit: int = 10,
    user_id: int = 1,
) -> dict:
    period = resolve_period(period_token, user_id=user_id)
    rows = db.get_exercise_stats_for_period(
        user_id=user_id,
        start_date=period.start_date,
        end_date=period.end_date,
    )

    return {
        "period": period,
        "metric": metric,
        "rows": aggregate_top_exercises(rows, metric=metric, limit=limit),
    }


def build_top_muscles(
    period_token: str | None = None,
    metric: str = "score_units",
    limit: int = 10,
    user_id: int = 1,
) -> dict:
    period = resolve_period(period_token, user_id=user_id)
    rows = db.get_muscle_stats_for_period(
        user_id=user_id,
        start_date=period.start_date,
        end_date=period.end_date,
    )

    return {
        "period": period,
        "metric": metric,
        "rows": aggregate_top_muscles(rows, metric=metric, limit=limit),
    }


def build_exercise_detail(
    exercise_input: str,
    period_token: str | None = None,
    user_id: int = 1,
) -> dict:
    exercise = analytics.normalize_exercise_name(exercise_input)
    period = resolve_period(period_token, user_id=user_id)
    rows = db.get_exercise_stats_for_period(
        user_id=user_id,
        start_date=period.start_date,
        end_date=period.end_date,
        exercise=exercise,
    )
    references = db.get_exercise_reference_values(user_id=user_id)
    reference = references.get(exercise)

    return {
        "period": period,
        "exercise": exercise,
        "rows": [dict(row) for row in rows],
        "reference": reference,
    }


def build_muscle_detail(
    muscle_input: str,
    period_token: str | None = None,
    user_id: int = 1,
) -> dict:
    muscle = analytics.normalize_exercise_name(muscle_input)
    period = resolve_period(period_token, user_id=user_id)
    rows = db.get_muscle_stats_for_period(
        user_id=user_id,
        start_date=period.start_date,
        end_date=period.end_date,
        muscle=muscle,
    )

    return {
        "period": period,
        "muscle": muscle,
        "rows": [dict(row) for row in rows],
    }
