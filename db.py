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