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
    (
        "20260607_0004_plan_recommendation_audits",
        (
            """
            CREATE TABLE IF NOT EXISTS training_plan_recommendation_audits (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                plan_id INTEGER NOT NULL REFERENCES training_plans(id) ON DELETE CASCADE,
                action VARCHAR(64) NOT NULL,
                status VARCHAR(64) NOT NULL DEFAULT 'applied',
                recommendations_snapshot JSONB,
                preview_changes JSONB,
                applied_changes JSONB,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_training_plan_recommendation_audits_user_id ON training_plan_recommendation_audits (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_training_plan_recommendation_audits_plan_id ON training_plan_recommendation_audits (plan_id)",
            "CREATE INDEX IF NOT EXISTS ix_training_plan_recommendation_audits_created_at ON training_plan_recommendation_audits (created_at)",
        ),
    ),
    (
        "20260607_0005_workout_completion_feedback",
        (
            """
            CREATE TABLE IF NOT EXISTS training_plan_workout_feedback (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                workout_id INTEGER NOT NULL REFERENCES training_plan_workouts(id) ON DELETE CASCADE,
                rpe INTEGER,
                fatigue INTEGER,
                pain BOOLEAN NOT NULL DEFAULT FALSE,
                pain_level INTEGER,
                sleep_quality INTEGER,
                notes TEXT,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                CONSTRAINT uq_training_plan_workout_feedback_workout UNIQUE (workout_id)
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_training_plan_workout_feedback_user_id ON training_plan_workout_feedback (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_training_plan_workout_feedback_workout_id ON training_plan_workout_feedback (workout_id)",
        ),
    ),
    (
        "20260607_0006_plan_target_time",
        (
            "ALTER TABLE training_plans ADD COLUMN IF NOT EXISTS target_time_seconds INTEGER",
        ),
    ),
    (
        "20260607_0007_workout_feedback_weather",
        (
            "ALTER TABLE training_plan_workout_feedback ADD COLUMN IF NOT EXISTS weather_notes TEXT",
        ),
    ),
    (
        "20260607_0008_performance_results",
        (
            """
            CREATE TABLE IF NOT EXISTS performance_results (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                activity_id INTEGER REFERENCES activities(id) ON DELETE SET NULL,
                result_type VARCHAR(32) NOT NULL DEFAULT 'race',
                name VARCHAR(255) NOT NULL,
                result_date TIMESTAMP WITH TIME ZONE NOT NULL,
                distance_km DOUBLE PRECISION NOT NULL,
                duration_seconds INTEGER NOT NULL,
                source VARCHAR(64) NOT NULL DEFAULT 'manual',
                terrain VARCHAR(64) NOT NULL DEFAULT 'road',
                weather VARCHAR(255),
                elevation_gain_m DOUBLE PRECISION,
                temperature_c DOUBLE PRECISION,
                is_noisy BOOLEAN NOT NULL DEFAULT FALSE,
                notes TEXT,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_performance_results_user_id ON performance_results (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_performance_results_activity_id ON performance_results (activity_id)",
            "CREATE INDEX IF NOT EXISTS ix_performance_results_result_date ON performance_results (result_date)",
            "CREATE INDEX IF NOT EXISTS ix_performance_results_user_date ON performance_results (user_id, result_date DESC)",
        ),
    ),
    (
        "20260608_0009_goal_race_fields",
        (
            "ALTER TABLE running_goals ADD COLUMN IF NOT EXISTS race_distance_km DOUBLE PRECISION",
            "ALTER TABLE running_goals ADD COLUMN IF NOT EXISTS target_date DATE",
            "ALTER TABLE running_goals ADD COLUMN IF NOT EXISTS target_time_seconds INTEGER",
            "ALTER TABLE running_goals ADD COLUMN IF NOT EXISTS priority VARCHAR(16)",
            "ALTER TABLE running_goals ADD COLUMN IF NOT EXISTS course_notes TEXT",
            "ALTER TABLE running_goals ADD COLUMN IF NOT EXISTS training_plan_id INTEGER",
            "CREATE INDEX IF NOT EXISTS ix_running_goals_target_date ON running_goals (target_date)",
            "CREATE INDEX IF NOT EXISTS ix_running_goals_training_plan_id ON running_goals (training_plan_id)",
            "CREATE INDEX IF NOT EXISTS ix_running_goals_user_status_target ON running_goals (user_id, status, target_date)",
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'fk_running_goals_training_plan_id'
                ) THEN
                    ALTER TABLE running_goals
                    ADD CONSTRAINT fk_running_goals_training_plan_id
                    FOREIGN KEY (training_plan_id) REFERENCES training_plans(id) ON DELETE SET NULL;
                END IF;
            END $$
            """,
        ),
    ),
    (
        "20260608_0010_profile_preferences_safety",
        (
            "ALTER TABLE athlete_profiles ADD COLUMN IF NOT EXISTS unit_system VARCHAR(16) NOT NULL DEFAULT 'metric'",
            "ALTER TABLE athlete_profiles ADD COLUMN IF NOT EXISTS preferred_weekdays JSONB",
            "ALTER TABLE athlete_profiles ADD COLUMN IF NOT EXISTS long_run_weekday INTEGER",
            "ALTER TABLE athlete_profiles ADD COLUMN IF NOT EXISTS max_run_duration_minutes INTEGER",
            "ALTER TABLE athlete_profiles ADD COLUMN IF NOT EXISTS vo2max DOUBLE PRECISION",
            "ALTER TABLE athlete_profiles ADD COLUMN IF NOT EXISTS health_conditions TEXT",
            "ALTER TABLE athlete_profiles ADD COLUMN IF NOT EXISTS recovery_status VARCHAR(32) NOT NULL DEFAULT 'normal'",
        ),
    ),
    (
        "20260608_0011_audit_log",
        (
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                action VARCHAR(64) NOT NULL,
                entity_type VARCHAR(64) NOT NULL,
                entity_id INTEGER,
                metadata_json JSONB,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_audit_log_user_id ON audit_log (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_audit_log_created_at ON audit_log (created_at)",
        ),
    ),
    (
        "20260608_0012_plan_versions",
        (
            """
            CREATE TABLE IF NOT EXISTS plan_versions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                plan_id INTEGER NOT NULL REFERENCES training_plans(id) ON DELETE CASCADE,
                version_number INTEGER NOT NULL,
                reason VARCHAR(64) NOT NULL,
                summary TEXT,
                snapshot_json JSONB,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                CONSTRAINT uq_plan_versions_plan_number UNIQUE (plan_id, version_number)
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_plan_versions_user_id ON plan_versions (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_plan_versions_plan_id ON plan_versions (plan_id)",
            "CREATE INDEX IF NOT EXISTS ix_plan_versions_created_at ON plan_versions (created_at)",
        ),
    ),
    (
        "20260608_0013_planned_workout_blocks_derived_metrics",
        (
            """
            CREATE TABLE IF NOT EXISTS planned_workout_blocks (
                id SERIAL PRIMARY KEY,
                workout_id INTEGER NOT NULL REFERENCES training_plan_workouts(id) ON DELETE CASCADE,
                block_index INTEGER NOT NULL,
                block_type VARCHAR(64) NOT NULL,
                repeat_count INTEGER NOT NULL DEFAULT 1,
                target_distance_km DOUBLE PRECISION,
                target_duration_seconds INTEGER,
                target_pace_min_seconds_per_km INTEGER,
                target_pace_max_seconds_per_km INTEGER,
                target_hr_min_bpm INTEGER,
                target_hr_max_bpm INTEGER,
                target_rpe_min INTEGER,
                target_rpe_max INTEGER,
                description TEXT,
                CONSTRAINT uq_planned_workout_block UNIQUE (workout_id, block_index)
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_planned_workout_blocks_workout_id ON planned_workout_blocks (workout_id)",
            """
            CREATE TABLE IF NOT EXISTS derived_activity_metrics (
                activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
                metric_key VARCHAR(100) NOT NULL,
                metric_value DOUBLE PRECISION NOT NULL,
                unit VARCHAR(64) NOT NULL,
                method VARCHAR(64) NOT NULL,
                source_reference VARCHAR(255),
                input_hash VARCHAR(64) NOT NULL,
                computed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                PRIMARY KEY (activity_id, metric_key),
                CONSTRAINT uq_derived_activity_metric UNIQUE (activity_id, metric_key)
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_derived_activity_metrics_activity_id ON derived_activity_metrics (activity_id)",
            "CREATE INDEX IF NOT EXISTS ix_derived_activity_metrics_computed_at ON derived_activity_metrics (computed_at)",
        ),
    ),
    (
        "20260608_0014_daily_training_loads",
        (
            """
            CREATE TABLE IF NOT EXISTS daily_training_loads (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                date DATE NOT NULL,
                load_value DOUBLE PRECISION NOT NULL DEFAULT 0,
                method VARCHAR(64) NOT NULL DEFAULT 'unavailable',
                duration_minutes DOUBLE PRECISION NOT NULL DEFAULT 0,
                activity_ids JSON,
                ctl DOUBLE PRECISION,
                atl DOUBLE PRECISION,
                tsb DOUBLE PRECISION,
                monotony_window_value DOUBLE PRECISION,
                strain_window_value DOUBLE PRECISION,
                computed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                PRIMARY KEY (user_id, date)
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_daily_training_loads_user_id ON daily_training_loads (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_daily_training_loads_date ON daily_training_loads (date)",
            "CREATE INDEX IF NOT EXISTS ix_daily_training_loads_user_date ON daily_training_loads (user_id, date)",
            "CREATE INDEX IF NOT EXISTS ix_daily_training_loads_computed_at ON daily_training_loads (computed_at)",
        ),
    ),
    (
        "20260608_0015_workout_feedback_spec_fields",
        (
            "ALTER TABLE training_plan_workout_feedback ADD COLUMN IF NOT EXISTS activity_id INTEGER REFERENCES activities(id) ON DELETE SET NULL",
            "ALTER TABLE training_plan_workout_feedback ADD COLUMN IF NOT EXISTS completion_status VARCHAR(32)",
            "ALTER TABLE training_plan_workout_feedback ADD COLUMN IF NOT EXISTS soreness_0_10 INTEGER",
            "ALTER TABLE training_plan_workout_feedback ADD COLUMN IF NOT EXISTS sleep_quality_0_10 INTEGER",
            "ALTER TABLE training_plan_workout_feedback ADD COLUMN IF NOT EXISTS pain_notes TEXT",
            "ALTER TABLE training_plan_workout_feedback ADD COLUMN IF NOT EXISTS user_notes TEXT",
            "CREATE INDEX IF NOT EXISTS ix_training_plan_workout_feedback_activity_id ON training_plan_workout_feedback (activity_id)",
            "UPDATE training_plan_workout_feedback SET soreness_0_10 = COALESCE(soreness_0_10, fatigue), sleep_quality_0_10 = COALESCE(sleep_quality_0_10, sleep_quality), user_notes = COALESCE(user_notes, notes)",
            "UPDATE training_plan_workout_feedback AS feedback SET activity_id = workouts.completed_activity_id, completion_status = workouts.status FROM training_plan_workouts AS workouts WHERE feedback.workout_id = workouts.id AND (feedback.activity_id IS NULL OR feedback.completion_status IS NULL)",
        ),
    ),
    (
        "20260609_0016_telegram_bot_login_codes",
        (
            "ALTER TABLE users ALTER COLUMN telegram_id TYPE BIGINT",
            """
            CREATE TABLE IF NOT EXISTS telegram_login_codes (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                telegram_id BIGINT NOT NULL,
                code_hash VARCHAR(128) NOT NULL UNIQUE,
                expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                used_at TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_telegram_login_codes_user_id ON telegram_login_codes (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_telegram_login_codes_telegram_id ON telegram_login_codes (telegram_id)",
            "CREATE INDEX IF NOT EXISTS ix_telegram_login_codes_code_hash ON telegram_login_codes (code_hash)",
            "CREATE INDEX IF NOT EXISTS ix_telegram_login_codes_expires_at ON telegram_login_codes (expires_at)",
        ),
    ),
    (
        "20260702_0017_screenshot_content_hash",
        (
            "ALTER TABLE screenshot_sources ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)",
            "CREATE INDEX IF NOT EXISTS ix_screenshot_sources_content_hash ON screenshot_sources (content_hash)",
            "CREATE INDEX IF NOT EXISTS ix_screenshot_sources_user_content_hash ON screenshot_sources (user_id, content_hash)",
        ),
    ),
    (
        "20260703_0018_import_recognition_queue",
        (
            "ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS queued_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS recognition_started_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS recognition_finished_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS recognition_retry_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS recognition_attempt_count INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS recognition_max_attempts INTEGER NOT NULL DEFAULT 3",
            "ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS recognition_locked_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS recognition_locked_by VARCHAR(100)",
            "ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS recognition_last_error TEXT",
            "CREATE INDEX IF NOT EXISTS ix_import_batches_queued_at ON import_batches (queued_at)",
            "CREATE INDEX IF NOT EXISTS ix_import_batches_recognition_retry_at ON import_batches (recognition_retry_at)",
            "CREATE INDEX IF NOT EXISTS ix_import_batches_recognition_locked_at ON import_batches (recognition_locked_at)",
            "CREATE INDEX IF NOT EXISTS ix_import_batches_recognition_queue ON import_batches (status, recognition_retry_at, queued_at)",
            "ALTER TABLE import_recognition_attempts ADD COLUMN IF NOT EXISTS provider_id INTEGER",
            "ALTER TABLE import_recognition_attempts ADD COLUMN IF NOT EXISTS model VARCHAR(255)",
            "ALTER TABLE import_recognition_attempts ADD COLUMN IF NOT EXISTS attempt_number INTEGER",
            "ALTER TABLE import_recognition_attempts ADD COLUMN IF NOT EXISTS duration_ms INTEGER",
            "ALTER TABLE import_recognition_attempts ADD COLUMN IF NOT EXISTS failure_class VARCHAR(64)",
            "CREATE INDEX IF NOT EXISTS ix_import_recognition_attempts_provider_id ON import_recognition_attempts (provider_id)",
        ),
    ),
    (
        "20260712_0019_single_current_training_plan",
        (
            """
            WITH ranked AS (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY user_id
                    ORDER BY CASE WHEN status = 'active' THEN 0 ELSE 1 END, created_at DESC, id DESC
                ) AS position
                FROM training_plans
                WHERE status IN ('active', 'draft')
            )
            UPDATE training_plans
            SET status = 'archived'
            WHERE id IN (SELECT id FROM ranked WHERE position > 1)
            """,
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_training_plans_one_current_per_user ON training_plans (user_id) WHERE status IN ('active', 'draft')",
        ),
    ),
    (
        "20260712_0020_daily_readiness_checkins",
        (
            """
            CREATE TABLE IF NOT EXISTS daily_readiness_checkins (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                checkin_date DATE NOT NULL,
                sleep_quality_0_10 INTEGER,
                fatigue_0_10 INTEGER,
                soreness_0_10 INTEGER,
                stress_0_10 INTEGER,
                pain BOOLEAN NOT NULL DEFAULT FALSE,
                pain_level_0_10 INTEGER,
                pain_notes TEXT,
                illness_symptoms BOOLEAN NOT NULL DEFAULT FALSE,
                illness_notes TEXT,
                notes TEXT,
                recommendation_snapshot JSONB,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                CONSTRAINT uq_daily_readiness_checkins_user_date UNIQUE (user_id, checkin_date)
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_daily_readiness_checkins_user_id ON daily_readiness_checkins (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_daily_readiness_checkins_checkin_date ON daily_readiness_checkins (checkin_date)",
            "CREATE INDEX IF NOT EXISTS ix_daily_readiness_checkins_user_date ON daily_readiness_checkins (user_id, checkin_date)",
        ),
    ),
    (
        "20260712_0021_daily_readiness_action_previews",
        (
            """
            CREATE TABLE IF NOT EXISTS daily_readiness_action_previews (
                id VARCHAR(64) PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                plan_id INTEGER NOT NULL REFERENCES training_plans(id) ON DELETE CASCADE,
                workout_id INTEGER NOT NULL REFERENCES training_plan_workouts(id) ON DELETE CASCADE,
                checkin_id INTEGER NOT NULL REFERENCES daily_readiness_checkins(id) ON DELETE CASCADE,
                checkin_date DATE NOT NULL,
                action VARCHAR(64) NOT NULL,
                rule_version VARCHAR(64) NOT NULL,
                recommendation_snapshot JSONB NOT NULL,
                preview_snapshot JSONB NOT NULL,
                state_fingerprint VARCHAR(64) NOT NULL,
                expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                applied_at TIMESTAMP WITH TIME ZONE,
                recommendation_audit_id INTEGER REFERENCES training_plan_recommendation_audits(id) ON DELETE SET NULL,
                plan_version_id INTEGER REFERENCES plan_versions(id) ON DELETE SET NULL,
                audit_log_id INTEGER REFERENCES audit_log(id) ON DELETE SET NULL,
                applied_response_json JSONB,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_daily_readiness_action_previews_user_id ON daily_readiness_action_previews (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_daily_readiness_action_previews_plan_id ON daily_readiness_action_previews (plan_id)",
            "CREATE INDEX IF NOT EXISTS ix_daily_readiness_action_previews_workout_id ON daily_readiness_action_previews (workout_id)",
            "CREATE INDEX IF NOT EXISTS ix_daily_readiness_action_previews_checkin_id ON daily_readiness_action_previews (checkin_id)",
            "CREATE INDEX IF NOT EXISTS ix_daily_readiness_action_previews_checkin_date ON daily_readiness_action_previews (checkin_date)",
            "CREATE INDEX IF NOT EXISTS ix_daily_readiness_action_previews_expires_at ON daily_readiness_action_previews (expires_at)",
        ),
    ),
    (
        "20260712_0022_coaching_events",
        (
            """
            CREATE TABLE IF NOT EXISTS coaching_events (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                event_type VARCHAR(64) NOT NULL,
                event_version VARCHAR(32) NOT NULL DEFAULT 'v1',
                category VARCHAR(32) NOT NULL,
                source VARCHAR(64) NOT NULL,
                occurred_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                plan_id INTEGER REFERENCES training_plans(id) ON DELETE SET NULL,
                workout_id INTEGER REFERENCES training_plan_workouts(id) ON DELETE SET NULL,
                activity_id INTEGER REFERENCES activities(id) ON DELETE SET NULL,
                checkin_id INTEGER REFERENCES daily_readiness_checkins(id) ON DELETE SET NULL,
                feedback_id INTEGER REFERENCES training_plan_workout_feedback(id) ON DELETE SET NULL,
                correlation_id VARCHAR(128),
                payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_coaching_events_user_id ON coaching_events (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_coaching_events_event_type ON coaching_events (event_type)",
            "CREATE INDEX IF NOT EXISTS ix_coaching_events_occurred_at ON coaching_events (occurred_at)",
            "CREATE INDEX IF NOT EXISTS ix_coaching_events_user_occurred ON coaching_events (user_id, occurred_at DESC, id DESC)",
            "CREATE INDEX IF NOT EXISTS ix_coaching_events_plan_id ON coaching_events (plan_id)",
            "CREATE INDEX IF NOT EXISTS ix_coaching_events_workout_id ON coaching_events (workout_id)",
            "CREATE INDEX IF NOT EXISTS ix_coaching_events_activity_id ON coaching_events (activity_id)",
            "CREATE INDEX IF NOT EXISTS ix_coaching_events_checkin_id ON coaching_events (checkin_id)",
            "CREATE INDEX IF NOT EXISTS ix_coaching_events_feedback_id ON coaching_events (feedback_id)",
            "CREATE INDEX IF NOT EXISTS ix_coaching_events_correlation_id ON coaching_events (correlation_id)",
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
