from datetime import date

import re
from pathlib import Path
import tempfile
import reference_service
import stats_service
import stats_formatter
import stats_charts
import stats_view_service

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from config import BOT_TOKEN
import db
import analytics
import charts
import gemini_parser


WAITING_FOR_EXERCISE = "waiting_for_exercise"
PENDING_ROWS = "pending_rows"
WAITING_FOR_AI_WORKOUT = "waiting_for_ai_workout"

CALLBACK_ADD_AI_WORKOUT = "add_ai_workout"
CALLBACK_USE_TEMPLATE_PARSER = "use_template_parser"
CALLBACK_LAST_DATE_PREFIX = "last_date:"


COMMANDS_HELP = """
Команды бота:

Добавление тренировок:
/start - главное меню
/ai_add - добавить тренировку свободным текстом через AI parser
/add_exercise - старый шаблонный ввод
/last - последние 10 тренировочных дат, клик открывает все строки за день

Текстовая статистика:
/stats [7d|30d|90d|all|YYYY-MM] - обзор периода
/top exercises [metric] [period] [limit] - топ упражнений
/top muscles [metric] [period] [limit] - топ мышц
/exercise bench_press [period] - статистика упражнения
/muscle chest [period] - статистика мышечной группы
/score - score последней тренировки
/volume - volume по последним дням

Графики:
/score_chart - dashboard последней тренировки
/score_chart [7d|30d|90d|all|YYYY-MM] - dashboard периода
/stats_chart [period] - dashboard периода
/top_chart exercises [metric] [period] [limit] - график топа упражнений
/top_chart muscles [metric] [period] [limit] - график топа мышц
/exercise_chart bench_press [period] - график прогресса упражнения
/muscle_chart chest [period] - график мышцы
/muscle_trend [period] - тренд топ мышц

Периоды:
7d, 30d, 90d, all, YYYY-MM. По умолчанию обычно 30d.

Метрики для exercise top:
score_units, total_volume, avg_rating, best_e1rm, best_working_weight, sets, working_sets, heavy_sets

Метрики для muscle top:
score_units, avg_rating, best_rating

Примеры:
/stats 30d
/top exercises best_e1rm all 10
/top_chart muscles score_units 90d
/exercise_chart bench_press 90d
/muscle_chart chest 30d
""".strip()




TEMPLATE = """
Введите упражнение по схеме:

exercise: bench_press
category: chest
sets: 3
reps: 10, 8, 7
weight_kg: 60, 65, 65
rest_sec_after: 120
duration_sec:
rpe: 7, 8, 8
notes: normal

Можно разделять значения пробелами или запятыми.
Если значение одно, оно применится ко всем подходам.
"""


def split_values(value: str):
    value = value.strip()

    if not value:
        return []

    parts = re.split(r"[,\s]+", value)
    return [p.strip() for p in parts if p.strip()]


def expand_values(values, sets_count, field_name, cast_func):
    if len(values) == 0:
        return [None] * sets_count

    if len(values) == 1:
        try:
            return [cast_func(values[0])] * sets_count
        except ValueError:
            raise ValueError(f"Поле `{field_name}` содержит некорректное значение.")

    if len(values) != sets_count:
        raise ValueError(
            f"Поле `{field_name}`: количество значений ({len(values)}) "
            f"не совпадает с количеством подходов ({sets_count})."
        )

    try:
        return [cast_func(v) for v in values]
    except ValueError:
        raise ValueError(f"Поле `{field_name}` содержит некорректные значения.")


def parse_workout_text(text: str, user_id: int):
    data = {}

    for line in text.splitlines():
        line = line.strip()

        if not line:
            continue

        if ":" not in line:
            raise ValueError(
                "Каждая строка должна быть в формате `поле: значение`."
            )

        key, value = line.split(":", 1)
        data[key.strip().lower()] = value.strip()

    required_fields = ["exercise", "category", "sets", "reps", "weight_kg"]

    for field in required_fields:
        if field not in data or not data[field]:
            raise ValueError(f"Не заполнено обязательное поле `{field}`.")

    try:
        sets_count = int(data["sets"])
    except ValueError:
        raise ValueError("Поле `sets` должно быть целым числом.")

    if sets_count <= 0:
        raise ValueError("Поле `sets` должно быть больше нуля.")

    exercise = data["exercise"]
    category = data["category"]

    reps = expand_values(
        split_values(data.get("reps", "")),
        sets_count,
        "reps",
        int
    )

    weights = expand_values(
        split_values(data.get("weight_kg", "")),
        sets_count,
        "weight_kg",
        float
    )

    rest_values = expand_values(
        split_values(data.get("rest_sec_after", "")),
        sets_count,
        "rest_sec_after",
        int
    )

    duration_values = expand_values(
        split_values(data.get("duration_sec", "")),
        sets_count,
        "duration_sec",
        int
    )

    rpe_values = expand_values(
        split_values(data.get("rpe", "")),
        sets_count,
        "rpe",
        int
    )

    notes = data.get("notes", "") or None

    rows = []

    for i in range(sets_count):
        rows.append(
            {
                "user_id": user_id,
                "date": date.today(),
                "exercise": exercise,
                "category": category,
                "reps": reps[i],
                "weight_kg": weights[i],
                "rest_sec_after": rest_values[i],
                "duration_sec": duration_values[i],
                "rpe": rpe_values[i],
                "notes": notes,
            }
        )

    return rows


def format_preview(rows: list[dict]):
    lines = ["Проверь, что бот понял правильно:\n"]

    for i, row in enumerate(rows, start=1):
        lines.append(
            f"{i}. {row['exercise']} | {row['category']} | "
            f"reps: {row['reps']} | weight: {row['weight_kg']} | "
            f"rest: {row['rest_sec_after']} | duration: {row['duration_sec']} | "
            f"rpe: {row['rpe']} | notes: {row['notes']}"
        )

    return "\n".join(lines)


def format_workouts_for_date(training_date, rows: list[dict]) -> str:
    if not rows:
        return f"Нет строк workouts за дату {training_date}."

    total_volume = sum(
        analytics.to_float(row.get("reps")) * analytics.to_float(row.get("weight_kg"))
        for row in rows
    )
    exercises_count = len({
        analytics.normalize_exercise_name(row.get("exercise"))
        for row in rows
        if row.get("exercise")
    })

    lines = [
        f"Тренировка за {training_date}",
        "",
        f"Строк/подходов: {len(rows)}",
        f"Упражнений: {exercises_count}",
        f"Volume: {total_volume:.1f} kg",
        "",
    ]

    current_exercise = None

    for index, row in enumerate(rows, start=1):
        exercise = row.get("exercise") or "unknown"

        if exercise != current_exercise:
            current_exercise = exercise
            lines.append(f"{exercise}")

        reps = row.get("reps")
        weight = row.get("weight_kg")
        duration = row.get("duration_sec")
        rest = row.get("rest_sec_after")
        rpe = row.get("rpe")
        notes = row.get("notes")

        detail_parts = [f"#{row['id']}", f"{reps} reps"]

        if weight is not None:
            detail_parts.append(f"{analytics.to_float(weight):.1f} kg")

        if duration is not None and analytics.to_int(duration) > 0:
            detail_parts.append(f"{duration} sec")

        if rest is not None:
            detail_parts.append(f"rest {rest}s")

        if rpe is not None:
            detail_parts.append(f"rpe {rpe}")

        if notes:
            detail_parts.append(f"notes: {notes}")

        lines.append(f"{index}. " + " | ".join(detail_parts))

    return "\n".join(lines)


def split_telegram_text(text: str, limit: int = 3900) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks = []
    current_lines = []
    current_length = 0

    for line in text.splitlines():
        line_length = len(line) + 1

        if current_lines and current_length + line_length > limit:
            chunks.append("\n".join(current_lines))
            current_lines = []
            current_length = 0

        current_lines.append(line)
        current_length += line_length

    if current_lines:
        chunks.append("\n".join(current_lines))

    return chunks


def get_current_user_id(update: Update) -> int:
    telegram_user = update.effective_user

    if telegram_user is None:
        raise ValueError("Не удалось определить Telegram-пользователя.")

    return db.get_or_create_user(
        telegram_user_id=telegram_user.id,
        username=telegram_user.username,
        first_name=telegram_user.first_name,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    get_current_user_id(update)

    keyboard = [
        [InlineKeyboardButton("Добавить тренировку", callback_data=CALLBACK_ADD_AI_WORKOUT)]
    ]

    await update.message.reply_text(
        "Бот работает. Можно добавить тренировку свободным текстом.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def dbtest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_name = db.test_connection()
    await update.message.reply_text(f"Подключение к базе работает: {db_name}")


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data[WAITING_FOR_EXERCISE] = True
    context.user_data[WAITING_FOR_AI_WORKOUT] = False

    await update.message.reply_text(TEMPLATE)

async def ai_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data[WAITING_FOR_AI_WORKOUT] = True
    context.user_data[WAITING_FOR_EXERCISE] = False
    context.user_data[PENDING_ROWS] = None

    await update.message.reply_text(
        "Напиши тренировку свободным текстом. Например:\n\n"
        "Жим лёжа: 20×15 разминка, 50×10, 60×8, 60×7. "
        "Потом подтягивания 10, 8, 6. Пресс 3×30."
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = get_current_user_id(update)

    if query.data.startswith(CALLBACK_LAST_DATE_PREFIX):
        date_value = query.data.removeprefix(CALLBACK_LAST_DATE_PREFIX)

        try:
            training_date = date.fromisoformat(date_value)
        except ValueError:
            await query.message.reply_text(f"Некорректная дата: {date_value}")
            return

        rows = db.get_workouts_by_date(training_date, user_id=user_id)
        for chunk in split_telegram_text(format_workouts_for_date(training_date, rows)):
            await query.message.reply_text(chunk)
        return

    if query.data == CALLBACK_ADD_AI_WORKOUT:
        context.user_data[WAITING_FOR_AI_WORKOUT] = True
        context.user_data[WAITING_FOR_EXERCISE] = False
        context.user_data[PENDING_ROWS] = None

        await query.message.reply_text(
            "Напиши тренировку свободным текстом. Например:\n\n"
            "Жим лёжа: 20×15 разминка, 50×10, 60×8, 60×7. "
            "Потом подтягивания 10, 8, 6. Пресс 3×30."
        )
        return

    if query.data == "add_exercise":
        context.user_data[WAITING_FOR_EXERCISE] = True
        context.user_data[WAITING_FOR_AI_WORKOUT] = False
        context.user_data[PENDING_ROWS] = None

        await query.message.reply_text(TEMPLATE)
        return

    if query.data == CALLBACK_USE_TEMPLATE_PARSER:
        context.user_data[WAITING_FOR_EXERCISE] = True
        context.user_data[WAITING_FOR_AI_WORKOUT] = False
        context.user_data[PENDING_ROWS] = None

        await query.message.reply_text(
            "Ок, переключаю на старый шаблонный парсер.\n\n"
            f"{TEMPLATE}"
        )
        return

    if query.data == "confirm_insert":
        rows = context.user_data.get(PENDING_ROWS)

        if not rows:
            await query.message.reply_text("Нет данных для сохранения.")
            return

        try:
            db.insert_workout_rows(rows)

        except Exception as e:
            print("INSERT ERROR:", repr(e))
            print("ROWS:", rows)

            await query.message.reply_text(
                f"Не смог сохранить в базу: {e}"
            )
            return

        try:
            training_dates = {
                row["date"]
                for row in rows
                if row.get("date") is not None
            }
            exercise_keys = {
                analytics.normalize_exercise_name(row.get("exercise"))
                for row in rows
                if row.get("exercise") is not None
            }

            references_count = reference_service.rebuild_references_for_exercises(
                exercise_keys=exercise_keys,
                user_id=user_id,
            )

            print("REFERENCE REBUILD RESULT:", references_count)

            rebuild_result = stats_service.rebuild_stats_for_dates(
                training_dates=training_dates,
                user_id=user_id,
            )

            print("STATS REBUILD RESULT:", rebuild_result)

        except Exception as e:
            print("STATS REBUILD ERROR:", repr(e))

            await query.message.reply_text(
                "Тренировку сохранил, но не смог обновить агрегированную статистику. "
                f"Ошибка: {e}"
            )

            context.user_data[PENDING_ROWS] = None
            context.user_data[WAITING_FOR_EXERCISE] = False
            context.user_data[WAITING_FOR_AI_WORKOUT] = False
            return

        context.user_data[PENDING_ROWS] = None
        context.user_data[WAITING_FOR_EXERCISE] = False
        context.user_data[WAITING_FOR_AI_WORKOUT] = False

        await query.message.reply_text(
            "Сохранил в базу и обновил статистику."
        )
        return

    if query.data == "cancel_insert":
        context.user_data[PENDING_ROWS] = None
        context.user_data[WAITING_FOR_EXERCISE] = False
        context.user_data[WAITING_FOR_AI_WORKOUT] = False

        await query.message.reply_text("Ок, не сохраняю.")
        return

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_current_user_id(update)

    if context.user_data.get(WAITING_FOR_AI_WORKOUT):
        await update.message.reply_text("Разбираю тренировку через Gemini...")

        try:

            existing_exercises = db.get_existing_exercise_names(user_id=user_id)

            rows = gemini_parser.parse_workout_with_gemini(
                
                text=update.message.text,
                default_date=date.today(),
                user_id=user_id,
                existing_exercises=existing_exercises,
            )
         

            context.user_data[PENDING_ROWS] = rows

            keyboard = [
                [
                    InlineKeyboardButton("OK", callback_data="confirm_insert"),
                    InlineKeyboardButton("Cancel", callback_data="cancel_insert"),
                ]
            ]

            await update.message.reply_text(
                format_preview(rows),
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

        except Exception as e:
            print("GEMINI PARSE ERROR:", repr(e))

            keyboard = [
                [
                    InlineKeyboardButton("Use template parser", callback_data=CALLBACK_USE_TEMPLATE_PARSER),
                    InlineKeyboardButton("Cancel", callback_data="cancel_insert"),
                ]
            ]

            await update.message.reply_text(
                "Не смог разобрать тренировку через Gemini.\n\n"
                f"Ошибка: {e}\n\n"
                "Можно отменить или перейти на старый шаблонный ввод.",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

        return

    if not context.user_data.get(WAITING_FOR_EXERCISE):
        await update.message.reply_text(
            "Я пока жду команду. Нажми /start, /ai_add или /add_exercise."
        )
        return

    try:
        rows = parse_workout_text(update.message.text, user_id=user_id)
        context.user_data[PENDING_ROWS] = rows

        keyboard = [
            [
                InlineKeyboardButton("OK", callback_data="confirm_insert"),
                InlineKeyboardButton("Cancel", callback_data="cancel_insert"),
            ]
        ]

        await update.message.reply_text(
            format_preview(rows),
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    except Exception as e:
        await update.message.reply_text(
            f"Данные некорректны: {e}\n\nПопробуй ещё раз по схеме:\n{TEMPLATE}"
        )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    row = db.get_basic_stats()

    text = (
        "Общая статистика:\n\n"
        f"Подходов: {row['total_sets']}\n"
        f"Тренировочных дней: {row['training_days']}\n"
        f"Уникальных упражнений: {row['unique_exercises']}\n"
        f"Всего повторений: {row['total_reps']}\n"
        f"Общий объём: {float(row['total_volume']):.1f} кг\n"
        f"Период: {row['first_date']} — {row['last_date']}"
    )

    await update.message.reply_text(text)

async def volume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_current_user_id(update)
    rows = db.get_volume_by_date(user_id=user_id)

    if not rows:
        await update.message.reply_text("Данных пока нет.")
        return

    lines = ["Объём по последним тренировочным дням:\n"]

    for row in rows:
        lines.append(
            f"{row['date']} | "
            f"объём: {float(row['total_volume']):.1f} кг | "
            f"подходов: {row['sets_count']}"
        )

    await update.message.reply_text("\n".join(lines))


async def score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_current_user_id(update)
    latest_date = db.get_latest_training_date(user_id=user_id)

    if not latest_date:
        await update.message.reply_text("В базе пока нет тренировок.")
        return

    rows = db.get_workouts_by_date(latest_date, user_id=user_id)

    if not rows:
        await update.message.reply_text("Не нашёл строк для последней даты тренировки.")
        return

    reference_values = reference_service.get_reference_values(user_id=user_id)
    result = analytics.calculate_session_scores(
        rows,
        reference_values=reference_values,
    )
    report = analytics.format_session_score_report(result)

    await update.message.reply_text(report)


#charts
async def muscle_trend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.get_all_workouts()

    if not rows:
        await update.message.reply_text("В базе пока нет тренировок.")
        return

    unique_dates = sorted({row["date"] for row in rows})

    if len(unique_dates) < 2:
        await update.message.reply_text(
            "Для графика динамики нужно минимум 2 тренировочных дня."
        )
        return

    with tempfile.NamedTemporaryFile(
        suffix=".png",
        delete=False,
    ) as tmp_file:
        output_path = Path(tmp_file.name)

    try:
        charts.save_muscle_trend_chart(
            rows=rows,
            output_path=output_path,
            top_n=8,
            reference_values=reference_service.get_reference_values(user_id=1),
        )

        with open(output_path, "rb") as image_file:
            await update.message.reply_photo(
                photo=image_file,
                caption="Динамика score по мышечным группам."
            )

    except Exception as e:
        await update.message.reply_text(f"Не смог построить график: {e}")

    finally:
        if output_path.exists():
            output_path.unlink()


            
async def score_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.get_all_workouts()

    if not rows:
        await update.message.reply_text("В базе пока нет тренировок.")
        return

    with tempfile.NamedTemporaryFile(
        suffix=".png",
        delete=False,
    ) as tmp_file:
        output_path = Path(tmp_file.name)

    try:
        charts.save_latest_score_dashboard(
            rows=rows,
            output_path=output_path,
            reference_values=reference_service.get_reference_values(user_id=1),
        )

        with open(output_path, "rb") as image_file:
            await update.message.reply_photo(
                photo=image_file,
                caption="Визуальная сводка последней тренировки."
            )

    except Exception as e:
        await update.message.reply_text(f"Не смог построить score chart: {e}")

    finally:
        if output_path.exists():
            output_path.unlink()
# New chart handlers override the older chart handlers above.
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(COMMANDS_HELP)


def parse_top_chart_args(args: list[str]) -> tuple[str | None, str, str, int]:
    if not args:
        return None, "score_units", "30d", 10

    target = args[0].lower()
    metric = "score_units"
    period_token = "30d"
    limit = 10

    for arg in args[1:]:
        if arg.isdigit():
            limit = min(max(int(arg), 1), 20)
        elif stats_view_service.is_period_token(arg):
            period_token = arg
        else:
            metric = arg

    return target, metric, period_token, limit


async def send_chart(update: Update, output_path: Path, caption: str):
    with open(output_path, "rb") as image_file:
        await update.message.reply_photo(
            photo=image_file,
            caption=caption,
        )


async def muscle_trend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_current_user_id(update)
    period_token = context.args[0] if context.args else "90d"

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
        output_path = Path(tmp_file.name)

    try:
        stats_charts.save_muscle_trend_chart_from_aggregates(
            period_token=period_token,
            output_path=output_path,
            top_n=8,
            user_id=user_id,
        )
        await send_chart(
            update=update,
            output_path=output_path,
            caption=f"Muscle trend: {period_token}",
        )

    except Exception as e:
        await update.message.reply_text(f"Не смог построить график: {e}")

    finally:
        if output_path.exists():
            output_path.unlink()


async def score_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_current_user_id(update)
    period_token = context.args[0] if context.args else "latest"

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
        output_path = Path(tmp_file.name)

    try:
        if period_token == "latest":
            rows = db.get_all_workouts(user_id=user_id)

            if not rows:
                await update.message.reply_text("В базе пока нет тренировок.")
                return

            charts.save_latest_score_dashboard(
                rows=rows,
                output_path=output_path,
                reference_values=reference_service.get_reference_values(user_id=user_id),
            )
            caption = "Визуальная сводка по последней тренировке."
        else:
            stats_charts.save_period_dashboard(
                period_token=period_token,
                output_path=output_path,
                user_id=user_id,
            )
            caption = f"Визуальная сводка за период: {period_token}"

        await send_chart(
            update=update,
            output_path=output_path,
            caption=caption,
        )

    except Exception as e:
        await update.message.reply_text(f"Не смог построить score chart: {e}")

    finally:
        if output_path.exists():
            output_path.unlink()


async def stats_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_current_user_id(update)
    period_token = context.args[0] if context.args else "30d"

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
        output_path = Path(tmp_file.name)

    try:
        stats_charts.save_period_dashboard(
            period_token=period_token,
            output_path=output_path,
            user_id=user_id,
        )
        await send_chart(
            update=update,
            output_path=output_path,
            caption=f"Dashboard за период: {period_token}",
        )

    except Exception as e:
        await update.message.reply_text(f"Не смог построить dashboard: {e}")

    finally:
        if output_path.exists():
            output_path.unlink()


async def top_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_current_user_id(update)
    target, metric, period_token, limit = parse_top_chart_args(context.args)

    if target is None or target in {"help", "?", "помощь"}:
        await update.message.reply_text(COMMANDS_HELP)
        return

    if target not in {"exercise", "exercises", "muscle", "muscles"}:
        await update.message.reply_text(
            "Используй /top_chart exercises ... или /top_chart muscles ..."
        )
        return

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
        output_path = Path(tmp_file.name)

    try:
        stats_charts.save_top_chart(
            target=target,
            metric=metric,
            period_token=period_token,
            limit=limit,
            output_path=output_path,
            user_id=user_id,
        )
        await send_chart(
            update=update,
            output_path=output_path,
            caption=f"Top chart: {target}, {metric}, {period_token}",
        )

    except Exception as e:
        await update.message.reply_text(f"Не смог построить top chart: {e}")

    finally:
        if output_path.exists():
            output_path.unlink()


async def exercise_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_current_user_id(update)
    if not context.args:
        await update.message.reply_text(
            "Укажи упражнение. Например: /exercise_chart bench_press 90d"
        )
        return

    exercise_args, period_token = stats_view_service.split_period_arg(context.args)

    if not exercise_args:
        await update.message.reply_text(
            "Укажи упражнение перед периодом. Например: /exercise_chart bench_press 90d"
        )
        return

    exercise_input = " ".join(exercise_args)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
        output_path = Path(tmp_file.name)

    try:
        stats_charts.save_exercise_chart(
            exercise_input=exercise_input,
            period_token=period_token,
            output_path=output_path,
            user_id=user_id,
        )
        await send_chart(
            update=update,
            output_path=output_path,
            caption=f"Exercise chart: {exercise_input}, {period_token}",
        )

    except Exception as e:
        await update.message.reply_text(f"Не смог построить exercise chart: {e}")

    finally:
        if output_path.exists():
            output_path.unlink()


async def muscle_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_current_user_id(update)
    if not context.args:
        await update.message.reply_text(
            "Укажи мышцу. Например: /muscle_chart chest 90d"
        )
        return

    muscle_args, period_token = stats_view_service.split_period_arg(context.args)

    if not muscle_args:
        await update.message.reply_text(
            "Укажи мышцу перед периодом. Например: /muscle_chart chest 90d"
        )
        return

    muscle_input = " ".join(muscle_args)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
        output_path = Path(tmp_file.name)

    try:
        stats_charts.save_muscle_chart(
            muscle_input=muscle_input,
            period_token=period_token,
            output_path=output_path,
            user_id=user_id,
        )
        await send_chart(
            update=update,
            output_path=output_path,
            caption=f"Muscle chart: {muscle_input}, {period_token}",
        )

    except Exception as e:
        await update.message.reply_text(f"Не смог построить muscle chart: {e}")

    finally:
        if output_path.exists():
            output_path.unlink()


# main!

async def legacy_exercise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Укажи упражнение. Например:\n"
            "/exercise bench_press\n"
            "/exercise Bench Press"
        )
        return

    exercise_input = " ".join(context.args)
    exercise_key = analytics.normalize_exercise_name(exercise_input)

    rows = db.get_exercise_aggregate_history(exercise_key)

    if not rows:
        await update.message.reply_text(
            f"Не нашёл агрегатов по упражнению: {exercise_key}"
        )
        return

    latest = rows[-1]

    total_sessions = len(rows)
    total_sets = sum(row["sets"] or 0 for row in rows)
    total_reps = sum(row["total_reps"] or 0 for row in rows)
    total_volume = sum(float(row["total_volume"] or 0) for row in rows)
    max_weight = max(float(row["max_weight"] or 0) for row in rows)

    working_weights = [
        float(row["working_weight"])
        for row in rows
        if row["working_weight"] is not None
    ]

    best_working_weight = max(working_weights) if working_weights else None

    best_e1rm_values = [
        float(row["best_estimated_1rm"])
        for row in rows
        if row["best_estimated_1rm"] is not None
    ]

    best_e1rm = max(best_e1rm_values) if best_e1rm_values else None

    avg_rating = sum(float(row["rating_10"] or 0) for row in rows) / total_sessions

    text = [
        f"Статистика по упражнению: {exercise_key}",
        "",
        f"Тренировочных дней: {total_sessions}",
        f"Последняя дата: {latest['date']}",
        f"Всего подходов: {total_sets}",
        f"Всего повторений: {total_reps}",
        f"Общий объём: {total_volume:.1f} кг",
        f"Максимальный вес: {max_weight:.1f} кг",
    ]

    if best_working_weight is not None:
        text.append(f"Лучший рабочий вес: {best_working_weight:.1f} кг")

    if best_e1rm is not None:
        text.append(f"Лучший e1RM: {best_e1rm:.1f} кг")

    text.extend(
        [
            f"Последний score: {float(latest['rating_10'] or 0):.1f}/10",
            f"Средний score: {avg_rating:.1f}/10",
        ]
    )

    if latest["exercise_type"] in {"reps_based", "bodyweight"}:
        text.append(f"Последние повторы за день: {latest['total_reps']}")

    if latest["exercise_type"] == "static":
        text.append(f"Последняя длительность: {latest['total_duration_sec']} сек.")

    await update.message.reply_text("\n".join(text))


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_current_user_id(update)

    if context.args and context.args[0].lower() in {"help", "?", "помощь"}:
        await update.message.reply_text(stats_formatter.format_stats_help())
        return

    period_token = context.args[0] if context.args else "30d"
    data = stats_view_service.build_overview(period_token=period_token, user_id=user_id)

    await update.message.reply_text(stats_formatter.format_overview(data))


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_current_user_id(update)

    if not context.args or context.args[0].lower() in {"help", "?", "помощь"}:
        await update.message.reply_text(stats_formatter.format_stats_help())
        return

    target = context.args[0].lower()
    metric = "score_units"
    period_token = "30d"
    limit = 10

    for arg in context.args[1:]:
        if arg.isdigit():
            limit = min(max(int(arg), 1), 20)
        elif stats_view_service.is_period_token(arg):
            period_token = arg
        else:
            metric = arg

    if target in {"exercise", "exercises", "упражнения"}:
        data = stats_view_service.build_top_exercises(
            period_token=period_token,
            metric=metric,
            limit=limit,
            user_id=user_id,
        )
        await update.message.reply_text(stats_formatter.format_top_exercises(data))
        return

    if target in {"muscle", "muscles", "мышцы"}:
        data = stats_view_service.build_top_muscles(
            period_token=period_token,
            metric=metric,
            limit=limit,
            user_id=user_id,
        )
        await update.message.reply_text(stats_formatter.format_top_muscles(data))
        return

    await update.message.reply_text(
        "Не понял тип топа. Используй /top exercises ... или /top muscles ..."
    )


async def exercise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_current_user_id(update)

    if not context.args:
        await update.message.reply_text(
            "Укажи упражнение. Например:\n"
            "/exercise bench_press\n"
            "/exercise bench_press 90d"
        )
        return

    exercise_args, period_token = stats_view_service.split_period_arg(context.args)

    if not exercise_args:
        await update.message.reply_text(
            "Укажи упражнение перед периодом. Например: /exercise bench_press 90d"
        )
        return

    exercise_input = " ".join(exercise_args)
    data = stats_view_service.build_exercise_detail(
        exercise_input=exercise_input,
        period_token=period_token,
        user_id=user_id,
    )

    await update.message.reply_text(stats_formatter.format_exercise_detail(data))


async def muscle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_current_user_id(update)

    if not context.args:
        await update.message.reply_text(
            "Укажи мышцу. Например:\n"
            "/muscle chest\n"
            "/muscle back 90d"
        )
        return

    muscle_args, period_token = stats_view_service.split_period_arg(context.args)

    if not muscle_args:
        await update.message.reply_text(
            "Укажи мышцу перед периодом. Например: /muscle chest 30d"
        )
        return

    muscle_input = " ".join(muscle_args)
    data = stats_view_service.build_muscle_detail(
        muscle_input=muscle_input,
        period_token=period_token,
        user_id=user_id,
    )

    await update.message.reply_text(stats_formatter.format_muscle_detail(data))


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("commands", help_command))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("dbtest", dbtest))
    app.add_handler(CommandHandler("add_exercise", add_command))
    app.add_handler(CommandHandler("ai_add", ai_add_command))
    app.add_handler(CommandHandler("last", last))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("volume", volume))
    app.add_handler(CommandHandler("score", score))
    app.add_handler(CommandHandler("muscle_trend", muscle_trend))
    
    app.add_handler(CommandHandler("score_chart", score_chart))
    app.add_handler(CommandHandler("stats_chart", stats_chart))
    app.add_handler(CommandHandler("top_chart", top_chart))
    app.add_handler(CommandHandler("exercise_chart", exercise_chart))
    app.add_handler(CommandHandler("muscle_chart", muscle_chart))
    app.add_handler(CommandHandler("exercise", exercise))
    app.add_handler(CommandHandler("muscle", muscle))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("Bot is running...")
    app.run_polling()

#last_rows
async def last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.get_last_workouts(limit=10)

    if not rows:
        await update.message.reply_text("В базе пока нет тренировок.")
        return

    lines = ["Последние записи:\n"]

    for row in rows:
        lines.append(
            f"#{row['id']} | {row['date']} | {row['exercise']} | "
            f"{row['reps']} reps × {row['weight_kg']} kg | "
            f"rpe: {row['rpe']} | notes: {row['notes']}"
        )

    await update.message.reply_text("\n".join(lines))


async def last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_current_user_id(update)
    rows = db.get_latest_training_dates(limit=10, user_id=user_id)

    if not rows:
        await update.message.reply_text("В базе пока нет тренировок.")
        return

    lines = [
        "Последние тренировочные даты.",
        "Нажми дату, чтобы открыть все строки workouts за день:",
        "",
    ]
    keyboard = []

    for row in rows:
        training_date = row["date"]
        lines.append(
            f"{training_date} | "
            f"строк: {row['rows_count']} | "
            f"упражнений: {row['exercises_count']} | "
            f"volume: {analytics.to_float(row['total_volume']):.1f} kg"
        )
        keyboard.append(
            [
                InlineKeyboardButton(
                    str(training_date),
                    callback_data=f"{CALLBACK_LAST_DATE_PREFIX}{training_date}",
                )
            ]
        )

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )



if __name__ == "__main__":
    main()

