import argparse
import json
from datetime import UTC, datetime, timedelta

from app.db.migrations.runner import run_migrations
from app.db.session import SessionLocal, engine
from app.services.coach_evaluation import materialize_evaluation, run_to_dict


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include an offset")
    return parsed.astimezone(UTC)


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize an aggregate Coaching OS evaluation dashboard")
    parser.add_argument("--start", type=_timestamp)
    parser.add_argument("--end", type=_timestamp)
    parser.add_argument("--days", type=int, default=28)
    parser.add_argument("--format", choices=("json", "text"), default="text")
    parser.add_argument("--fail-on-block", action="store_true")
    args = parser.parse_args()
    now = datetime.now(UTC)
    end = args.end or now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = args.start or end - timedelta(days=max(1, min(args.days, 365)))
    run_migrations(engine)
    with SessionLocal() as db:
        report = run_to_dict(materialize_evaluation(db, start, end))
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    else:
        print(f"evaluation: {report['id']} {report['status']} ({report['window_start']} to {report['window_end']})")
        for name, gate in report["gates"].items():
            print(f"{name}: {gate['status']}")
        print(report["disclaimer"])
    if args.fail_on_block and report["status"] == "block":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
