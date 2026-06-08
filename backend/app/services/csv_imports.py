import csv
from datetime import datetime
from io import StringIO
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Activity, AthleteProfile, User
from app.services.activity_metrics import sync_derived_activity_metrics


FIELD_ALIASES = {
    "title": {"title", "name", "activity name", "activity_name", "workout title"},
    "activity_type": {"activity_type", "activity type", "type", "sport"},
    "started_at": {"started_at", "start_time", "start time", "date", "activity date", "timestamp"},
    "distance_km": {"distance_km", "distance km", "distance", "distance (km)", "dist_km"},
    "duration_seconds": {"duration_seconds", "duration seconds", "moving_time", "moving time", "elapsed time", "time", "duration"},
    "calories_kcal": {"calories", "calories_kcal", "calories kcal"},
    "average_pace_seconds_per_km": {"average_pace_seconds_per_km", "pace_seconds_per_km", "avg pace", "average pace", "pace"},
    "average_heart_rate_bpm": {"average_heart_rate_bpm", "avg hr", "average heart rate", "average hr", "heart rate"},
    "elevation_gain_m": {"elevation_gain_m", "elevation gain", "elevation gain (m)", "total ascent"},
    "average_cadence_spm": {"average_cadence_spm", "cadence", "avg cadence"},
}


def normalized_row(row: dict[str, Any]) -> dict[str, str]:
    source = {str(key).strip().lower(): str(value).strip() for key, value in row.items() if key is not None and value is not None}
    result: dict[str, str] = {}
    for canonical, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in source and source[alias] != "":
                result[canonical] = source[alias]
                break
    return result


def parse_float(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = value.replace(" ", "").replace(",", ".")
    return float(cleaned)


def parse_int(value: str | None) -> int | None:
    parsed = parse_float(value)
    return round(parsed) if parsed is not None else None


def parse_duration_seconds(value: str | None) -> int | None:
    if not value:
        return None
    cleaned = value.strip()
    if ":" not in cleaned:
        return parse_int(cleaned)
    parts = [int(part) for part in cleaned.split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
        return minutes * 60 + seconds
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return hours * 3600 + minutes * 60 + seconds
    raise ValueError(f"Unsupported duration format: {value}")


def parse_pace_seconds_per_km(value: str | None) -> int | None:
    if not value:
        return None
    return parse_duration_seconds(value)


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = value.strip().replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            if fmt is None:
                return datetime.fromisoformat(cleaned)
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format: {value}")


def activity_payload_from_csv_row(row: dict[str, Any], row_number: int, filename: str) -> dict[str, Any]:
    values = normalized_row(row)
    duration_seconds = parse_duration_seconds(values.get("duration_seconds"))
    if duration_seconds is None or duration_seconds <= 0:
        raise ValueError(f"row {row_number}: duration_seconds is required")
    distance_km = parse_float(values.get("distance_km"))
    if distance_km is not None and distance_km > 1000:
        distance_km = distance_km / 1000
    started_at = parse_datetime(values.get("started_at"))
    activity_type = values.get("activity_type") or "outdoor_run"
    return {
        "activity_type": activity_type[:64],
        "title": (values.get("title") or "CSV import run")[:255],
        "started_at": started_at,
        "distance_km": distance_km,
        "duration_seconds": duration_seconds,
        "calories_kcal": parse_int(values.get("calories_kcal")),
        "average_pace_seconds_per_km": parse_pace_seconds_per_km(values.get("average_pace_seconds_per_km")),
        "average_heart_rate_bpm": parse_int(values.get("average_heart_rate_bpm")),
        "elevation_gain_m": parse_float(values.get("elevation_gain_m")),
        "average_cadence_spm": parse_int(values.get("average_cadence_spm")),
        "source_note": f"Imported from CSV file {filename}, row {row_number}.",
    }


def create_activity_from_csv_payload(db: Session, user: User, payload: dict[str, Any]) -> tuple[Activity, bool]:
    profile = db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == user.id))
    existing = None
    if payload.get("started_at") and payload.get("distance_km") and payload.get("duration_seconds"):
        existing = db.scalar(select(Activity).where(
            Activity.user_id == user.id,
            Activity.started_at == payload["started_at"],
            Activity.distance_km == payload["distance_km"],
            Activity.duration_seconds == payload["duration_seconds"],
        ))
    if existing:
        sync_derived_activity_metrics(db, existing, profile)
        return existing, False
    activity = Activity(user_id=user.id, **payload)
    db.add(activity)
    db.flush()
    sync_derived_activity_metrics(db, activity, profile)
    return activity, True


def read_csv_text(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def iter_csv_rows(raw: bytes) -> list[dict[str, Any]]:
    text = read_csv_text(raw)
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t") if sample.strip() else csv.excel
    except csv.Error:
        dialect = csv.excel
    return list(csv.DictReader(StringIO(text), dialect=dialect))
