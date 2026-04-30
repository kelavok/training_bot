from sqlalchemy import create_engine, text

from config import DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME


def get_engine():
    return create_engine(
        f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )


def test_connection():
    engine = get_engine()

    with engine.connect() as conn:
        result = conn.execute(text("SELECT current_database();"))
        db_name = result.scalar()

    return db_name


def insert_workout_rows(rows: list[dict]):
    engine = get_engine()

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