from sqlalchemy import Engine, text


MIGRATIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "20260607_0001_profile_measurements_zones",
        (
            """
            CREATE TABLE IF NOT EXISTS athlete_profiles (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                date_of_birth DATE,
                sex VARCHAR(32) NOT NULL DEFAULT 'unspecified',
                height_cm DOUBLE PRECISION,
                weight_kg DOUBLE PRECISION,
                timezone VARCHAR(100) DEFAULT 'Europe/Moscow',
                locale VARCHAR(32) DEFAULT 'ru-RU',
                resting_heart_rate_bpm INTEGER,
                max_heart_rate_bpm INTEGER,
                max_hr_source VARCHAR(64),
                lactate_threshold_hr_bpm INTEGER,
                lactate_threshold_pace_seconds_per_km INTEGER,
                conservative_mode BOOLEAN NOT NULL DEFAULT FALSE,
                injury_notes TEXT,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                CONSTRAINT uq_athlete_profile_user UNIQUE (user_id)
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_athlete_profiles_user_id ON athlete_profiles (user_id)",
            """
            CREATE TABLE IF NOT EXISTS athlete_measurements (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                measurement_type VARCHAR(64) NOT NULL,
                measured_at TIMESTAMP WITH TIME ZONE,
                value_numeric DOUBLE PRECISION,
                value_json JSONB,
                source VARCHAR(64) NOT NULL DEFAULT 'manual',
                confidence DOUBLE PRECISION,
                notes TEXT,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_athlete_measurements_user_id ON athlete_measurements (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_athlete_measurements_measured_at ON athlete_measurements (measured_at)",
            """
            CREATE TABLE IF NOT EXISTS training_zones (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                zone_type VARCHAR(32) NOT NULL,
                method VARCHAR(64) NOT NULL,
                zone_key VARCHAR(64) NOT NULL,
                label VARCHAR(255),
                lower_value DOUBLE PRECISION,
                upper_value DOUBLE PRECISION,
                unit VARCHAR(64) NOT NULL,
                confidence VARCHAR(32) NOT NULL DEFAULT 'low',
                source_reference VARCHAR(255),
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                CONSTRAINT uq_user_zone_method_key UNIQUE (user_id, zone_type, method, zone_key)
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_training_zones_user_id ON training_zones (user_id)",
        ),
    ),
    (
        "20260607_0002_plan_execution_fields",
        (
            "ALTER TABLE training_plan_workouts ADD COLUMN IF NOT EXISTS scheduled_date DATE",
            "ALTER TABLE training_plan_workouts ADD COLUMN IF NOT EXISTS status VARCHAR(64) NOT NULL DEFAULT 'planned'",
            "ALTER TABLE training_plan_workouts ADD COLUMN IF NOT EXISTS completed_activity_id INTEGER",
            "CREATE INDEX IF NOT EXISTS ix_training_plan_workouts_scheduled_date ON training_plan_workouts (scheduled_date)",
            "CREATE INDEX IF NOT EXISTS ix_training_plan_workouts_completed_activity_id ON training_plan_workouts (completed_activity_id)",
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'fk_training_plan_workouts_completed_activity_id'
                ) THEN
                    ALTER TABLE training_plan_workouts
                    ADD CONSTRAINT fk_training_plan_workouts_completed_activity_id
                    FOREIGN KEY (completed_activity_id) REFERENCES activities(id) ON DELETE SET NULL;
                END IF;
            END $$
            """,
        ),
    ),
    (
        "20260607_0003_unique_workout_activity_links",
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_training_plan_workouts_completed_activity_id ON training_plan_workouts (completed_activity_id) WHERE completed_activity_id IS NOT NULL",
        ),
    ),
)


def run_migrations(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
            )
            """
        ))
        for version, statements in MIGRATIONS:
            applied = conn.execute(
                text("SELECT 1 FROM schema_migrations WHERE version = :version"),
                {"version": version},
            ).first()
            if applied:
                continue
            for statement in statements:
                conn.execute(text(statement))
            conn.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                {"version": version},
            )
