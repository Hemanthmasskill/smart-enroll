import argparse
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import sys

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from pymongo import MongoClient
from app.core.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cleanup_abandoned_drafts")


def cleanup_abandoned_drafts(
    retention_days: int | None = None,
    dry_run: bool = False,
    db_name: str | None = None,
) -> dict[str, int]:
    """
    Purge abandoned DRAFT applications and their stored files older than the retention threshold.
    Encryption-at-rest notice: STORAGE_DIR should reside on an encrypted volume (LUKS / BitLocker / EBS KMS).
    """
    days = retention_days if retention_days is not None else settings.RETENTION_DAYS
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_iso = cutoff.isoformat()

    target_db = db_name or settings.DATABASE_NAME
    client = MongoClient(settings.MONGODB_URI)
    db = client[target_db]

    logger.info(
        "Scanning for abandoned DRAFT applications older than %d days (cutoff: %s) in '%s'...",
        days,
        cutoff_iso,
        target_db,
    )

    # Query for abandoned DRAFT applications
    query = {
        "status": "DRAFT",
        "$or": [
            {"updatedAt": {"$lt": cutoff_iso}},
            {"updatedAt": None, "createdAt": {"$lt": cutoff_iso}},
        ],
    }

    abandoned_apps = list(db["applications"].find(query))
    logger.info("Found %d abandoned draft application(s).", len(abandoned_apps))

    deleted_apps = 0
    deleted_docs = 0
    deleted_files = 0

    storage_root = settings.storage_path

    for app in abandoned_apps:
        app_id = app.get("applicationId")
        logger.info("Processing abandoned draft applicationId: %s", app_id)

        # Find associated documents
        docs = list(db["documents"].find({"applicationId": app_id}))
        for doc in docs:
            filename = doc.get("storedFilename")
            if filename:
                file_path = storage_root / filename
                if file_path.exists():
                    if not dry_run:
                        try:
                            file_path.unlink()
                            deleted_files += 1
                            logger.info("Deleted file: %s", file_path)
                        except Exception as e:
                            logger.error("Failed to delete file %s: %s", file_path, e)
                    else:
                        deleted_files += 1
                        logger.info("[DRY-RUN] Would delete file: %s", file_path)

            if not dry_run:
                db["documents"].delete_one({"_id": doc["_id"]})
            deleted_docs += 1

        if not dry_run:
            db["applications"].delete_one({"_id": app["_id"]})
        deleted_apps += 1

    client.close()

    summary = {
        "abandoned_applications_cleaned": deleted_apps,
        "documents_cleaned": deleted_docs,
        "files_deleted": deleted_files,
        "dry_run": dry_run,
        "retention_days": days,
    }
    logger.info("Cleanup completed: %s", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Cleanup abandoned draft applications and unlinked files beyond retention period."
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=None,
        help=f"Retention period in days (default: {settings.RETENTION_DAYS} from config)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate cleanup without deleting documents or database records.",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Target database name override.",
    )

    args = parser.parse_args()
    cleanup_abandoned_drafts(
        retention_days=args.retention_days,
        dry_run=args.dry_run,
        db_name=args.db,
    )


if __name__ == "__main__":
    main()
