from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Activity, User


def user_analytics(db: Session, user: User) -> dict:
    activities = list(db.scalars(select(Activity).where(Activity.user_id == user.id).order_by(Activity.started_at.desc())))
    total_distance = sum(activity.distance_km or 0 for activity in activities)
    total_duration = sum(activity.duration_seconds or 0 for activity in activities)
    hr_values = [activity.average_heart_rate_bpm for activity in activities if activity.average_heart_rate_bpm]
    longest = max(activities, key=lambda activity: activity.distance_km or 0, default=None)
    fastest = min(
        [activity for activity in activities if activity.average_pace_seconds_per_km],
        key=lambda activity: activity.average_pace_seconds_per_km or 99999,
        default=None,
    )

    months = defaultdict(lambda: {"distance_km": 0.0, "duration_seconds": 0, "count": 0})
    for activity in activities:
        key = activity.started_at.strftime("%Y-%m") if activity.started_at else "unknown"
        months[key]["distance_km"] += activity.distance_km or 0
        months[key]["duration_seconds"] += activity.duration_seconds or 0
        months[key]["count"] += 1

    return {
        "activity_count": len(activities),
        "total_distance_km": round(total_distance, 2),
        "total_duration_seconds": total_duration,
        "weighted_average_pace_seconds_per_km": round(total_duration / total_distance) if total_distance else None,
        "average_heart_rate_bpm": round(sum(hr_values) / len(hr_values)) if hr_values else None,
        "longest_activity_id": longest.id if longest else None,
        "longest_distance_km": longest.distance_km if longest else None,
        "fastest_activity_id": fastest.id if fastest else None,
        "fastest_average_pace_seconds_per_km": fastest.average_pace_seconds_per_km if fastest else None,
        "months": [
            {"month": key, **value}
            for key, value in sorted(months.items(), reverse=True)
        ],
    }
