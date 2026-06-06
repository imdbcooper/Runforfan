from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Activity, ActivityScreenshot, ActivitySegment, ActivitySplitBlock, ActivityWorkoutBlock, AthleteProfile, LactateThresholdMeasurement, ScreenshotSource, User
from app.services.auth import get_or_create_demo_user


def seed_interval_training(db: Session, user: User) -> None:
    started_at = datetime(2026, 6, 6, 20, 16)
    exists = db.scalar(select(Activity).where(Activity.user_id == user.id, Activity.started_at == started_at, Activity.distance_km == 11.74))
    if exists:
        return

    sources = []
    for file_path, screen_type, notes in [
        ("scrins/training3/photo_2026-06-06_23-23-46.jpg", "workout_pace_tab", "Interval workout pace tab."),
        ("scrins/training3/photo_2026-06-06_23-23-49.jpg", "workout_segments_tab", "Interval workout structured segments tab."),
        ("scrins/training3/photo_2026-06-06_23-23-53.jpg", "workout_details_tab", "Interval workout details tab."),
    ]:
        source = db.scalar(select(ScreenshotSource).where(ScreenshotSource.user_id == user.id, ScreenshotSource.file_path == file_path))
        if not source:
            source = ScreenshotSource(user_id=user.id, file_path=file_path, screen_type=screen_type, captured_at=datetime(2026, 6, 6, 23, 23), source_app="Huawei Health", notes=notes)
            db.add(source)
            db.flush()
        sources.append(source)

    activity = Activity(
        user_id=user.id,
        activity_type="outdoor_run_interval",
        title="Интервальная тренировка: 3 x 2 км",
        started_at=started_at,
        distance_km=11.74,
        duration_seconds=4442,
        calories_kcal=1022,
        average_pace_seconds_per_km=378,
        fastest_pace_seconds_per_km=325,
        average_speed_kmh=9.51,
        average_cadence_spm=174,
        average_stride_cm=91,
        steps_count=12931,
        average_heart_rate_bpm=152,
        elevation_gain_m=26.1,
        elevation_loss_m=28.2,
        source_note="Seeded from Huawei interval training screenshots in scrins/training3.",
    )
    db.add(activity)
    db.flush()

    for source in sources:
        db.add(ActivityScreenshot(activity_id=activity.id, source_id=source.id))

    for idx, distance, duration, pace in [
        (1, 1.0, 374, 374), (2, 1.0, 425, 425), (3, 1.0, 375, 375),
        (4, 1.0, 330, 330), (5, 1.0, 325, 325), (6, 1.0, 389, 389),
        (7, 1.0, 340, 340), (8, 1.0, 413, 413), (9, 1.0, 343, 343),
        (10, 1.0, 365, 365), (11, 1.0, 466, 466), (12, 0.74, 297, 401),
    ]:
        db.add(ActivitySegment(activity_id=activity.id, segment_index=idx, distance_km=distance, duration_seconds=duration, pace_seconds_per_km=pace))

    db.add_all([
        ActivitySplitBlock(activity_id=activity.id, block_index=1, start_km=0, end_km=5, distance_km=5, duration_seconds=1829, cumulative_duration_seconds=1829),
        ActivitySplitBlock(activity_id=activity.id, block_index=2, start_km=5, end_km=10, distance_km=5, duration_seconds=1850, cumulative_duration_seconds=3679),
        ActivitySplitBlock(activity_id=activity.id, block_index=3, start_km=10, end_km=11.74, distance_km=1.74, duration_seconds=763, cumulative_duration_seconds=4442),
    ])

    for idx, block_type, title, duration, distance, pace, hr in [
        (1, "warmup", "Разминка", 1168, 2.98, 391, 137),
        (2, "work", "Бег", 654, 2.0, 327, 161),
        (3, "recovery", "Отдых", 180, 0.38, 468, 150),
        (4, "work", "Бег", 682, 2.0, 341, 161),
        (5, "recovery", "Отдых", 180, 0.31, 590, 151),
        (6, "work", "Бег", 664, 2.0, 332, 163),
        (7, "recovery", "Отдых", 180, 0.40, 462, 155),
        (8, "cooldown", "Низкий", 734, 1.67, 437, 145),
    ]:
        db.add(ActivityWorkoutBlock(activity_id=activity.id, block_index=idx, block_type=block_type, title=title, duration_seconds=duration, distance_km=distance, pace_seconds_per_km=pace, average_heart_rate_bpm=hr))


def seed_athlete_profile(db: Session, user: User) -> None:
    profile = db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == user.id))
    if profile:
        return
    db.add(AthleteProfile(
        user_id=user.id,
        sex="unspecified",
        timezone="Europe/Moscow",
        locale="ru-RU",
        lactate_threshold_hr_bpm=163,
        lactate_threshold_pace_seconds_per_km=324,
        conservative_mode=False,
    ))


def seed_demo_data(db: Session) -> None:
    user = get_or_create_demo_user(db)
    seed_athlete_profile(db, user)
    exists = db.scalar(select(Activity).where(Activity.user_id == user.id))
    if exists:
        seed_interval_training(db, user)
        db.commit()
        return

    first = Activity(
        user_id=user.id,
        activity_type="outdoor_run",
        title="Бег на улице",
        started_at=datetime(2026, 6, 1, 20, 13),
        distance_km=10.27,
        duration_seconds=3991,
        calories_kcal=862,
        average_pace_seconds_per_km=389,
        fastest_pace_seconds_per_km=359,
        average_speed_kmh=9.26,
        average_cadence_spm=177,
        average_stride_cm=87,
        steps_count=11838,
        average_heart_rate_bpm=141,
        elevation_gain_m=23.2,
        elevation_loss_m=24.4,
        source_note="Seeded from original SQLite screenshots.",
    )
    second = Activity(
        user_id=user.id,
        activity_type="outdoor_run",
        title="Бег на улице",
        started_at=datetime(2026, 5, 31, 17, 45),
        distance_km=5.23,
        duration_seconds=1707,
        calories_kcal=436,
        average_pace_seconds_per_km=326,
        fastest_pace_seconds_per_km=270,
        average_speed_kmh=11.03,
        average_cadence_spm=175,
        average_stride_cm=105,
        steps_count=4988,
        average_heart_rate_bpm=158,
        elevation_gain_m=26.4,
        elevation_loss_m=28.5,
        aerobic_training_stress=2.7,
        aerobic_training_effect="На прежнем уровне",
        source_note="Seeded from training2 screenshots.",
    )
    db.add_all([first, second])
    db.flush()

    for idx, duration, pace, hr, cadence in [
        (1, 377, 377, 133, 178), (2, 410, 410, 137, 181), (3, 406, 406, 137, 180),
        (4, 415, 415, 138, 177), (5, 410, 410, 138, 176), (6, 402, 402, 141, 175),
        (7, 402, 402, 140, 174), (8, 388, 388, 143, 176), (9, 368, 368, 145, 177),
        (10, 359, 359, 146, 178),
    ]:
        db.add(ActivitySegment(activity_id=first.id, segment_index=idx, distance_km=1.0, duration_seconds=duration, pace_seconds_per_km=pace, average_heart_rate_bpm=hr, average_cadence_spm=cadence))
    db.add(ActivitySegment(activity_id=first.id, segment_index=11, distance_km=0.27, duration_seconds=54, pace_seconds_per_km=204, average_heart_rate_bpm=178, average_cadence_spm=191))
    db.add_all([
        ActivitySplitBlock(activity_id=first.id, block_index=1, start_km=0, end_km=5, distance_km=5, duration_seconds=2018, cumulative_duration_seconds=2018),
        ActivitySplitBlock(activity_id=first.id, block_index=2, start_km=5, end_km=10, distance_km=5, duration_seconds=1919, cumulative_duration_seconds=3937),
    ])

    for idx, distance, duration, pace, hr, cadence in [
        (1, 1.0, 324, 324, 143, 170), (2, 1.0, 270, 270, 176, 178),
        (3, 1.0, 389, 389, 151, 172), (4, 1.0, 349, 349, 149, 176),
        (5, 1.0, 315, 315, 167, 177), (6, 0.23, 60, 260, 181, 181),
    ]:
        db.add(ActivitySegment(activity_id=second.id, segment_index=idx, distance_km=distance, duration_seconds=duration, pace_seconds_per_km=pace, average_heart_rate_bpm=hr, average_cadence_spm=cadence))
    db.add(ActivitySplitBlock(activity_id=second.id, block_index=1, start_km=0, end_km=5, distance_km=5, duration_seconds=1647, cumulative_duration_seconds=1647))

    db.add(LactateThresholdMeasurement(
        user_id=user.id,
        duration_seconds=1190,
        calories_kcal=259,
        average_pace_seconds_per_km=389,
        average_speed_kmh=9.26,
        average_cadence_spm=176,
        average_stride_cm=88,
        steps_count=3494,
        average_heart_rate_bpm=145,
        elevation_gain_m=1.3,
        elevation_loss_m=2.3,
        threshold_heart_rate_bpm=163,
        threshold_pace_seconds_per_km=324,
        notes="Seeded lactate threshold measurement.",
    ))
    seed_interval_training(db, user)
    db.commit()
