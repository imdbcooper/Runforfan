from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User
from app.schemas.common import AnalyticsInsightOut, AnalyticsSummaryOut, AnalyticsTimeseriesOut, TrainingLoadDailyOut, TrainingLoadFitnessFatigueOut, TrainingLoadWarningOut, TrainingLoadWeeklyOut
from app.services.analytics import analytics_insights, analytics_timeseries, user_analytics
from app.services.auth import get_current_user
from app.services.training_load import training_load_daily, training_load_fitness_fatigue, training_load_warning_list, training_load_weekly


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


@router.get("/load/daily", response_model=TrainingLoadDailyOut)
def analytics_load_daily(from_date: date | None = Query(default=None, alias="from"), to_date: date | None = Query(default=None, alias="to"), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return training_load_daily(db, user, from_date, to_date)


@router.get("/load/weekly", response_model=TrainingLoadWeeklyOut)
def analytics_load_weekly(from_date: date | None = Query(default=None, alias="from"), to_date: date | None = Query(default=None, alias="to"), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return training_load_weekly(db, user, from_date, to_date)


@router.get("/load/fitness-fatigue", response_model=TrainingLoadFitnessFatigueOut)
def analytics_load_fitness_fatigue(from_date: date | None = Query(default=None, alias="from"), to_date: date | None = Query(default=None, alias="to"), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return training_load_fitness_fatigue(db, user, from_date, to_date)


@router.get("/load/warnings", response_model=list[TrainingLoadWarningOut])
def analytics_load_warnings(from_date: date | None = Query(default=None, alias="from"), to_date: date | None = Query(default=None, alias="to"), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return training_load_warning_list(db, user, from_date, to_date)
