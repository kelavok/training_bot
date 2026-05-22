from sqlalchemy import create_engine, text

from config import DATABASE_URL, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME


DEFAULT_REST_SEC_AFTER = 120
DEFAULT_RPE = 6


def get_engine():
    if DATABASE_URL:
        return create_engine(DATABASE_URL)

    return create_engine(
        f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )


def test_connection():
    engine = get_engine()

    with engine.connect() as conn:
        result = conn.execute(text("SELECT current_database();"))
        db_name = result.scalar()

    return db_name


def normalize_workout_row_defaults(row: dict) -> dict:
    normalized_row = dict(row)

    rest_sec_after = normalized_row.get("rest_sec_after")
    rpe = normalized_row.get("rpe")

    if rest_sec_after is None or rest_sec_after <= 0:
        normalized_row["rest_sec_after"] = DEFAULT_REST_SEC_AFTER

    if rpe is None or rpe <= 0:
        normalized_row["rpe"] = DEFAULT_RPE

    return normalized_row


def normalize_workout_rows_defaults(rows: list[dict]) -> list[dict]:
    return [normalize_workout_row_defaults(row) for row in rows]


def insert_workout_rows(rows: list[dict]):
    engine = get_engine()
    rows = normalize_workout_rows_defaults(rows)

    with engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO workouts 
                (
                    user_id,
                    date,
                    exercise,
                    category,
                    reps,
                    weight_kg,
                    rest_sec_after,
                    duration_sec,
                    rpe,
                    notes
                )
                VALUES 
                (
                    :user_id,
                    :date,
                    :exercise,
                    :category,
                    :reps,
                    :weight_kg,
                    :rest_sec_after,
                    :duration_sec,
                    :rpe,
                    :notes
                )
            """),
            rows
        )
        conn.commit()

#analytics_layer
#1. last rows
def get_last_workouts(limit: int = 10):
    engine = get_engine()

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT
                    id,
                    date,
                    exercise,
                    category,
                    reps,
                    weight_kg,
                    rest_sec_after,
                    duration_sec,
                    rpe,
                    notes
                FROM workouts
                ORDER BY id DESC
                LIMIT :limit
            """),
            {"limit": limit}
        )

        rows = result.mappings().all()

    return rows

def get_basic_stats():
    engine = get_engine()

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT
                    COUNT(*) AS total_sets,
                    COUNT(DISTINCT date) AS training_days,
                    COUNT(DISTINCT exercise) AS unique_exercises,
                    COALESCE(SUM(reps), 0) AS total_reps,
                    COALESCE(SUM(reps * weight_kg), 0) AS total_volume,
                    MIN(date) AS first_date,
                    MAX(date) AS last_date
                FROM workouts
            """)
        )

        row = result.mappings().one()

    return row

def get_volume_by_date():
    engine = get_engine()

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT
                    date,
                    COALESCE(SUM(reps * weight_kg), 0) AS total_volume,
                    COUNT(*) AS sets_count
                FROM workouts
                GROUP BY date
                ORDER BY date DESC
                LIMIT 10
            """)
        )

        rows = result.mappings().all()

    return rows

#Connect with analytics
def get_latest_training_date():
    engine = get_engine()

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT MAX(date) AS latest_date
                FROM workouts
            """)
        )

        latest_date = result.scalar()

    return latest_date


def get_workouts_by_date(training_date):
    engine = get_engine()

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT
                    id,
                    user_id,
                    date,
                    exercise,
                    category,
                    reps,
                    weight_kg,
                    rest_sec_after,
                    duration_sec,
                    rpe,
                    notes
                FROM workouts
                WHERE date = :training_date
                ORDER BY id
            """),
            {"training_date": training_date}
        )

        rows = result.mappings().all()

    return rows

#get all workouts for analytics
def get_all_workouts():
    engine = get_engine()

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT
                    id,
                    user_id,
                    date,
                    exercise,
                    category,
                    reps,
                    weight_kg,
                    rest_sec_after,
                    duration_sec,
                    rpe,
                    notes
                FROM workouts
                ORDER BY date, id
            """)
        )

        rows = result.mappings().all()

    return rows


def get_existing_exercise_names():
    engine = get_engine()

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT DISTINCT exercise
                FROM workouts
                WHERE exercise IS NOT NULL
                ORDER BY exercise
            """)
        )

        rows = result.scalars().all()

    return list(rows)



def clear_daily_stats():
    engine = get_engine()

    with engine.connect() as conn:
        conn.execute(text("DELETE FROM daily_exercise_stats"))
        conn.execute(text("DELETE FROM daily_muscle_stats"))
        conn.commit()


def insert_daily_exercise_stats(rows: list[dict]):
    if not rows:
        return

    engine = get_engine()

    with engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO daily_exercise_stats
                (
                    user_id,
                    date,
                    exercise,
                    exercise_type,
                    sets,
                    working_sets,
                    heavy_sets,
                    target_sets,
                    total_reps,
                    total_duration_sec,
                    total_volume,
                    max_weight,
                    working_weight,
                    best_estimated_1rm,
                    avg_intensity,
                    score_units,
                    target_units,
                    rating_10,
                    algorithmic_effort,
                    updated_at
                )
                VALUES
                (
                    :user_id,
                    :date,
                    :exercise,
                    :exercise_type,
                    :sets,
                    :working_sets,
                    :heavy_sets,
                    :target_sets,
                    :total_reps,
                    :total_duration_sec,
                    :total_volume,
                    :max_weight,
                    :working_weight,
                    :best_estimated_1rm,
                    :avg_intensity,
                    :score_units,
                    :target_units,
                    :rating_10,
                    :algorithmic_effort,
                    now()
                )
                ON CONFLICT (user_id, date, exercise)
                DO UPDATE SET
                    exercise_type = EXCLUDED.exercise_type,
                    sets = EXCLUDED.sets,
                    working_sets = EXCLUDED.working_sets,
                    heavy_sets = EXCLUDED.heavy_sets,
                    target_sets = EXCLUDED.target_sets,
                    total_reps = EXCLUDED.total_reps,
                    total_duration_sec = EXCLUDED.total_duration_sec,
                    total_volume = EXCLUDED.total_volume,
                    max_weight = EXCLUDED.max_weight,
                    working_weight = EXCLUDED.working_weight,
                    best_estimated_1rm = EXCLUDED.best_estimated_1rm,
                    avg_intensity = EXCLUDED.avg_intensity,
                    score_units = EXCLUDED.score_units,
                    target_units = EXCLUDED.target_units,
                    rating_10 = EXCLUDED.rating_10,
                    algorithmic_effort = EXCLUDED.algorithmic_effort,
                    updated_at = now()
            """),
            rows
        )
        conn.commit()


def insert_daily_muscle_stats(rows: list[dict]):
    if not rows:
        return

    engine = get_engine()

    with engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO daily_muscle_stats
                (
                    user_id,
                    date,
                    muscle,
                    score_units,
                    target_units,
                    rating_10,
                    updated_at
                )
                VALUES
                (
                    :user_id,
                    :date,
                    :muscle,
                    :score_units,
                    :target_units,
                    :rating_10,
                    now()
                )
                ON CONFLICT (user_id, date, muscle)
                DO UPDATE SET
                    score_units = EXCLUDED.score_units,
                    target_units = EXCLUDED.target_units,
                    rating_10 = EXCLUDED.rating_10,
                    updated_at = now()
            """),
            rows
        )
        conn.commit()


def get_daily_exercise_stats(exercise: str):
    engine = get_engine()

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT
                    user_id,
                    date,
                    exercise,
                    exercise_type,
                    sets,
                    working_sets,
                    heavy_sets,
                    target_sets,
                    total_reps,
                    total_duration_sec,
                    total_volume,
                    max_weight,
                    working_weight,
                    best_estimated_1rm,
                    avg_intensity,
                    score_units,
                    target_units,
                    rating_10,
                    algorithmic_effort,
                    updated_at
                FROM daily_exercise_stats
                WHERE lower(exercise) = lower(:exercise)
                ORDER BY date
            """),
            {"exercise": exercise}
        )

        rows = result.mappings().all()

    return rows


def get_daily_muscle_stats(muscle: str):
    engine = get_engine()

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT
                    user_id,
                    date,
                    muscle,
                    score_units,
                    target_units,
                    rating_10,
                    updated_at
                FROM daily_muscle_stats
                WHERE lower(muscle) = lower(:muscle)
                ORDER BY date
            """),
            {"muscle": muscle}
        )

        rows = result.mappings().all()

    return rows

def get_exercise_aggregate_history(exercise: str):
    engine = get_engine()

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT
                    user_id,
                    date,
                    exercise,
                    exercise_type,
                    sets,
                    working_sets,
                    heavy_sets,
                    target_sets,
                    total_reps,
                    total_duration_sec,
                    total_volume,
                    max_weight,
                    working_weight,
                    best_estimated_1rm,
                    avg_intensity,
                    score_units,
                    target_units,
                    rating_10,
                    algorithmic_effort,
                    updated_at
                FROM daily_exercise_stats
                WHERE exercise = :exercise
                ORDER BY date
            """),
            {"exercise": exercise}
        )

        rows = result.mappings().all()

    return rows


def get_muscle_aggregate_history(muscle: str):
    engine = get_engine()

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT
                    user_id,
                    date,
                    muscle,
                    score_units,
                    target_units,
                    rating_10,
                    updated_at
                FROM daily_muscle_stats
                WHERE muscle = :muscle
                ORDER BY date
            """),
            {"muscle": muscle}
        )

        rows = result.mappings().all()

    return rows


def get_available_exercise_keys():
    engine = get_engine()

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT DISTINCT exercise
                FROM daily_exercise_stats
                ORDER BY exercise
            """)
        )

        rows = result.scalars().all()

    return list(rows)


def get_available_muscle_keys():
    engine = get_engine()

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT DISTINCT muscle
                FROM daily_muscle_stats
                ORDER BY muscle
            """)
        )

        rows = result.scalars().all()

    return list(rows)


def clear_daily_stats_for_date(training_date):
    engine = get_engine()

    with engine.connect() as conn:
        conn.execute(
            text("""
                DELETE FROM daily_exercise_stats
                WHERE date = :training_date
            """),
            {"training_date": training_date}
        )

        conn.execute(
            text("""
                DELETE FROM daily_muscle_stats
                WHERE date = :training_date
            """),
            {"training_date": training_date}
        )

        conn.commit()