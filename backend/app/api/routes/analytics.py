from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User
from app.schemas.common import AnalyticsInsightOut, AnalyticsSummaryOut, AnalyticsTimeseriesOut
from app.services.analytics import analytics_insights, analytics_timeseries, user_analytics
from app.services.auth import get_current_user


router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=AnalyticsSummaryOut)
def analytics_summary(from_date: date | None = Query(default=None, alias="from"), to_date: date | None = Query(default=None, alias="to"), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return user_analytics(db, user, from_date, to_date)


@router.get("/timeseries", response_model=AnalyticsTimeseriesOut)
def analytics_timeseries_route(metric: str = Query(default="distance", pattern="^(distance|duration|workouts|pace|hr|load)$"), granularity: str = Query(default="week", pattern="^(week|month)$"), from_date: date | None = Query(default=None, alias="from"), to_date: date | None = Query(default=None, alias="to"), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return analytics_timeseries(db, user, metric, granularity, from_date, to_date)


@router.get("/insights", response_model=list[AnalyticsInsightOut])
def analytics_insights_route(from_date: date | None = Query(default=None, alias="from"), to_date: date | None = Query(default=None, alias="to"), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return analytics_insights(db, user, from_date, to_date)
