from __future__ import annotations

import analytics


METRIC_LABELS = {
    "score_units": "score units",
    "total_volume": "volume",
    "avg_rating": "avg score",
    "best_e1rm": "best e1RM",
    "best_working_weight": "best working weight",
    "sets": "sets",
    "working_sets": "working sets",
    "heavy_sets": "heavy sets",
}


def fmt_float(value, digits: int = 1) -> str:
    return f"{analytics.to_float(value):.{digits}f}"


def format_period(period) -> str:
    if period.start_date is None:
        return f"{period.label} до {period.end_date}"

    return f"{period.label}: {period.start_date} - {period.end_date}"


def format_metric_value(row: dict, metric: str) -> str:
    value = row.get(metric, row.get("metric_value"))

    if metric in {"sets", "working_sets", "heavy_sets"}:
        return str(int(value or 0))

    if metric in {"total_volume"}:
        return f"{fmt_float(value)} kg"

    if metric in {"best_e1rm", "best_working_weight"}:
        return f"{fmt_float(value)} kg"

    if metric == "avg_rating":
        return f"{fmt_float(value)}/10"

    return fmt_float(value, digits=2)


def format_stats_help() -> str:
    return (
        "Команды статистики:\n\n"
        "/stats [7d|30d|90d|all|YYYY-MM] - обзор периода\n"
        "/top exercises [metric] [period] [limit] - топ упражнений\n"
        "/top muscles [metric] [period] [limit] - топ мышц\n"
        "/exercise bench_press [period] - упражнение\n"
        "/muscle back [period] - мышечная группа\n\n"
        "Метрики для /top exercises:\n"
        "score_units, total_volume, avg_rating, best_e1rm, "
        "best_working_weight, sets, working_sets, heavy_sets\n\n"
        "Метрики для /top muscles:\n"
        "score_units, avg_rating, best_rating\n\n"
        "Примеры:\n"
        "/stats 30d\n"
        "/top exercises best_e1rm all 10\n"
        "/top muscles score_units 90d\n"
        "/exercise bench_press 90d\n"
        "/muscle chest 30d"
    )


def format_overview(data: dict) -> str:
    period = data["period"]
    basic = data["basic"]

    lines = [
        f"Обзор за период: {format_period(period)}",
        "",
        f"Тренировочных дней: {basic['training_days']}",
        f"Упражнений: {basic['unique_exercises']}",
        f"Подходов: {basic['total_sets']}",
        f"Рабочих подходов: {data['working_sets']}",
        f"Heavy sets: {data['heavy_sets']}",
        f"Повторений: {basic['total_reps']}",
        f"Общий volume: {fmt_float(basic['total_volume'])} kg",
        f"Средний score упражнений: {fmt_float(data['avg_exercise_rating'])}/10",
        "",
        "Топ мышц по score units:",
    ]

    if data["top_muscles"]:
        for index, row in enumerate(data["top_muscles"], start=1):
            lines.append(
                f"{index}. {row['muscle']} - "
                f"{fmt_float(row['score_units'], 2)} units, "
                f"avg {fmt_float(row['avg_rating'])}/10"
            )
    else:
        lines.append("Нет данных.")

    lines.extend(["", "Топ упражнений по score units:"])

    if data["top_exercises"]:
        for index, row in enumerate(data["top_exercises"], start=1):
            lines.append(
                f"{index}. {row['exercise']} - "
                f"{fmt_float(row['score_units'], 2)} units, "
                f"avg {fmt_float(row['avg_rating'])}/10"
            )
    else:
        lines.append("Нет данных.")

    lines.extend([
        "",
        "Подсказка: /stats help покажет фильтры и примеры.",
    ])

    return "\n".join(lines)


def format_top_exercises(data: dict) -> str:
    period = data["period"]
    metric = data["metric"]
    metric_label = METRIC_LABELS.get(metric, metric)

    lines = [
        f"Топ упражнений за период: {format_period(period)}",
        f"Метрика: {metric_label}",
        "",
    ]

    if not data["rows"]:
        lines.append("Нет данных за этот период.")
        return "\n".join(lines)

    for index, row in enumerate(data["rows"], start=1):
        lines.append(
            f"{index}. {row['exercise']} - {format_metric_value(row, metric)} | "
            f"days: {row['sessions']} | score: {fmt_float(row['avg_rating'])}/10 | "
            f"sets: {row['sets']}"
        )

    return "\n".join(lines)


def format_top_muscles(data: dict) -> str:
    period = data["period"]
    metric = data["metric"]
    metric_label = METRIC_LABELS.get(metric, metric)

    lines = [
        f"Топ мышц за период: {format_period(period)}",
        f"Метрика: {metric_label}",
        "",
    ]

    if not data["rows"]:
        lines.append("Нет данных за этот период.")
        return "\n".join(lines)

    for index, row in enumerate(data["rows"], start=1):
        lines.append(
            f"{index}. {row['muscle']} - {format_metric_value(row, metric)} | "
            f"days: {row['days']} | avg: {fmt_float(row['avg_rating'])}/10 | "
            f"best: {fmt_float(row['best_rating'])}/10"
        )

    return "\n".join(lines)


def format_exercise_detail(data: dict) -> str:
    rows = data["rows"]
    exercise = data["exercise"]
    period = data["period"]
    reference = data["reference"]

    if not rows:
        return f"Нет агрегатов по упражнению {exercise} за период {format_period(period)}."

    latest = rows[-1]
    total_sessions = len(rows)
    total_sets = sum(row["sets"] or 0 for row in rows)
    working_sets = sum(row["working_sets"] or 0 for row in rows)
    heavy_sets = sum(row["heavy_sets"] or 0 for row in rows)
    total_reps = sum(row["total_reps"] or 0 for row in rows)
    total_volume = sum(analytics.to_float(row["total_volume"]) for row in rows)
    max_weight = max((analytics.to_float(row["max_weight"]) for row in rows), default=0.0)
    score_units = sum(analytics.to_float(row["score_units"]) for row in rows)
    avg_rating = sum(analytics.to_float(row["rating_10"]) for row in rows) / total_sessions

    working_weights = [
        analytics.to_float(row["working_weight"])
        for row in rows
        if row["working_weight"] is not None
    ]
    best_working_weight = max(working_weights) if working_weights else None

    e1rm_values = [
        analytics.to_float(row["best_estimated_1rm"])
        for row in rows
        if row["best_estimated_1rm"] is not None
    ]
    best_e1rm = max(e1rm_values) if e1rm_values else None

    lines = [
        f"{exercise} за период: {format_period(period)}",
        "",
        f"Тренировочных дней: {total_sessions}",
        f"Последняя дата: {latest['date']}",
        f"Подходов: {total_sets}",
        f"Рабочих подходов: {working_sets}",
        f"Heavy sets: {heavy_sets}",
        f"Повторений: {total_reps}",
        f"Volume: {total_volume:.1f} kg",
        f"Score units: {score_units:.2f}",
        f"Средний score: {avg_rating:.1f}/10",
        f"Максимальный вес: {max_weight:.1f} kg",
    ]

    if best_working_weight is not None:
        lines.append(f"Лучший рабочий вес: {best_working_weight:.1f} kg")

    if best_e1rm is not None:
        lines.append(f"Лучший e1RM: {best_e1rm:.1f} kg")

    if reference:
        lines.append(
            f"Reference: {fmt_float(reference['reference_value'])} "
            f"({reference['reference_source']})"
        )

    lines.extend(["", "Последние дни:"])

    for row in rows[-5:]:
        details = [
            f"{row['date']}",
            f"{fmt_float(row['rating_10'])}/10",
            f"{fmt_float(row['score_units'], 2)} units",
            f"{row['sets']} sets",
        ]

        if row["working_weight"] is not None:
            details.append(f"work {fmt_float(row['working_weight'])} kg")

        if row["best_estimated_1rm"] is not None:
            details.append(f"e1RM {fmt_float(row['best_estimated_1rm'])}")

        lines.append(" - " + " | ".join(details))

    return "\n".join(lines)


def format_muscle_detail(data: dict) -> str:
    rows = data["rows"]
    muscle = data["muscle"]
    period = data["period"]

    if not rows:
        return f"Нет агрегатов по мышце {muscle} за период {format_period(period)}."

    total_days = len(rows)
    score_units = sum(analytics.to_float(row["score_units"]) for row in rows)
    avg_rating = sum(analytics.to_float(row["rating_10"]) for row in rows) / total_days
    best_row = max(rows, key=lambda row: analytics.to_float(row["rating_10"]))

    lines = [
        f"{muscle} за период: {format_period(period)}",
        "",
        f"Тренировочных дней: {total_days}",
        f"Score units: {score_units:.2f}",
        f"Средний score: {avg_rating:.1f}/10",
        f"Лучший день: {best_row['date']} - {fmt_float(best_row['rating_10'])}/10",
        "",
        "Последние дни:",
    ]

    for row in rows[-7:]:
        lines.append(
            f" - {row['date']} | {fmt_float(row['rating_10'])}/10 | "
            f"{fmt_float(row['score_units'], 2)} units"
        )

    return "\n".join(lines)
