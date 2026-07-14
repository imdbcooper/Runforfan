from app.db.migrations.runner import run_migrations
from app.db.session import engine
from app.services.coach_delivery import run_loop

if __name__ == "__main__":
    run_migrations(engine)
    run_loop()
