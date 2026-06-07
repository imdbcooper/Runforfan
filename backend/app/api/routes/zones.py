from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User
from app.schemas.common import ZoneWrite, ZonesOut
from app.services.auth import get_current_user
from app.services.zones import recalculate_and_store_zones, replace_manual_zones, zones_response


router = APIRouter(prefix="/zones", tags=["zones"])


def validate_zone_units(payload: list[ZoneWrite], expected_unit: str) -> None:
    for zone in payload:
        if zone.unit != expected_unit:
            raise HTTPException(status_code=422, detail=f"{zone.zone_key} must use unit={expected_unit}")


@router.get("", response_model=ZonesOut)
def get_zones(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return zones_response(db, user)


@router.post("/recalculate", response_model=ZonesOut)
def recalculate_zones(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return recalculate_and_store_zones(db, user)


@router.put("/hr", response_model=ZonesOut)
def replace_hr_zones(payload: list[ZoneWrite], user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    validate_zone_units(payload, "bpm")
    return replace_manual_zones(db, user, "hr", [zone.model_dump() for zone in payload])


@router.put("/pace", response_model=ZonesOut)
def replace_pace_zones(payload: list[ZoneWrite], user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    validate_zone_units(payload, "seconds_per_km")
    return replace_manual_zones(db, user, "pace", [zone.model_dump() for zone in payload])


@router.put("/rpe", response_model=ZonesOut)
def replace_rpe_zones(payload: list[ZoneWrite], user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    validate_zone_units(payload, "rpe")
    return replace_manual_zones(db, user, "rpe", [zone.model_dump() for zone in payload])
