import argparse

from app.db.migrations.runner import run_migrations
from app.db.session import SessionLocal, engine
from app.services.safety_reviews import SafetyReviewConflict, provision_reviewer, revoke_reviewer


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision or revoke a safety reviewer grant")
    parser.add_argument("action", choices=("grant", "revoke"))
    parser.add_argument("user_id", type=int)
    parser.add_argument("--confirm", required=True, choices=("GRANT", "REVOKE"))
    args = parser.parse_args()
    expected = args.action.upper()
    if args.confirm != expected:
        parser.error(f"--confirm must be {expected} for {args.action}")

    run_migrations(engine)
    try:
        with SessionLocal() as db:
            if args.action == "grant":
                grant = provision_reviewer(db, args.user_id)
                print(f"reviewer grant #{grant.id}: active for user {grant.user_id}")
            else:
                grant, released = revoke_reviewer(db, args.user_id)
                print(f"reviewer grant #{grant.id}: revoked for user {grant.user_id}; released claims: {released}")
    except SafetyReviewConflict as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
