PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS screenshot_sources (
  id INTEGER PRIMARY KEY,
  file_path TEXT NOT NULL UNIQUE,
  screen_type TEXT NOT NULL,
  captured_at TEXT,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS training_activities (
  id INTEGER PRIMARY KEY,
  activity_type TEXT NOT NULL,
  title TEXT NOT NULL,
  started_at TEXT,
  distance_km REAL,
  duration_seconds INTEGER NOT NULL,
  calories_kcal INTEGER,
  average_pace_seconds_per_km INTEGER,
  fastest_pace_seconds_per_km INTEGER,
  average_speed_kmh REAL,
  average_cadence_spm INTEGER,
  average_stride_cm INTEGER,
  steps_count INTEGER,
  average_heart_rate_bpm INTEGER,
  elevation_gain_m REAL,
  elevation_loss_m REAL,
  aerobic_training_stress REAL,
  aerobic_training_effect TEXT,
  source_note TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS activity_screenshot_sources (
  activity_id INTEGER NOT NULL,
  source_id INTEGER NOT NULL,
  PRIMARY KEY (activity_id, source_id),
  FOREIGN KEY (activity_id) REFERENCES training_activities(id) ON DELETE CASCADE,
  FOREIGN KEY (source_id) REFERENCES screenshot_sources(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS activity_segments (
  id INTEGER PRIMARY KEY,
  activity_id INTEGER NOT NULL,
  segment_index INTEGER NOT NULL,
  distance_km REAL NOT NULL,
  duration_seconds INTEGER NOT NULL,
  pace_seconds_per_km INTEGER NOT NULL,
  average_heart_rate_bpm INTEGER,
  average_cadence_spm INTEGER,
  UNIQUE (activity_id, segment_index),
  FOREIGN KEY (activity_id) REFERENCES training_activities(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS activity_split_blocks (
  id INTEGER PRIMARY KEY,
  activity_id INTEGER NOT NULL,
  block_index INTEGER NOT NULL,
  start_km REAL NOT NULL,
  end_km REAL NOT NULL,
  distance_km REAL NOT NULL,
  duration_seconds INTEGER NOT NULL,
  cumulative_duration_seconds INTEGER,
  notes TEXT,
  UNIQUE (activity_id, block_index),
  FOREIGN KEY (activity_id) REFERENCES training_activities(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS lactate_threshold_measurements (
  id INTEGER PRIMARY KEY,
  source_id INTEGER NOT NULL,
  measured_at TEXT,
  duration_seconds INTEGER,
  calories_kcal INTEGER,
  average_pace_seconds_per_km INTEGER,
  average_speed_kmh REAL,
  average_cadence_spm INTEGER,
  average_stride_cm INTEGER,
  steps_count INTEGER,
  average_heart_rate_bpm INTEGER,
  elevation_gain_m REAL,
  elevation_loss_m REAL,
  threshold_heart_rate_bpm INTEGER NOT NULL,
  threshold_pace_seconds_per_km INTEGER NOT NULL,
  distance_km REAL,
  distance_is_estimated INTEGER NOT NULL DEFAULT 0 CHECK (distance_is_estimated IN (0, 1)),
  notes TEXT,
  FOREIGN KEY (source_id) REFERENCES screenshot_sources(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS import_batches (
  id INTEGER PRIMARY KEY,
  status TEXT NOT NULL,
  recognition_engine TEXT,
  recognition_message TEXT,
  raw_result_json TEXT,
  created_activity_id INTEGER,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (created_activity_id) REFERENCES training_activities(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS import_batch_sources (
  batch_id INTEGER NOT NULL,
  source_id INTEGER NOT NULL,
  PRIMARY KEY (batch_id, source_id),
  FOREIGN KEY (batch_id) REFERENCES import_batches(id) ON DELETE CASCADE,
  FOREIGN KEY (source_id) REFERENCES screenshot_sources(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS running_goals (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  goal_type TEXT NOT NULL,
  target_value REAL,
  unit TEXT,
  period_start TEXT,
  period_end TEXT,
  reason TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_training_activities_started_at
  ON training_activities(started_at);

CREATE INDEX IF NOT EXISTS idx_activity_segments_activity_id
  ON activity_segments(activity_id);

CREATE INDEX IF NOT EXISTS idx_lactate_threshold_measurements_measured_at
  ON lactate_threshold_measurements(measured_at);

CREATE INDEX IF NOT EXISTS idx_import_batches_created_at
  ON import_batches(created_at);

CREATE INDEX IF NOT EXISTS idx_running_goals_status
  ON running_goals(status);
