PRAGMA foreign_keys = ON;

BEGIN TRANSACTION;

DELETE FROM activity_split_blocks;
DELETE FROM activity_workout_blocks;
DELETE FROM activity_segments;
DELETE FROM activity_screenshot_sources;
DELETE FROM lactate_threshold_measurements;
DELETE FROM import_batch_sources;
DELETE FROM import_batches;
DELETE FROM running_goals;
DELETE FROM training_activities;
DELETE FROM screenshot_sources;
DELETE FROM schema_metadata;

INSERT INTO schema_metadata (key, value) VALUES
  ('schema_version', '3'),
  ('seed_version', '2026-06-06-interval-training-v3');

INSERT INTO screenshot_sources (id, file_path, screen_type, captured_at, notes) VALUES
  (1, 'scrins/photo_2026-06-06_17-35-22.jpg', 'workout_pace_tab', '2026-06-06 17:35:22', 'Workout pace overview screenshot.'),
  (2, 'scrins/photo_2026-06-06_17-35-21.jpg', 'workout_segments_tab', '2026-06-06 17:35:21', 'Workout kilometer segments screenshot.'),
  (3, 'scrins/photo_2026-06-06_17-35-20.jpg', 'workout_details_tab', '2026-06-06 17:35:20', 'Workout details screenshot.'),
  (4, 'scrins/photo_2026-06-06_17-35-08.jpg', 'lactate_threshold_details_tab', '2026-06-06 17:35:08', 'Lactate threshold measurement screenshot.'),
  (5, 'scrins/training2/photo_2026-06-06_18-13-29.jpg', 'workout_pace_tab', '2026-06-06 18:13:29', 'Second workout pace overview screenshot.'),
  (6, 'scrins/training2/photo_2026-06-06_18-13-30.jpg', 'workout_segments_tab', '2026-06-06 18:13:30', 'Second workout kilometer segments screenshot.'),
  (7, 'scrins/training2/photo_2026-06-06_18-13-32.jpg', 'workout_details_tab', '2026-06-06 18:13:32', 'Second workout details screenshot.'),
  (8, 'scrins/training3/photo_2026-06-06_23-23-46.jpg', 'workout_pace_tab', '2026-06-06 23:23:46', 'Interval workout pace overview screenshot.'),
  (9, 'scrins/training3/photo_2026-06-06_23-23-49.jpg', 'workout_segments_tab', '2026-06-06 23:23:49', 'Interval workout structured segment screenshot.'),
  (10, 'scrins/training3/photo_2026-06-06_23-23-53.jpg', 'workout_details_tab', '2026-06-06 23:23:53', 'Interval workout details screenshot.');

INSERT INTO training_activities (
  id,
  activity_type,
  title,
  started_at,
  distance_km,
  duration_seconds,
  calories_kcal,
  average_pace_seconds_per_km,
  fastest_pace_seconds_per_km,
  average_speed_kmh,
  average_cadence_spm,
  average_stride_cm,
  steps_count,
  average_heart_rate_bpm,
  elevation_gain_m,
  elevation_loss_m,
  aerobic_training_stress,
  aerobic_training_effect,
  source_note
) VALUES
  (
    1,
    'outdoor_run',
    'Бег на улице',
    '2026-06-01 20:13:00',
    10.27,
    3991,
    862,
    389,
    359,
    9.26,
    177,
    87,
    11838,
    141,
    23.2,
    24.4,
    NULL,
    NULL,
    'Data extracted manually from three workout screenshots.'
  ),
  (
    2,
    'outdoor_run',
    'Бег на улице',
    '2026-05-31 17:45:00',
    5.23,
    1707,
    436,
    326,
    270,
    11.03,
    175,
    105,
    4988,
    158,
    26.4,
    28.5,
    2.7,
    'На прежнем уровне',
    'Data extracted manually from three second-workout screenshots.'
  ),
  (
    3,
    'outdoor_run_interval',
    'Интервальная тренировка: 3 x 2 км',
    '2026-06-06 20:16:00',
    11.74,
    4442,
    1022,
    378,
    325,
    9.51,
    174,
    91,
    12931,
    152,
    26.1,
    28.2,
    NULL,
    NULL,
    'Data extracted manually from Huawei interval training screenshots.'
  );

INSERT INTO activity_screenshot_sources (activity_id, source_id) VALUES
  (1, 1),
  (1, 2),
  (1, 3),
  (2, 5),
  (2, 6),
  (2, 7),
  (3, 8),
  (3, 9),
  (3, 10);

INSERT INTO activity_segments (
  activity_id,
  segment_index,
  distance_km,
  duration_seconds,
  pace_seconds_per_km,
  average_heart_rate_bpm,
  average_cadence_spm
) VALUES
  (1, 1, 1.00, 377, 377, 133, 178),
  (1, 2, 1.00, 410, 410, 137, 181),
  (1, 3, 1.00, 406, 406, 137, 180),
  (1, 4, 1.00, 415, 415, 138, 177),
  (1, 5, 1.00, 410, 410, 138, 176),
  (1, 6, 1.00, 402, 402, 141, 175),
  (1, 7, 1.00, 402, 402, 140, 174),
  (1, 8, 1.00, 388, 388, 143, 176),
  (1, 9, 1.00, 368, 368, 145, 177),
  (1, 10, 1.00, 359, 359, 146, 178),
  (1, 11, 0.27, 54, 204, 178, 191),
  (2, 1, 1.00, 324, 324, 143, 170),
  (2, 2, 1.00, 270, 270, 176, 178),
  (2, 3, 1.00, 389, 389, 151, 172),
  (2, 4, 1.00, 349, 349, 149, 176),
  (2, 5, 1.00, 315, 315, 167, 177),
  (2, 6, 0.23, 60, 260, 181, 181),
  (3, 1, 1.00, 374, 374, NULL, NULL),
  (3, 2, 1.00, 425, 425, NULL, NULL),
  (3, 3, 1.00, 375, 375, NULL, NULL),
  (3, 4, 1.00, 330, 330, NULL, NULL),
  (3, 5, 1.00, 325, 325, NULL, NULL),
  (3, 6, 1.00, 389, 389, NULL, NULL),
  (3, 7, 1.00, 340, 340, NULL, NULL),
  (3, 8, 1.00, 413, 413, NULL, NULL),
  (3, 9, 1.00, 343, 343, NULL, NULL),
  (3, 10, 1.00, 365, 365, NULL, NULL),
  (3, 11, 1.00, 466, 466, NULL, NULL),
  (3, 12, 0.74, 297, 401, NULL, NULL);

INSERT INTO activity_split_blocks (
  activity_id,
  block_index,
  start_km,
  end_km,
  distance_km,
  duration_seconds,
  cumulative_duration_seconds,
  notes
) VALUES
  (1, 1, 0.0, 5.0, 5.0, 2018, 2018, 'First 5 km split from pace tab.'),
  (1, 2, 5.0, 10.0, 5.0, 1919, 3937, 'Second 5 km split from pace tab.'),
  (2, 1, 0.0, 5.0, 5.0, 1647, 1647, 'First 5 km split from second workout pace tab.'),
  (3, 1, 0.0, 5.0, 5.0, 1829, 1829, 'First 5 km split from interval workout pace tab.'),
  (3, 2, 5.0, 10.0, 5.0, 1850, 3679, 'Second 5 km split from interval workout pace tab.'),
  (3, 3, 10.0, 11.74, 1.74, 763, 4442, 'Final partial split from interval workout pace tab.');

INSERT INTO activity_workout_blocks (
  activity_id,
  block_index,
  block_type,
  title,
  distance_km,
  duration_seconds,
  pace_seconds_per_km,
  average_heart_rate_bpm,
  average_cadence_spm,
  notes
) VALUES
  (3, 1, 'warmup', 'Разминка', 2.98, 1168, 391, 137, NULL, 'Warm-up before 2 km work intervals.'),
  (3, 2, 'work', 'Бег', 2.00, 654, 327, 161, NULL, 'Work interval 1 of 3.'),
  (3, 3, 'recovery', 'Отдых', 0.38, 180, 468, 150, NULL, 'Three-minute recovery after work interval 1.'),
  (3, 4, 'work', 'Бег', 2.00, 682, 341, 161, NULL, 'Work interval 2 of 3.'),
  (3, 5, 'recovery', 'Отдых', 0.31, 180, 590, 151, NULL, 'Three-minute recovery after work interval 2.'),
  (3, 6, 'work', 'Бег', 2.00, 664, 332, 163, NULL, 'Work interval 3 of 3.'),
  (3, 7, 'recovery', 'Отдых', 0.40, 180, 462, 155, NULL, 'Three-minute recovery after work interval 3.'),
  (3, 8, 'cooldown', 'Низкий', 1.67, 734, 437, 145, NULL, 'Low intensity cooldown.');

INSERT INTO lactate_threshold_measurements (
  id,
  source_id,
  measured_at,
  duration_seconds,
  calories_kcal,
  average_pace_seconds_per_km,
  average_speed_kmh,
  average_cadence_spm,
  average_stride_cm,
  steps_count,
  average_heart_rate_bpm,
  elevation_gain_m,
  elevation_loss_m,
  threshold_heart_rate_bpm,
  threshold_pace_seconds_per_km,
  distance_km,
  distance_is_estimated,
  notes
) VALUES (
  1,
  4,
  NULL,
  1190,
  259,
  389,
  9.26,
  176,
  88,
  3494,
  145,
  1.3,
  2.3,
  163,
  324,
  NULL,
  0,
  'Measurement date and distance are not visible on the screenshot.'
);

COMMIT;
