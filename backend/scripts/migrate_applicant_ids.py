import argparse
import re
import secrets
import sys
from pathlib import Path

# Add backend directory to sys.path so app modules can be imported
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from app.core.config import settings

APPLICANT_ID_PATTERN = re.compile(r"^APL-[0-9A-F]{12}$")


def generate_unique_applicant_id(db) -> str:
    """Generate a 12-hex-character cryptographically secure applicant ID that does not exist in db."""
    while True:
        candidate = f"APL-{secrets.token_hex(6).upper()}"
        if not db["users"].find_one({"applicant_id": candidate}):
            return candidate


def migrate_applicant_ids(apply_changes: bool = False, db=None) -> dict:
    """
    Idempotent migration of user applicant IDs.
    Finds applicants with missing, non-compliant, or duplicate applicant IDs,
    generates secure unique IDs, and updates users, applications, and documents collections.
    """
    if db is None:
        client = MongoClient(settings.MONGODB_URI)
        db = client[settings.DATABASE_NAME]

    users = list(db["users"].find({"role": "applicant"}))
    seen_ids = set()
    needs_migration = []

    for user in users:
        app_id = user.get("applicant_id")
        user_id = str(user["_id"])
        is_invalid = not app_id or not APPLICANT_ID_PATTERN.match(str(app_id))
        is_duplicate = app_id in seen_ids

        if is_invalid or is_duplicate:
            needs_migration.append((user, app_id, is_duplicate))
        else:
            seen_ids.add(app_id)

    print(f"Total applicants found: {len(users)}")
    print(f"Applicants needing migration: {len(needs_migration)}")

    migrated_count = 0
    for user, old_id, is_dup in needs_migration:
        user_id = str(user["_id"])
        new_id = generate_unique_applicant_id(db)
        seen_ids.add(new_id)

        reason = "duplicate ID" if is_dup else "legacy or invalid ID format"
        print(f"User {user_id} ({user.get('email')}) - Old: {old_id} -> New: {new_id} ({reason})")

        if apply_changes:
            db["users"].update_one({"_id": user["_id"]}, {"$set": {"applicant_id": new_id}})
            app_result = db["applications"].update_many(
                {"userId": user_id},
                {"$set": {"applicantId": new_id}},
            )
            doc_result = db["documents"].update_many(
                {"userId": user_id},
                {"$set": {"applicantId": new_id}},
            )
            print(f"  -> Applied: updated user, {app_result.modified_count} application(s), {doc_result.modified_count} document(s).")
            migrated_count += 1

    if apply_changes:
        # Ensure unique sparse index on users.applicant_id
        try:
            db["users"].create_index("applicant_id", unique=True, partialFilterExpression={"applicant_id": {"$type": "string"}})
            print("Successfully ensured unique sparse index on users.applicant_id")
        except DuplicateKeyError as e:
            print(f"Error creating unique index on users.applicant_id: {e}", file=sys.stderr)
            raise
    else:
        if needs_migration:
            print("\nDRY-RUN MODE: No changes written to database. Run with --apply to execute migration.")
        else:
            print("\nAll applicant IDs are compliant and unique. No migration needed.")

    return {
        "total_applicants": len(users),
        "needs_migration": len(needs_migration),
        "migrated": migrated_count,
    }


def main():
    parser = argparse.ArgumentParser(description="Migrate legacy or collision-prone applicant IDs to secure format.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes to MongoDB. If not set, runs in dry-run mode.",
    )
    args = parser.parse_args()

    mode_str = "APPLY" if args.apply else "DRY-RUN"
    print(f"Starting applicant ID migration in {mode_str} mode on database '{settings.DATABASE_NAME}'...")
    migrate_applicant_ids(apply_changes=args.apply)


if __name__ == "__main__":
    main()
