from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.session import get_db
from app.schemas.common import AuthToken, UserOut
from app.services.auth import create_session, get_or_create_demo_user, get_or_create_telegram_user, validate_telegram_login


router = APIRouter(prefix="/auth", tags=["auth"])


class TelegramLoginPayload(BaseModel):
    id: str
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    auth_date: str
    hash: str


@router.post("/dev-login", response_model=AuthToken)
def dev_login(db: Session = Depends(get_db)):
    if get_settings().app_env not in {"development", "local", "test"}:
        raise HTTPException(status_code=403, detail="Dev login is disabled")
    user = get_or_create_demo_user(db)
    token = create_session(db, user)
    return AuthToken(access_token=token, user=UserOut.model_validate(user))


@router.post("/telegram", response_model=AuthToken)
def telegram_login(payload: TelegramLoginPayload, db: Session = Depends(get_db)):
    data = payload.model_dump(exclude_none=True)
    if not validate_telegram_login(data):
        raise HTTPException(status_code=401, detail="Invalid Telegram login hash")
    user = get_or_create_telegram_user(db, data)
    token = create_session(db, user)
    return AuthToken(access_token=token, user=UserOut.model_validate(user))
