from datetime import date
import re

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
from db import test_connection, insert_workout_rows


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
    db_name = test_connection()
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

        insert_workout_rows(rows)

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


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("dbtest", dbtest))
    app.add_handler(CommandHandler("add_exercise", add_command))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()