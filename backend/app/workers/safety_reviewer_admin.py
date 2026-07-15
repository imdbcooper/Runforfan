import argparse
import json

from app.db.migrations.runner import run_migrations
from app.db.session import SessionLocal, engine
from app.services.safety_reviews import SafetyReviewConflict, operational_status, provision_review_audience, provision_reviewer, revoke_review_audience, revoke_reviewer


def main() -> None:
    parser = argparse.ArgumentParser(description="Operate bounded safety review controls")
    subparsers = parser.add_subparsers(dest="scope", required=True)
    reviewer = subparsers.add_parser("reviewer")
    reviewer.add_argument("action", choices=("grant", "revoke"))
    reviewer.add_argument("user_id", type=int)
    reviewer.add_argument("--confirm", required=True, choices=("GRANT", "REVOKE"))
    audience = subparsers.add_parser("audience")
    audience.add_argument("action", choices=("add", "revoke"))
    audience.add_argument("user_id", type=int)
    audience.add_argument("--confirm", required=True, choices=("ENROLL", "REVOKE"))
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--access-hours", type=int, default=24)
    status_parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    if args.scope != "status":
        expected = "ENROLL" if args.scope == "audience" and args.action == "add" else args.action.upper()
        if args.confirm != expected:
            parser.error(f"--confirm must be {expected} for {args.action}")

    run_migrations(engine)
    try:
        with SessionLocal() as db:
            if args.scope == "status":
                report = operational_status(db, access_hours=args.access_hours)
                if args.format == "json":
                    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
                else:
                    queue = report["queue"]
                    print(f"generated_at: {report['generated_at']}")
                    print(f"rollout: {report['rollout']}")
                    print(f"active reviewer grants: {report['active_reviewer_grants']}")
                    print(f"active audience enrollments: {report['active_audience_enrollments']}")
                    print(f"queue: requested={queue['requested_count']} claimed={queue['claimed_count']} requested_age_buckets={queue['requested_age_buckets']}")
                    print(f"access events since {report['access_ledger']['since']}: {report['access_ledger']['events']}")
                    print(report["disclaimer"])
            elif args.scope == "reviewer" and args.action == "grant":
                grant = provision_reviewer(db, args.user_id)
                print(f"reviewer grant #{grant.id}: active for user {grant.user_id}")
            elif args.scope == "reviewer":
                grant, released = revoke_reviewer(db, args.user_id)
                print(f"reviewer grant #{grant.id}: revoked for user {grant.user_id}; released claims: {released}")
            elif args.action == "add":
                enrollment = provision_review_audience(db, args.user_id)
                print(f"review audience enrollment #{enrollment.id}: active for user {enrollment.user_id}")
            else:
                enrollment, closed = revoke_review_audience(db, args.user_id)
                print(f"review audience enrollment #{enrollment.id}: revoked for user {enrollment.user_id}; closed active requests: {closed}")
    except SafetyReviewConflict as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
