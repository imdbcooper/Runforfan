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
    (
        "20260712_0023_athlete_state_snapshots",
        (
            """
            CREATE TABLE IF NOT EXISTS athlete_state_snapshots (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                local_date DATE NOT NULL,
                timezone VARCHAR(100) NOT NULL,
                state_version VARCHAR(64) NOT NULL,
                rule_version VARCHAR(64) NOT NULL,
                input_fingerprint VARCHAR(64) NOT NULL,
                snapshot_json JSONB NOT NULL,
                as_of_at TIMESTAMP WITH TIME ZONE NOT NULL,
                computed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                trigger_type VARCHAR(64) NOT NULL DEFAULT 'on_read',
                CONSTRAINT uq_athlete_state_snapshot_input UNIQUE (user_id, local_date, state_version, input_fingerprint)
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_athlete_state_snapshots_user_id ON athlete_state_snapshots (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_athlete_state_snapshots_local_date ON athlete_state_snapshots (local_date)",
            "CREATE INDEX IF NOT EXISTS ix_athlete_state_snapshots_computed_at ON athlete_state_snapshots (computed_at)",
            "CREATE INDEX IF NOT EXISTS ix_athlete_state_snapshots_user_date ON athlete_state_snapshots (user_id, local_date DESC, id DESC)",
        ),
    ),
    (
        "20260712_0024_coach_action_previews",
        (
            """
            CREATE TABLE IF NOT EXISTS coach_action_previews (
                id VARCHAR(64) PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                plan_id INTEGER NOT NULL REFERENCES training_plans(id) ON DELETE CASCADE,
                workout_id INTEGER NOT NULL REFERENCES training_plan_workouts(id) ON DELETE CASCADE,
                action VARCHAR(64) NOT NULL,
                rule_version VARCHAR(64) NOT NULL,
                request_snapshot JSONB NOT NULL,
                preview_snapshot JSONB NOT NULL,
                state_fingerprint VARCHAR(64) NOT NULL,
                expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                applied_at TIMESTAMP WITH TIME ZONE,
                recommendation_audit_id INTEGER REFERENCES training_plan_recommendation_audits(id) ON DELETE SET NULL,
                plan_version_id INTEGER REFERENCES plan_versions(id) ON DELETE SET NULL,
                audit_log_id INTEGER REFERENCES audit_log(id) ON DELETE SET NULL,
                coaching_event_id INTEGER REFERENCES coaching_events(id) ON DELETE SET NULL,
                applied_response_json JSONB,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_coach_action_previews_user_id ON coach_action_previews (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_coach_action_previews_plan_id ON coach_action_previews (plan_id)",
            "CREATE INDEX IF NOT EXISTS ix_coach_action_previews_workout_id ON coach_action_previews (workout_id)",
            "CREATE INDEX IF NOT EXISTS ix_coach_action_previews_expires_at ON coach_action_previews (expires_at)",
        ),
    ),
    (
        "20260713_0025_plan_rollback_and_recalculation",
        (
            "ALTER TABLE plan_versions ADD COLUMN IF NOT EXISTS pre_snapshot_json JSONB",
            "ALTER TABLE plan_versions ADD COLUMN IF NOT EXISTS post_snapshot_json JSONB",
            "ALTER TABLE plan_versions ADD COLUMN IF NOT EXISTS rollback_of_version_id INTEGER REFERENCES plan_versions(id) ON DELETE SET NULL",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_plan_versions_rollback_of ON plan_versions (rollback_of_version_id) WHERE rollback_of_version_id IS NOT NULL",
            """
            CREATE TABLE IF NOT EXISTS plan_rollback_previews (
                id VARCHAR(64) PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                plan_id INTEGER NOT NULL REFERENCES training_plans(id) ON DELETE CASCADE,
                version_id INTEGER NOT NULL REFERENCES plan_versions(id) ON DELETE CASCADE,
                preview_snapshot JSONB NOT NULL,
                state_fingerprint VARCHAR(64) NOT NULL,
                expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                applied_at TIMESTAMP WITH TIME ZONE,
                rollback_version_id INTEGER REFERENCES plan_versions(id) ON DELETE SET NULL,
                recommendation_audit_id INTEGER REFERENCES training_plan_recommendation_audits(id) ON DELETE SET NULL,
                audit_log_id INTEGER REFERENCES audit_log(id) ON DELETE SET NULL,
                coaching_event_id INTEGER REFERENCES coaching_events(id) ON DELETE SET NULL,
                applied_response_json JSONB,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_plan_rollback_previews_user_id ON plan_rollback_previews (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_plan_rollback_previews_plan_id ON plan_rollback_previews (plan_id)",
            "CREATE INDEX IF NOT EXISTS ix_plan_rollback_previews_version_id ON plan_rollback_previews (version_id)",
            "CREATE INDEX IF NOT EXISTS ix_plan_rollback_previews_expires_at ON plan_rollback_previews (expires_at)",
            """
            CREATE TABLE IF NOT EXISTS plan_recalculation_requests (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                plan_id INTEGER REFERENCES training_plans(id) ON DELETE SET NULL,
                trigger_type VARCHAR(64) NOT NULL,
                source_key VARCHAR(160) NOT NULL,
                source_event_id INTEGER REFERENCES coaching_events(id) ON DELETE SET NULL,
                input_fingerprint VARCHAR(64) NOT NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'completed',
                assessment_json JSONB NOT NULL,
                requested_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                completed_at TIMESTAMP WITH TIME ZONE,
                CONSTRAINT uq_plan_recalculation_user_source UNIQUE (user_id, source_key)
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_plan_recalculation_requests_user_id ON plan_recalculation_requests (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_plan_recalculation_requests_plan_id ON plan_recalculation_requests (plan_id)",
            "CREATE INDEX IF NOT EXISTS ix_plan_recalculation_requests_trigger_type ON plan_recalculation_requests (trigger_type)",
            "CREATE INDEX IF NOT EXISTS ix_plan_recalculation_requests_source_event_id ON plan_recalculation_requests (source_event_id)",
            "CREATE INDEX IF NOT EXISTS ix_plan_recalculation_requests_status ON plan_recalculation_requests (status)",
            "CREATE INDEX IF NOT EXISTS ix_plan_recalculation_requests_requested_at ON plan_recalculation_requests (requested_at)",
        ),
    ),
    (
        "20260713_0026_weekly_reviews",
        (
            """
            CREATE TABLE IF NOT EXISTS weekly_reviews (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                plan_id INTEGER REFERENCES training_plans(id) ON DELETE SET NULL,
                week_start DATE NOT NULL,
                week_end DATE NOT NULL,
                timezone VARCHAR(100) NOT NULL,
                review_version VARCHAR(64) NOT NULL,
                rule_version VARCHAR(64) NOT NULL,
                input_fingerprint VARCHAR(64) NOT NULL,
                resolution_status VARCHAR(32) NOT NULL,
                snapshot_json JSONB NOT NULL,
                as_of_at TIMESTAMP WITH TIME ZONE NOT NULL,
                computed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                trigger_type VARCHAR(64) NOT NULL DEFAULT 'on_read',
                CONSTRAINT uq_weekly_review_input UNIQUE (user_id, week_start, review_version, input_fingerprint)
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_weekly_reviews_user_id ON weekly_reviews (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_weekly_reviews_plan_id ON weekly_reviews (plan_id)",
            "CREATE INDEX IF NOT EXISTS ix_weekly_reviews_week_start ON weekly_reviews (week_start)",
            "CREATE INDEX IF NOT EXISTS ix_weekly_reviews_resolution_status ON weekly_reviews (resolution_status)",
            "CREATE INDEX IF NOT EXISTS ix_weekly_reviews_computed_at ON weekly_reviews (computed_at)",
            "CREATE INDEX IF NOT EXISTS ix_weekly_reviews_user_week ON weekly_reviews (user_id, week_start DESC, id DESC)",
            """
            CREATE TABLE IF NOT EXISTS weekly_strategy_previews (
                id VARCHAR(64) PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                review_id INTEGER NOT NULL REFERENCES weekly_reviews(id) ON DELETE CASCADE,
                plan_id INTEGER NOT NULL REFERENCES training_plans(id) ON DELETE CASCADE,
                strategy VARCHAR(64) NOT NULL,
                rule_version VARCHAR(64) NOT NULL,
                request_snapshot JSONB NOT NULL,
                preview_snapshot JSONB NOT NULL,
                state_fingerprint VARCHAR(64) NOT NULL,
                expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                applied_at TIMESTAMP WITH TIME ZONE,
                recommendation_audit_id INTEGER REFERENCES training_plan_recommendation_audits(id) ON DELETE SET NULL,
                plan_version_id INTEGER REFERENCES plan_versions(id) ON DELETE SET NULL,
                audit_log_id INTEGER REFERENCES audit_log(id) ON DELETE SET NULL,
                coaching_event_id INTEGER REFERENCES coaching_events(id) ON DELETE SET NULL,
                applied_response_json JSONB,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_weekly_strategy_previews_user_id ON weekly_strategy_previews (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_weekly_strategy_previews_review_id ON weekly_strategy_previews (review_id)",
            "CREATE INDEX IF NOT EXISTS ix_weekly_strategy_previews_plan_id ON weekly_strategy_previews (plan_id)",
            "CREATE INDEX IF NOT EXISTS ix_weekly_strategy_previews_strategy ON weekly_strategy_previews (strategy)",
            "CREATE INDEX IF NOT EXISTS ix_weekly_strategy_previews_expires_at ON weekly_strategy_previews (expires_at)",
        ),
    ),
    (
        "20260713_0027_conversational_coach",
        (
            """
            CREATE TABLE IF NOT EXISTS coach_conversations (
                id VARCHAR(64) PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                status VARCHAR(32) NOT NULL,
                surface VARCHAR(64) NOT NULL,
                title VARCHAR(255),
                last_message_at TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                CONSTRAINT ck_coach_conversations_status CHECK (status IN ('active', 'archived')),
                CONSTRAINT ck_coach_conversations_surface CHECK (surface IN ('overview')),
                CONSTRAINT uq_coach_conversations_id_user UNIQUE (id, user_id)
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_coach_conversations_user_id ON coach_conversations (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_coach_conversations_status ON coach_conversations (status)",
            "CREATE INDEX IF NOT EXISTS ix_coach_conversations_last_message_at ON coach_conversations (last_message_at)",
            "CREATE INDEX IF NOT EXISTS ix_coach_conversations_user_created ON coach_conversations (user_id, created_at DESC, id DESC)",
            """
            CREATE TABLE IF NOT EXISTS coach_messages (
                id BIGSERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                conversation_id VARCHAR(64) NOT NULL,
                role VARCHAR(32) NOT NULL,
                turn_status VARCHAR(32) NOT NULL DEFAULT 'completed',
                content TEXT,
                content_redacted BOOLEAN NOT NULL DEFAULT FALSE,
                response_json JSONB,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                CONSTRAINT ck_coach_messages_role CHECK (role IN ('user', 'assistant')),
                CONSTRAINT ck_coach_messages_turn_status CHECK (turn_status IN ('pending', 'completed')),
                CONSTRAINT ck_coach_messages_assistant_completed CHECK (role = 'user' OR turn_status = 'completed'),
                CONSTRAINT fk_coach_messages_conversation_owner FOREIGN KEY (conversation_id, user_id) REFERENCES coach_conversations(id, user_id) ON DELETE CASCADE,
                CONSTRAINT uq_coach_messages_id_user UNIQUE (id, user_id),
                CONSTRAINT uq_coach_messages_id_user_conversation UNIQUE (id, user_id, conversation_id)
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_coach_messages_user_id ON coach_messages (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_coach_messages_conversation_id ON coach_messages (conversation_id)",
            "CREATE INDEX IF NOT EXISTS ix_coach_messages_turn_status ON coach_messages (turn_status)",
            "CREATE INDEX IF NOT EXISTS ix_coach_messages_conversation_created ON coach_messages (conversation_id, created_at ASC, id ASC)",
            """
            CREATE TABLE IF NOT EXISTS coach_memory (
                id BIGSERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                memory_key VARCHAR(128) NOT NULL,
                value_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                status VARCHAR(32) NOT NULL DEFAULT 'confirmed',
                source_message_id BIGINT,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                CONSTRAINT ck_coach_memory_key CHECK (memory_key IN ('communication_style', 'coaching_focus', 'confirmed_available_days')),
                CONSTRAINT ck_coach_memory_status CHECK (status IN ('confirmed')),
                CONSTRAINT fk_coach_memory_source_owner FOREIGN KEY (source_message_id, user_id) REFERENCES coach_messages(id, user_id) ON DELETE CASCADE,
                CONSTRAINT uq_coach_memory_user_key UNIQUE (user_id, memory_key)
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_coach_memory_user_id ON coach_memory (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_coach_memory_source_message_id ON coach_memory (source_message_id)",
            """
            CREATE TABLE IF NOT EXISTS coach_llm_attempts (
                id BIGSERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                conversation_id VARCHAR(64) NOT NULL,
                message_id BIGINT NOT NULL,
                provider VARCHAR(64) NOT NULL,
                provider_id INTEGER REFERENCES llm_provider_settings(id) ON DELETE SET NULL,
                model VARCHAR(255),
                attempt_number INTEGER NOT NULL,
                request_phase VARCHAR(32) NOT NULL,
                status VARCHAR(32) NOT NULL,
                failure_class VARCHAR(64),
                started_at TIMESTAMP WITH TIME ZONE,
                completed_at TIMESTAMP WITH TIME ZONE,
                duration_ms INTEGER,
                request_fingerprint VARCHAR(128),
                output_fingerprint VARCHAR(128),
                validation_errors JSONB,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                CONSTRAINT ck_coach_llm_attempt_number CHECK (attempt_number > 0),
                CONSTRAINT ck_coach_llm_attempt_status CHECK (status IN ('success', 'failed')),
                CONSTRAINT ck_coach_llm_attempt_phase CHECK (request_phase IN ('initial', 'repair')),
                CONSTRAINT ck_coach_llm_attempt_duration CHECK (duration_ms IS NULL OR duration_ms >= 0),
                CONSTRAINT fk_coach_llm_attempt_conversation_owner FOREIGN KEY (conversation_id, user_id) REFERENCES coach_conversations(id, user_id) ON DELETE CASCADE,
                CONSTRAINT fk_coach_llm_attempt_message_owner FOREIGN KEY (message_id, user_id, conversation_id) REFERENCES coach_messages(id, user_id, conversation_id) ON DELETE CASCADE
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_coach_llm_attempts_user_id ON coach_llm_attempts (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_coach_llm_attempts_conversation_id ON coach_llm_attempts (conversation_id)",
            "CREATE INDEX IF NOT EXISTS ix_coach_llm_attempts_message_id ON coach_llm_attempts (message_id)",
            "CREATE INDEX IF NOT EXISTS ix_coach_llm_attempts_status ON coach_llm_attempts (status)",
            "CREATE INDEX IF NOT EXISTS ix_coach_llm_attempts_user_created ON coach_llm_attempts (user_id, created_at DESC, id DESC)",
        ),
    ),
    (
        "20260714_0028_recovery_signal_observations",
        (
            "ALTER TABLE daily_readiness_checkins ADD COLUMN IF NOT EXISTS weather_condition VARCHAR(32)",
            "ALTER TABLE daily_readiness_checkins ADD COLUMN IF NOT EXISTS surface_condition VARCHAR(32)",
            "ALTER TABLE daily_readiness_checkins ADD COLUMN IF NOT EXISTS available_time_minutes INTEGER",
            "ALTER TABLE daily_readiness_checkins DROP CONSTRAINT IF EXISTS ck_daily_readiness_weather_condition",
            "ALTER TABLE daily_readiness_checkins ADD CONSTRAINT ck_daily_readiness_weather_condition CHECK (weather_condition IS NULL OR weather_condition IN ('normal', 'heat', 'cold', 'storm', 'poor_air'))",
            "ALTER TABLE daily_readiness_checkins DROP CONSTRAINT IF EXISTS ck_daily_readiness_surface_condition",
            "ALTER TABLE daily_readiness_checkins ADD CONSTRAINT ck_daily_readiness_surface_condition CHECK (surface_condition IS NULL OR surface_condition IN ('dry', 'wet', 'icy', 'uneven'))",
            "ALTER TABLE daily_readiness_checkins DROP CONSTRAINT IF EXISTS ck_daily_readiness_available_time",
            "ALTER TABLE daily_readiness_checkins ADD CONSTRAINT ck_daily_readiness_available_time CHECK (available_time_minutes IS NULL OR (available_time_minutes >= 0 AND available_time_minutes <= 600))",
            """
            CREATE TABLE IF NOT EXISTS recovery_signal_observations (
                id BIGSERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                metric_key VARCHAR(64) NOT NULL,
                value_numeric DOUBLE PRECISION NOT NULL,
                unit VARCHAR(32) NOT NULL,
                observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
                received_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                source_kind VARCHAR(32) NOT NULL,
                source_system VARCHAR(64) NOT NULL,
                source_label VARCHAR(100) NOT NULL,
                source_record_id VARCHAR(255) NOT NULL,
                quality VARCHAR(16) NOT NULL,
                quality_score DOUBLE PRECISION,
                normalization_version VARCHAR(64) NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                CONSTRAINT ck_recovery_signal_metric_key CHECK (metric_key IN ('sleep_duration_seconds', 'sleep_efficiency_pct', 'hrv_rmssd_ms', 'resting_heart_rate_bpm')),
                CONSTRAINT ck_recovery_signal_unit CHECK (unit IN ('seconds', 'percent', 'ms', 'bpm')),
                CONSTRAINT ck_recovery_signal_source_kind CHECK (source_kind IN ('manual', 'device_import', 'partner_sync')),
                CONSTRAINT ck_recovery_signal_quality CHECK (quality IN ('high', 'medium', 'low')),
                CONSTRAINT ck_recovery_signal_quality_score CHECK (quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 1)),
                CONSTRAINT ck_recovery_signal_observed_received CHECK (observed_at <= received_at),
                CONSTRAINT uq_recovery_signal_source_record UNIQUE (user_id, source_system, metric_key, source_record_id)
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_recovery_signal_observations_user_id ON recovery_signal_observations (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_recovery_signal_observations_metric_key ON recovery_signal_observations (metric_key)",
            "CREATE INDEX IF NOT EXISTS ix_recovery_signal_observations_observed_at ON recovery_signal_observations (observed_at)",
            "CREATE INDEX IF NOT EXISTS ix_recovery_signal_observations_received_at ON recovery_signal_observations (received_at)",
            "CREATE INDEX IF NOT EXISTS ix_recovery_signal_user_metric_observed ON recovery_signal_observations (user_id, metric_key, observed_at DESC, id DESC)",
            "CREATE INDEX IF NOT EXISTS ix_recovery_signal_user_received ON recovery_signal_observations (user_id, received_at DESC, id DESC)",
            """
            CREATE TABLE IF NOT EXISTS upload_deletion_jobs (
                id BIGSERIAL PRIMARY KEY,
                staged_name VARCHAR(100) NOT NULL,
                file_count INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                CONSTRAINT ck_upload_deletion_job_file_count CHECK (file_count >= 0),
                CONSTRAINT uq_upload_deletion_job_staged_name UNIQUE (staged_name)
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_upload_deletion_jobs_created_at ON upload_deletion_jobs (created_at)",
        ),
    ),
    (
        "20260714_0029_coach_delivery",
        (
            """
            CREATE TABLE IF NOT EXISTS coach_delivery_preferences (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                telegram_chat_id BIGINT,
                telegram_chat_verified_at TIMESTAMP WITH TIME ZONE,
                telegram_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                daily_brief_local_time TIME NOT NULL DEFAULT '08:00:00',
                enabled_at TIMESTAMP WITH TIME ZONE,
                disabled_at TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                CONSTRAINT ck_coach_delivery_preference_enabled_destination CHECK (NOT telegram_enabled OR (telegram_chat_id IS NOT NULL AND telegram_chat_verified_at IS NOT NULL))
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_coach_delivery_preferences_user_id ON coach_delivery_preferences (user_id)",
            """
            CREATE TABLE IF NOT EXISTS coach_deliveries (
                id VARCHAR(64) PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                channel VARCHAR(32) NOT NULL DEFAULT 'telegram',
                delivery_type VARCHAR(32) NOT NULL DEFAULT 'daily_brief',
                local_date DATE NOT NULL,
                timezone VARCHAR(100) NOT NULL,
                rule_version VARCHAR(64) NOT NULL,
                athlete_state_snapshot_id INTEGER REFERENCES athlete_state_snapshots(id) ON DELETE SET NULL,
                readiness_checkin_id INTEGER REFERENCES daily_readiness_checkins(id) ON DELETE SET NULL,
                workout_id INTEGER REFERENCES training_plan_workouts(id) ON DELETE SET NULL,
                template_key VARCHAR(32) NOT NULL,
                content_fingerprint VARCHAR(64) NOT NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                scheduled_for TIMESTAMP WITH TIME ZONE NOT NULL,
                retry_at TIMESTAMP WITH TIME ZONE,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 5,
                locked_at TIMESTAMP WITH TIME ZONE,
                locked_by VARCHAR(128),
                sent_at TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                CONSTRAINT ck_coach_delivery_channel CHECK (channel = 'telegram'),
                CONSTRAINT ck_coach_delivery_type CHECK (delivery_type = 'daily_brief'),
                CONSTRAINT ck_coach_delivery_template CHECK (template_key IN ('checkin_required', 'proceed', 'conservative', 'rest', 'stop')),
                CONSTRAINT ck_coach_delivery_status CHECK (status IN ('pending', 'sending', 'sent', 'retry_scheduled', 'permanent_failure', 'cancelled')),
                CONSTRAINT ck_coach_delivery_attempt_counts CHECK (attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts),
                CONSTRAINT ck_coach_delivery_retry_status CHECK (retry_at IS NULL OR status = 'retry_scheduled'),
                CONSTRAINT ck_coach_delivery_retry_scheduled_at CHECK (status != 'retry_scheduled' OR retry_at IS NOT NULL),
                CONSTRAINT ck_coach_delivery_sending_lock CHECK (status != 'sending' OR (locked_at IS NOT NULL AND locked_by IS NOT NULL)),
                CONSTRAINT uq_coach_delivery_daily UNIQUE (user_id, channel, delivery_type, local_date, rule_version)
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_coach_delivery_due_queue ON coach_deliveries (status, scheduled_for, retry_at)",
            "CREATE INDEX IF NOT EXISTS ix_coach_delivery_user_history ON coach_deliveries (user_id, local_date DESC, created_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS coach_delivery_attempts (
                id BIGSERIAL PRIMARY KEY,
                delivery_id VARCHAR(64) NOT NULL REFERENCES coach_deliveries(id) ON DELETE CASCADE,
                attempt_number INTEGER NOT NULL,
                status VARCHAR(32) NOT NULL,
                failure_class VARCHAR(32),
                http_status INTEGER,
                started_at TIMESTAMP WITH TIME ZONE NOT NULL,
                completed_at TIMESTAMP WITH TIME ZONE NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                CONSTRAINT ck_coach_delivery_attempt_number CHECK (attempt_number > 0),
                CONSTRAINT ck_coach_delivery_attempt_status CHECK (status IN ('success', 'retryable_failure', 'permanent_failure')),
                CONSTRAINT ck_coach_delivery_attempt_failure_class CHECK (failure_class IS NULL OR failure_class IN ('timeout', 'network', 'rate_limited', 'upstream', 'forbidden', 'bad_request', 'configuration', 'internal')),
                CONSTRAINT uq_coach_delivery_attempt UNIQUE (delivery_id, attempt_number)
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_coach_delivery_attempts_delivery_id ON coach_delivery_attempts (delivery_id)",
        ),
    ),
    (
        "20260714_0030_coach_delivery_constraints",
        (
            """
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'coach_deliveries'::regclass AND conname = 'ck_coach_delivery_attempt_counts') THEN
                    ALTER TABLE coach_deliveries ADD CONSTRAINT ck_coach_delivery_attempt_counts CHECK (attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts);
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'coach_deliveries'::regclass AND conname = 'ck_coach_delivery_retry_status') THEN
                    ALTER TABLE coach_deliveries ADD CONSTRAINT ck_coach_delivery_retry_status CHECK (retry_at IS NULL OR status = 'retry_scheduled');
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'coach_deliveries'::regclass AND conname = 'ck_coach_delivery_retry_scheduled_at') THEN
                    ALTER TABLE coach_deliveries ADD CONSTRAINT ck_coach_delivery_retry_scheduled_at CHECK (status != 'retry_scheduled' OR retry_at IS NOT NULL);
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'coach_deliveries'::regclass AND conname = 'ck_coach_delivery_sending_lock') THEN
                    ALTER TABLE coach_deliveries ADD CONSTRAINT ck_coach_delivery_sending_lock CHECK (status != 'sending' OR (locked_at IS NOT NULL AND locked_by IS NOT NULL));
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'coach_delivery_attempts'::regclass AND conname = 'ck_coach_delivery_attempt_number') THEN
                    ALTER TABLE coach_delivery_attempts ADD CONSTRAINT ck_coach_delivery_attempt_number CHECK (attempt_number > 0);
                END IF;
            END $$
            """,
        ),
    ),
)


def run_migrations(engine: Engine) -> None:
    with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(727506681)"))
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
