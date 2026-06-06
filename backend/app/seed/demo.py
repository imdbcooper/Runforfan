from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Activity, ActivitySegment, ActivitySplitBlock, LactateThresholdMeasurement, User
from app.services.auth import get_or_create_demo_user


def seed_demo_data(db: Session) -> None:
    user = get_or_create_demo_user(db)
    exists = db.scalar(select(Activity).where(Activity.user_id == user.id))
    if exists:
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
    db.commit()
