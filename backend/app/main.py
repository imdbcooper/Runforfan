from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import add_exception_handlers
from app.api.routes import account, activities, analytics, athlete_state, audit_log, auth, calendar, coach_actions, coaching_events, dashboard, export, goals, imports, performance, plan_recalculations, planning, profile, readiness, settings as settings_routes, zones
from app.core.settings import get_settings
from app.db.base import Base
from app.db.migrations.runner import run_migrations
from app.db.session import SessionLocal, engine
from app.models import *  # noqa: F401,F403
from app.seed.demo import seed_demo_data
from app.services.activity_metrics import backfill_derived_activity_metrics
from app.services.import_recognition_worker import start_import_recognition_worker, stop_import_recognition_worker
from app.services.telegram_bot import start_telegram_polling, stop_telegram_polling
from app.services.training_load import backfill_recent_daily_training_loads


settings = get_settings()

app = FastAPI(title="Runforfan Backend", version="0.1.0")
add_exception_handlers(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    if settings.auto_create_schema:
        Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    if settings.demo_seed:
        with SessionLocal() as db:
            seed_demo_data(db)
    if settings.derived_metrics_backfill_on_startup and settings.derived_metrics_backfill_startup_limit > 0:
        with SessionLocal() as db:
            backfill_derived_activity_metrics(db, limit=settings.derived_metrics_backfill_startup_limit)
            db.commit()
    if settings.daily_training_load_backfill_on_startup and settings.daily_training_load_backfill_days > 0 and settings.daily_training_load_backfill_user_limit > 0:
        with SessionLocal() as db:
            backfill_recent_daily_training_loads(db, days=settings.daily_training_load_backfill_days, user_limit=settings.daily_training_load_backfill_user_limit)
            db.commit()
    start_telegram_polling()
    start_import_recognition_worker()


@app.on_event("shutdown")
def on_shutdown() -> None:
    stop_import_recognition_worker()
    stop_telegram_polling()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth.router, prefix="/api")
app.include_router(activities.router, prefix="/api")
app.include_router(imports.router, prefix="/api")
app.include_router(goals.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(performance.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(calendar.router, prefix="/api")
app.include_router(planning.router, prefix="/api")
app.include_router(readiness.router, prefix="/api")
app.include_router(coach_actions.router, prefix="/api")
app.include_router(settings_routes.router, prefix="/api")
app.include_router(profile.router, prefix="/api")
app.include_router(zones.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(account.router, prefix="/api")
app.include_router(audit_log.router, prefix="/api")
app.include_router(coaching_events.router, prefix="/api")
app.include_router(athlete_state.router, prefix="/api")
app.include_router(plan_recalculations.router, prefix="/api")
