from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import pytest
from bson import ObjectId
from pymongo import MongoClient

from app.core.config import settings
from app.schemas.verification import AuthoritativeVerificationRecord
from app.services.ocr.classifier import CLASSIFICATION_PATTERNS, classify_document
from app.services.ocr.field_extractor import MAX_OCR_TEXT_LENGTH, extract_fields_from_text
from app.services.scanner import NoopUploadScanner, get_upload_scanner
from app.services.verification.dob_parser import parse_and_compare_dob
from app.services.verification.name_matcher import compare_names
from app.services.verification.numeric_comparer import (
    CGPA_TOLERANCE,
    PERCENTAGE_TOLERANCE,
    compare_cgpa,
    compare_percentages,
)
from scripts.cleanup_abandoned_drafts import cleanup_abandoned_drafts
from scripts.create_admin import create_admin


@pytest.fixture
def test_db():
    client = MongoClient(settings.MONGODB_URI)
    db = client[settings.DATABASE_NAME]
    yield db
    client.close()


def test_field_extractor_input_length_capping_and_redos_resistance():
    """
    Verify field extractor caps input to MAX_OCR_TEXT_LENGTH and
    terminates promptly on adversarial repetitive inputs without ReDoS.
    """
    adversarial_text = ("Percentage: 88.5%\nCandidate Name: Jane Doe\n" + ("A " * 60_000))
    assert len(adversarial_text) > MAX_OCR_TEXT_LENGTH

    start = datetime.now()
    fields = extract_fields_from_text(adversarial_text)
    elapsed = (datetime.now() - start).total_seconds()

    # Must complete in under 2 seconds even on large/adversarial input
    assert elapsed < 2.0
    assert fields.percentage is not None
    assert fields.percentage.normalizedValue == 88.5
    assert fields.candidateName is not None
    assert fields.candidateName.normalizedValue == "Jane Doe"


def test_classifier_padding_does_not_inflate_confidence():
    """
    Verify text padding and repeated matches cannot game confidence scoring beyond 0.98.
    """
    repeated_text = "secondary school examination matriculation sslc " * 500
    res = classify_document(repeated_text)
    assert res.predictedType == "10TH_MARKSHEET"
    assert res.confidence <= 0.98


def test_name_matcher_script_mismatch_and_all_initials():
    """
    Verify conservative name matching thresholds:
    - Differing scripts return MANUAL_REVIEW.
    - All-initials return MANUAL_REVIEW.
    - Exact multiset token match returns MATCH.
    - Contradicting tokens return MISMATCH.
    """
    # 1. All-initials rejection
    status, msg = compare_names("H. M. P.", "Hemanth Madanapalli")
    assert status == "MANUAL_REVIEW"
    assert "solely of single-letter initials" in msg

    # 2. Script mismatch (Latin vs Tamil)
    status, msg = compare_names("ஹேமந்த்", "Hemanth M.P.")
    assert status == "MANUAL_REVIEW"
    assert "Different scripts detected" in msg

    # 3. Exact multiset agreement
    status, msg = compare_names("Hemanth M.P.", "M.P. Hemanth")
    assert status == "MATCH"

    # 4. Conflicting names
    status, msg = compare_names("Suresh Kumar", "Hemanth Kumar")
    assert status == "MISMATCH"


def test_numeric_comparer_tolerances():
    """
    Verify explicit numeric tolerance boundaries:
    - Percentage within PERCENTAGE_TOLERANCE (±0.5%) matches; outside mismatches.
    - CGPA within CGPA_TOLERANCE (±0.05) matches; outside mismatches.
    """
    # Percentage tolerance
    status, _, _ = compare_percentages(85.3, None, None, "85.0")
    assert status == "MATCH"

    status, _, _ = compare_percentages(85.6, None, None, "85.0")
    assert status == "MISMATCH"

    # CGPA tolerance
    status, _, _ = compare_cgpa("8.53", "8.50")
    assert status == "MATCH"

    status, _, _ = compare_cgpa("8.56", "8.50")
    assert status == "MISMATCH"


def test_dob_parser_ambiguity():
    """
    Verify ambiguous numeric dates (both parts <= 12) return MANUAL_REVIEW,
    while unambiguous dates (> 12) or named months match decisively.
    """
    # Ambiguous: 03/04/2001 (March 4 vs April 3)
    status, msg, _ = parse_and_compare_dob("03/04/2001", "2001-04-03")
    assert status == "MANUAL_REVIEW"
    assert "ambiguous between DD/MM and MM/DD" in msg

    # Unambiguous: 25/04/2001 (Day is 25)
    status, msg, parsed = parse_and_compare_dob("25/04/2001", "2001-04-25")
    assert status == "MATCH"
    assert parsed == date(2001, 4, 25)

    # Named month: 04 March 2001
    status, msg, parsed = parse_and_compare_dob("04 March 2001", "2001-03-04")
    assert status == "MATCH"
    assert parsed == date(2001, 3, 4)


def test_synthetic_authoritative_markers():
    """
    Verify AuthoritativeVerificationRecord default schema enforces isSimulated=True
    and carries non-live disclaimer.
    """
    record = AuthoritativeVerificationRecord(status="SIMULATED_MATCH")
    assert record.isSimulated is True
    assert "Simulated record" in record.disclaimer
    assert record.provider == "SyntheticDigiLockerProvider"


def test_create_admin_password_policy(test_db):
    """
    Verify create_admin rejects weak passwords and requires compliance with password policy.
    """
    # Clean up test user if present
    test_db["users"].delete_many({"email": {"$in": ["admin_test_weak@smartenroll.edu", "admin_test_strong@smartenroll.edu"]}})

    # Weak password rejected
    success = create_admin("admin_test_weak@smartenroll.edu", "Admin Test", "weak")
    assert success is False

    # Compliant password succeeds
    success = create_admin(
        "admin_test_strong@smartenroll.edu",
        "Admin Test",
        "StrongAdminP@ssw0rd2026!",
    )
    assert success is True

    # Verify user in database
    user = test_db["users"].find_one({"email": "admin_test_strong@smartenroll.edu"})
    assert user is not None
    assert user["role"] == "admin"
    assert user["tokenVersion"] == 1
    assert user["is_active"] is True

    test_db["users"].delete_many({"email": "admin_test_strong@smartenroll.edu"})


def test_upload_scanner_interface(tmp_path):
    """
    Verify upload scanner interface and NoopUploadScanner behavior.
    """
    scanner = get_upload_scanner()
    assert isinstance(scanner, NoopUploadScanner)

    dummy_file = tmp_path / "test.pdf"
    dummy_file.write_bytes(b"%PDF-1.4 dummy content")

    is_clean, msg = scanner.scan_file(dummy_file)
    assert is_clean is True
    assert "clean" in msg.lower()

    # Non-existent file
    non_existent = tmp_path / "does_not_exist.pdf"
    is_clean, msg = scanner.scan_file(non_existent)
    assert is_clean is False


def test_cleanup_abandoned_drafts(test_db, tmp_path, monkeypatch):
    """
    Verify cleanup script deletes abandoned DRAFT applications older than retention days
    and unlinks storage files, while preserving active/submitted applications and recent drafts.
    """
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))

    old_date = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    recent_date = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()

    # 1. Old abandoned draft with a file
    old_file = tmp_path / "doc_old_draft.pdf"
    old_file.write_bytes(b"old file content")

    test_db["applications"].insert_one({
        "applicationId": "SE_ABANDONED_001",
        "status": "DRAFT",
        "updatedAt": old_date,
        "createdAt": old_date,
    })
    test_db["documents"].insert_one({
        "applicationId": "SE_ABANDONED_001",
        "documentType": "10TH_MARKSHEET",
        "storedFileName": "doc_old_draft.pdf",
    })

    # 2. Recent draft (should NOT be deleted)
    test_db["applications"].insert_one({
        "applicationId": "SE_RECENT_002",
        "status": "DRAFT",
        "updatedAt": recent_date,
        "createdAt": recent_date,
    })

    # 3. Old SUBMITTED application (should NOT be deleted)
    test_db["applications"].insert_one({
        "applicationId": "SE_SUBMITTED_003",
        "status": "SUBMITTED",
        "updatedAt": old_date,
        "createdAt": old_date,
    })

    summary = cleanup_abandoned_drafts(
        retention_days=30,
        apply=True,
        db_name=settings.TEST_DATABASE_NAME,
    )

    assert summary["abandoned_applications_cleaned"] == 1
    assert summary["documents_cleaned"] == 1
    assert summary["files_deleted"] == 1
    assert not old_file.exists()

    # Confirm recent draft and submitted app still exist
    assert test_db["applications"].find_one({"applicationId": "SE_RECENT_002"}) is not None
    assert test_db["applications"].find_one({"applicationId": "SE_SUBMITTED_003"}) is not None
    assert test_db["applications"].find_one({"applicationId": "SE_ABANDONED_001"}) is None

    # Clean up test records
    test_db["applications"].delete_many({"applicationId": {"$in": ["SE_RECENT_002", "SE_SUBMITTED_003"]}})


def test_cleanup_abandoned_drafts_dry_run_default_removes_nothing(test_db, tmp_path, monkeypatch):
    """
    Verify cleanup script defaults to dry-run (apply=False) and deletes zero database records or physical files.
    """
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))

    old_date = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    old_file = tmp_path / "doc_dry_run.pdf"
    old_file.write_bytes(b"important content that must not be deleted in dry run")

    test_db["applications"].insert_one({
        "applicationId": "SE_DRYRUN_001",
        "status": "DRAFT",
        "updatedAt": old_date,
        "createdAt": old_date,
    })
    test_db["documents"].insert_one({
        "applicationId": "SE_DRYRUN_001",
        "documentType": "10TH_MARKSHEET",
        "storedFileName": "doc_dry_run.pdf",
    })

    # Run without apply argument -> dry_run default
    summary = cleanup_abandoned_drafts(
        retention_days=30,
        db_name=settings.TEST_DATABASE_NAME,
    )

    assert summary["dry_run"] is True
    assert summary["applied"] is False
    assert summary["abandoned_applications_cleaned"] == 1
    assert summary["documents_cleaned"] == 1
    assert summary["files_deleted"] == 1

    # Files and database records MUST still exist
    assert old_file.exists()
    assert test_db["applications"].find_one({"applicationId": "SE_DRYRUN_001"}) is not None
    assert test_db["documents"].find_one({"applicationId": "SE_DRYRUN_001"}) is not None

    # Cleanup
    test_db["applications"].delete_many({"applicationId": "SE_DRYRUN_001"})
    test_db["documents"].delete_many({"applicationId": "SE_DRYRUN_001"})
    if old_file.exists():
        old_file.unlink()


def test_cleanup_abandoned_drafts_apply_removes_record_and_file(test_db, tmp_path, monkeypatch):
    """
    Verify --apply (apply=True) permanently removes both the MongoDB document/application records and physical file.
    """
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))

    old_date = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    old_file = tmp_path / "doc_apply_test.pdf"
    old_file.write_bytes(b"content to be permanently deleted")

    test_db["applications"].insert_one({
        "applicationId": "SE_APPLY_001",
        "status": "DRAFT",
        "updatedAt": old_date,
        "createdAt": old_date,
    })
    test_db["documents"].insert_one({
        "applicationId": "SE_APPLY_001",
        "documentType": "12TH_MARKSHEET",
        "storedFileName": "doc_apply_test.pdf",
    })

    summary = cleanup_abandoned_drafts(
        retention_days=30,
        apply=True,
        db_name=settings.TEST_DATABASE_NAME,
    )

    assert summary["dry_run"] is False
    assert summary["applied"] is True
    assert summary["abandoned_applications_cleaned"] == 1
    assert summary["documents_cleaned"] == 1
    assert summary["files_deleted"] == 1

    # Verify physical file is gone
    assert not old_file.exists()
    # Verify MongoDB records are gone
    assert test_db["applications"].find_one({"applicationId": "SE_APPLY_001"}) is None
    assert test_db["documents"].find_one({"applicationId": "SE_APPLY_001"}) is None


def test_cleanup_abandoned_drafts_rejects_paths_outside_storage_dir(test_db, tmp_path, monkeypatch):
    """
    Verify files with traversal paths resolving outside STORAGE_DIR are strictly rejected and not deleted.
    """
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "secret.txt"
    outside_file.write_bytes(b"critical system secret")

    monkeypatch.setattr(settings, "STORAGE_DIR", str(storage_dir))

    old_date = (datetime.now(timezone.utc) - timedelta(days=50)).isoformat()
    test_db["applications"].insert_one({
        "applicationId": "SE_TRAVERSAL_001",
        "status": "DRAFT",
        "updatedAt": old_date,
        "createdAt": old_date,
    })
    # Path traversal attempt pointing outside storage_dir
    test_db["documents"].insert_one({
        "applicationId": "SE_TRAVERSAL_001",
        "documentType": "GOVERNMENT_ID",
        "storedFileName": "../outside/secret.txt",
    })

    summary = cleanup_abandoned_drafts(
        retention_days=30,
        apply=True,
        db_name=settings.TEST_DATABASE_NAME,
    )

    # The outside file must NOT be deleted
    assert outside_file.exists()
    assert outside_file.read_bytes() == b"critical system secret"
    # The application and document records are cleaned, but 0 files were deleted
    assert summary["files_deleted"] == 0

    # Cleanup
    test_db["applications"].delete_many({"applicationId": "SE_TRAVERSAL_001"})
    test_db["documents"].delete_many({"applicationId": "SE_TRAVERSAL_001"})
