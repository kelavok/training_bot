from datetime import date
import re
from pathlib import Path
import tempfile

import db
import analytics
import charts

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


WAITING_FOR_EXERCISE = "waiting_for_exercise"
PENDING_ROWS = "pending_rows"


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


def parse_workout_text(text: str):
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
                "user_id": 1,
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Добавить упражнение", callback_data="add_exercise")]
    ]

    await update.message.reply_text(
        "Бот работает. Можно добавить упражнение.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def dbtest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_name = db.test_connection()
    await update.message.reply_text(f"Подключение к базе работает: {db_name}")


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data[WAITING_FOR_EXERCISE] = True
    await update.message.reply_text(TEMPLATE)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "add_exercise":
        context.user_data[WAITING_FOR_EXERCISE] = True
        await query.message.reply_text(TEMPLATE)

    elif query.data == "confirm_insert":
        rows = context.user_data.get(PENDING_ROWS)

        if not rows:
            await query.message.reply_text("Нет данных для сохранения.")
            return

        db.insert_workout_rows(rows)

        context.user_data[PENDING_ROWS] = None
        context.user_data[WAITING_FOR_EXERCISE] = False

        await query.message.reply_text("Сохранил в базу.")

    elif query.data == "cancel_insert":
        context.user_data[PENDING_ROWS] = None
        context.user_data[WAITING_FOR_EXERCISE] = False

        await query.message.reply_text("Ок, не сохраняю.")


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get(WAITING_FOR_EXERCISE):
        await update.message.reply_text(
            "Я пока жду команду. Нажми /start или /add_exercise."
        )
        return

    try:
        rows = parse_workout_text(update.message.text)
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
    rows = db.get_volume_by_date()

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
    latest_date = db.get_latest_training_date()

    if not latest_date:
        await update.message.reply_text("В базе пока нет тренировок.")
        return

    rows = db.get_workouts_by_date(latest_date)

    if not rows:
        await update.message.reply_text("Не нашёл строк для последней даты тренировки.")
        return

    result = analytics.calculate_session_scores(rows)
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
# main!
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("dbtest", dbtest))
    app.add_handler(CommandHandler("add_exercise", add_command))
    app.add_handler(CommandHandler("last", last))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("volume", volume))
    app.add_handler(CommandHandler("score", score))
    app.add_handler(CommandHandler("muscle_trend", muscle_trend))
    app.add_handler(CommandHandler("score_chart", score_chart))

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



if __name__ == "__main__":
    main()

