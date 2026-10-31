import argparse
import sys
from pathlib import Path

# Add backend directory to sys.path so app modules can be imported
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from pymongo import MongoClient
from app.core.config import settings


def dedupe_applications(db=None, apply: bool = False) -> dict:
    """
    Find and optionally remove duplicate records in applications and documents collections.
    Defaults to dry-run (apply=False).
    When apply=True, retains the most recently updated/created document and removes older duplicates.
    """
    if db is None:
        client = MongoClient(settings.MONGODB_URI)
        db = client[settings.DATABASE_NAME]

    report = {
        "applicationId_duplicates": [],
        "userId_duplicates": [],
        "document_slot_duplicates": [],
        "deleted_count": 0,
    }

    # 1. Check duplicate applicationId in applications
    pipeline_app_id = [
        {"$match": {"applicationId": {"$exists": True, "$ne": None}}},
        {"$group": {"_id": "$applicationId", "count": {"$sum": 1}, "ids": {"$push": "$_id"}}},
        {"$match": {"count": {"$gt": 1}}},
    ]
    for group in db["applications"].aggregate(pipeline_app_id):
        app_id = group["_id"]
        doc_ids = group["ids"]
        # Fetch docs to sort by createdAt/updatedAt
        docs = list(db["applications"].find({"_id": {"$in": doc_ids}}).sort([("updatedAt", -1), ("_id", -1)]))
        keep_doc = docs[0]
        remove_docs = docs[1:]
        report["applicationId_duplicates"].append({
            "key": app_id,
            "keep": str(keep_doc["_id"]),
            "remove": [str(d["_id"]) for d in remove_docs],
        })
        print(f"[applications] Duplicate applicationId '{app_id}': keeping {keep_doc['_id']}, candidates to remove: {[d['_id'] for d in remove_docs]}")
        if apply:
            for d in remove_docs:
                db["applications"].delete_one({"_id": d["_id"]})
                report["deleted_count"] += 1

    # 2. Check duplicate userId in applications
    pipeline_user_id = [
        {"$match": {"userId": {"$exists": True, "$ne": None}}},
        {"$group": {"_id": "$userId", "count": {"$sum": 1}, "ids": {"$push": "$_id"}}},
        {"$match": {"count": {"$gt": 1}}},
    ]
    for group in db["applications"].aggregate(pipeline_user_id):
        user_id = group["_id"]
        doc_ids = group["ids"]
        docs = list(db["applications"].find({"_id": {"$in": doc_ids}}).sort([("updatedAt", -1), ("_id", -1)]))
        keep_doc = docs[0]
        remove_docs = docs[1:]
        report["userId_duplicates"].append({
            "key": user_id,
            "keep": str(keep_doc["_id"]),
            "remove": [str(d["_id"]) for d in remove_docs],
        })
        print(f"[applications] Duplicate userId '{user_id}': keeping {keep_doc['_id']}, candidates to remove: {[d['_id'] for d in remove_docs]}")
        if apply:
            for d in remove_docs:
                db["applications"].delete_one({"_id": d["_id"]})
                report["deleted_count"] += 1

    # 3. Check duplicate (applicationId, documentType) in documents
    pipeline_doc_slots = [
        {"$match": {"applicationId": {"$exists": True}, "documentType": {"$exists": True}}},
        {"$group": {"_id": {"applicationId": "$applicationId", "documentType": "$documentType"}, "count": {"$sum": 1}, "ids": {"$push": "$_id"}}},
        {"$match": {"count": {"$gt": 1}}},
    ]
    for group in db["documents"].aggregate(pipeline_doc_slots):
        slot = group["_id"]
        doc_ids = group["ids"]
        docs = list(db["documents"].find({"_id": {"$in": doc_ids}}).sort([("updatedAt", -1), ("_id", -1)]))
        keep_doc = docs[0]
        remove_docs = docs[1:]
        report["document_slot_duplicates"].append({
            "key": slot,
            "keep": str(keep_doc["_id"]),
            "remove": [str(d["_id"]) for d in remove_docs],
        })
        print(f"[documents] Duplicate slot {slot}: keeping {keep_doc['_id']}, candidates to remove: {[d['_id'] for d in remove_docs]}")
        if apply:
            for d in remove_docs:
                db["documents"].delete_one({"_id": d["_id"]})
                report["deleted_count"] += 1

    total_conflicts = (
        len(report["applicationId_duplicates"])
        + len(report["userId_duplicates"])
        + len(report["document_slot_duplicates"])
    )
    if not apply:
        if total_conflicts > 0:
            print(f"\nDRY-RUN: {total_conflicts} conflict groups identified. No records deleted. Run with --apply to remove duplicates.")
        else:
            print("\nDRY-RUN: No duplicate records found in applications or documents.")
    else:
        print(f"\nAPPLIED: Deduplication complete. Deleted {report['deleted_count']} duplicate records.")

    return report


def main():
    parser = argparse.ArgumentParser(description="Find and deduplicate conflicting records in smart-enroll database.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply deletions to MongoDB. If not set, runs in dry-run mode without modifying data.",
    )
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"Starting deduplication scan in {mode} mode on database '{settings.DATABASE_NAME}'...")
    dedupe_applications(apply=args.apply)


if __name__ == "__main__":
    main()
