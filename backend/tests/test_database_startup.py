"""
Tests for Non-Destructive Database Startup & Explicit Deduplication (H3 / Task 2.3).
Verifies that:
1. Startup fails loudly with DatabaseInitializationError when duplicate keys exist on required unique indexes.
2. Startup never deletes documents automatically.
3. Index creation errors on documents collection are no longer swallowed with pass.
4. dedupe_applications script defaults to dry-run (no deletions) and removes duplicates with --apply.
"""

from datetime import datetime, timezone
import pytest
from pymongo import MongoClient

from app.core.config import settings
from app.core.database import (
    DatabaseInitializationError,
    close_mongo_connection,
    connect_to_mongo,
)
from scripts.dedupe_applications import dedupe_applications


@pytest.fixture(autouse=True)
def clean_test_database():
    """Ensure clean collections before and after test."""
    assert settings.DATABASE_NAME == "smartenroll_test", (
        f"Safety assertion failed: Expected 'smartenroll_test', got '{settings.DATABASE_NAME}'"
    )
    client = MongoClient(settings.MONGODB_URI)
    db = client[settings.DATABASE_NAME]
    # Drop all indexes and documents on collections tested
    for coll_name in ["applications", "documents", "users", "orchestration_runs"]:
        db[coll_name].drop_indexes()
        db[coll_name].delete_many({})
    close_mongo_connection()
    yield
    for coll_name in ["applications", "documents", "users", "orchestration_runs"]:
        db[coll_name].drop_indexes()
        db[coll_name].delete_many({})
    close_mongo_connection()


def test_startup_fails_loudly_on_duplicate_application_id_without_deleting_data():
    client = MongoClient(settings.MONGODB_URI)
    db = client[settings.DATABASE_NAME]

    # Insert two conflicting applications with identical applicationId
    doc1 = {
        "applicationId": "SE20269999",
        "userId": "user_111",
        "status": "DRAFT",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    doc2 = {
        "applicationId": "SE20269999",
        "userId": "user_222",
        "status": "DRAFT",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    db["applications"].insert_many([doc1, doc2])
    assert db["applications"].count_documents({"applicationId": "SE20269999"}) == 2

    # Attempting to start the application must raise DatabaseInitializationError
    with pytest.raises(DatabaseInitializationError) as exc_info:
        connect_to_mongo()

    assert "applications" in str(exc_info.value)
    assert "applicationId" in str(exc_info.value)

    # CRITICAL: Verify non-destructive behavior: NO documents were deleted!
    assert db["applications"].count_documents({"applicationId": "SE20269999"}) == 2


def test_startup_fails_loudly_on_duplicate_document_slot_without_swallowing():
    client = MongoClient(settings.MONGODB_URI)
    db = client[settings.DATABASE_NAME]

    # Insert two conflicting documents with same applicationId and documentType
    doc1 = {
        "documentId": "doc_111",
        "applicationId": "SE20269999",
        "documentType": "10TH_MARKSHEET",
        "status": "UPLOADED",
    }
    doc2 = {
        "documentId": "doc_222",
        "applicationId": "SE20269999",
        "documentType": "10TH_MARKSHEET",
        "status": "UPLOADED",
    }
    db["documents"].insert_many([doc1, doc2])
    assert db["documents"].count_documents({"applicationId": "SE20269999", "documentType": "10TH_MARKSHEET"}) == 2

    # Attempting to start the application must raise DatabaseInitializationError
    with pytest.raises(DatabaseInitializationError) as exc_info:
        connect_to_mongo()

    assert "documents" in str(exc_info.value)
    assert "applicationId" in str(exc_info.value)

    # Verify no documents were silently removed
    assert db["documents"].count_documents({"applicationId": "SE20269999", "documentType": "10TH_MARKSHEET"}) == 2


def test_dedupe_applications_dry_run_and_apply():
    client = MongoClient(settings.MONGODB_URI)
    db = client[settings.DATABASE_NAME]

    # Insert duplicates in applications and documents
    app1 = {"applicationId": "SE20269999", "userId": "u1", "updatedAt": "2026-01-01T00:00:00Z"}
    app2 = {"applicationId": "SE20269999", "userId": "u2", "updatedAt": "2026-01-02T00:00:00Z"}
    db["applications"].insert_many([app1, app2])

    d1 = {"documentId": "d1", "applicationId": "SE20269999", "documentType": "10TH_MARKSHEET", "updatedAt": "2026-01-01T00:00:00Z"}
    d2 = {"documentId": "d2", "applicationId": "SE20269999", "documentType": "10TH_MARKSHEET", "updatedAt": "2026-01-02T00:00:00Z"}
    db["documents"].insert_many([d1, d2])

    # 1. Dry run: finds duplicates but deletes 0
    dry_report = dedupe_applications(db=db, apply=False)
    assert len(dry_report["applicationId_duplicates"]) == 1
    assert len(dry_report["document_slot_duplicates"]) == 1
    assert dry_report["deleted_count"] == 0
    assert db["applications"].count_documents({}) == 2
    assert db["documents"].count_documents({}) == 2

    # 2. Apply: removes older duplicates
    apply_report = dedupe_applications(db=db, apply=True)
    assert apply_report["deleted_count"] == 2
    assert db["applications"].count_documents({}) == 1
    assert db["documents"].count_documents({}) == 1

    # 3. connect_to_mongo now succeeds cleanly
    connect_to_mongo()
    assert True
