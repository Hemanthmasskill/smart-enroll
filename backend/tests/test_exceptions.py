from datetime import datetime, timezone
import pytest
from bson import ObjectId
from fastapi.testclient import TestClient
from pymongo.database import Database

from app.api.exceptions import router as exceptions_router
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, get_password_hash
from app.main import app
from app.schemas.exceptions import ExceptionSeverity, ExceptionStatus, ExceptionType
from app.services.exceptions import (
    create_exception,
    ensure_exception_indexes,
    get_exception_by_id,
    list_exceptions,
    list_my_exceptions,
    resolve_exception,
    sync_exceptions_for_application,
)

# Ensure router is mounted for tests
if not any(getattr(route, "path", "").startswith(f"{settings.API_V1_STR}/exceptions") for route in app.routes):
    app.include_router(exceptions_router, prefix=f"{settings.API_V1_STR}/exceptions", tags=["Exceptions"])


@pytest.fixture
def api_client():
    return TestClient(app)


@pytest.fixture
def clean_db():
    db = get_db()
    db["users"].delete_many({})
    db["applications"].delete_many({})
    db["documents"].delete_many({})
    db["exceptions"].delete_many({})
    db["notifications"].delete_many({})
    db["orchestration_runs"].delete_many({})
    db["eligibility_evaluations"].delete_many({})
    ensure_exception_indexes(db)
    yield db
    db["exceptions"].delete_many({})
    db["notifications"].delete_many({})


@pytest.fixture
def admin_user(clean_db: Database):
    admin_doc = {
        "email": "admin.exceptions@smartenroll.edu",
        "hashed_password": get_password_hash("AdminPassword123!"),
        "role": "admin",
        "fullName": "Senior Admin",
        "tokenVersion": 1,
    }
    res = clean_db["users"].insert_one(admin_doc)
    admin_id = str(res.inserted_id)
    token = create_access_token(
        subject=admin_id,
        role="admin",
        token_version=1,
    )
    return {
        "userId": admin_id,
        "email": admin_doc["email"],
        "role": "admin",
        "fullName": admin_doc["fullName"],
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest.fixture
def applicant_user(clean_db: Database):
    app_user_doc = {
        "email": "applicant.one@example.com",
        "hashed_password": get_password_hash("ApplicantPassword123!"),
        "role": "applicant",
        "fullName": "Applicant One",
        "tokenVersion": 1,
    }
    res = clean_db["users"].insert_one(app_user_doc)
    user_id = str(res.inserted_id)
    token = create_access_token(
        subject=user_id,
        role="applicant",
        token_version=1,
    )

    app_id = "APP-TEST-EXC-001"
    application_doc = {
        "applicationId": app_id,
        "userId": user_id,
        "applicantId": user_id,
        "fullName": "Applicant One",
        "email": app_user_doc["email"],
        "programmeId": "mca",
        "status": "SUBMITTED",
        "tenthPercentage": "85.0",
        "twelfthPercentage": "86.0",
        "ugDegree": "BCA",
        "cgpa": "8.5",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    clean_db["applications"].insert_one(application_doc)

    return {
        "userId": user_id,
        "email": app_user_doc["email"],
        "role": "applicant",
        "fullName": app_user_doc["fullName"],
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
        "applicationId": app_id,
    }


@pytest.fixture
def second_applicant_user(clean_db: Database):
    app_user_doc = {
        "email": "applicant.two@example.com",
        "hashed_password": get_password_hash("ApplicantTwoPassword123!"),
        "role": "applicant",
        "fullName": "Applicant Two",
        "tokenVersion": 1,
    }
    res = clean_db["users"].insert_one(app_user_doc)
    user_id = str(res.inserted_id)
    token = create_access_token(
        subject=user_id,
        role="applicant",
        token_version=1,
    )

    app_id = "APP-TEST-EXC-002"
    application_doc = {
        "applicationId": app_id,
        "userId": user_id,
        "applicantId": user_id,
        "fullName": "Applicant Two",
        "email": app_user_doc["email"],
        "programmeId": "mba",
        "status": "SUBMITTED",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    clean_db["applications"].insert_one(application_doc)

    return {
        "userId": user_id,
        "email": app_user_doc["email"],
        "role": "applicant",
        "fullName": app_user_doc["fullName"],
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
        "applicationId": app_id,
    }


# =====================================================================
# Unit & Service Tests: Creation & Deterministic Severity
# =====================================================================

def test_exception_creation_for_all_nine_types(clean_db: Database, applicant_user: dict):
    """Verify that all 9 required exception types can be created with deterministic severity mapping."""
    app_id = applicant_user["applicationId"]

    expected_severities = {
        ExceptionType.ELIGIBILITY_CONFLICT.value: ExceptionSeverity.CRITICAL.value,
        ExceptionType.NAME_MISMATCH.value: ExceptionSeverity.HIGH.value,
        ExceptionType.DOB_MISMATCH.value: ExceptionSeverity.HIGH.value,
        ExceptionType.ACADEMIC_MISMATCH.value: ExceptionSeverity.HIGH.value,
        ExceptionType.UNREADABLE_DOCUMENT.value: ExceptionSeverity.HIGH.value,
        ExceptionType.INVALID_FILE.value: ExceptionSeverity.HIGH.value,
        ExceptionType.MISSING_DOCUMENT.value: ExceptionSeverity.MEDIUM.value,
        ExceptionType.DUPLICATE_DOCUMENT.value: ExceptionSeverity.MEDIUM.value,
        ExceptionType.VERIFICATION_UNAVAILABLE.value: ExceptionSeverity.LOW.value,
    }

    for exc_type, expected_sev in expected_severities.items():
        res = create_exception(
            db=clean_db,
            application_id=app_id,
            exception_type=exc_type,
            description=f"Automated test for {exc_type}",
            source="TEST_SUITE",
            metadata={"subject": f"item_{exc_type}"},
        )
        assert res is not None
        assert res["type"] == exc_type
        assert res["severity"] == expected_sev
        assert res["status"] == ExceptionStatus.OPEN.value
        assert res["applicationId"] == app_id
        assert res["userId"] == applicant_user["userId"]
        assert len(res["auditEvents"]) == 1
        assert res["auditEvents"][0]["action"] == "CREATED"


def test_invalid_exception_type_rejection(clean_db: Database, applicant_user: dict):
    """Verify that unsupported or invalid exception types are rejected."""
    with pytest.raises(Exception) as excinfo:
        create_exception(
            db=clean_db,
            application_id=applicant_user["applicationId"],
            exception_type="RANDOM_INVALID_TYPE",
            description="Should fail",
        )
    assert "Invalid exception type" in str(excinfo.value)


def test_no_false_exceptions_for_draft_application(clean_db: Database, applicant_user: dict):
    """Invariable: Do not create false exceptions for ordinary draft applications."""
    app_id = applicant_user["applicationId"]
    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "DRAFT"}})

    res = create_exception(
        db=clean_db,
        application_id=app_id,
        exception_type=ExceptionType.MISSING_DOCUMENT.value,
        description="Missing document should not be flagged in draft",
    )
    assert res is None
    assert clean_db["exceptions"].count_documents({"applicationId": app_id}) == 0


def test_duplicate_active_exception_prevention_idempotency(clean_db: Database, applicant_user: dict):
    """Verify that creating an exception for the same issue returns the existing active exception."""
    app_id = applicant_user["applicationId"]
    meta = {"documentType": "10TH_MARKSHEET"}

    first = create_exception(
        db=clean_db,
        application_id=app_id,
        exception_type=ExceptionType.NAME_MISMATCH.value,
        description="Candidate name mismatch on 10th marksheet",
        metadata=meta,
    )
    assert first is not None

    # Second attempt with identical dedupe subject
    second = create_exception(
        db=clean_db,
        application_id=app_id,
        exception_type=ExceptionType.NAME_MISMATCH.value,
        description="Second attempt at candidate name mismatch",
        metadata=meta,
    )
    assert second is not None
    assert second["exceptionId"] == first["exceptionId"]
    assert clean_db["exceptions"].count_documents({"applicationId": app_id}) == 1


# =====================================================================
# Notification Compatibility Tests
# =====================================================================

def test_notification_record_structure_compatibility(clean_db: Database, applicant_user: dict):
    """
    Verify notification record in 'notifications' collection complies with Increment 18:
    notificationId, userId, applicantId, applicationId, type, title, message, read, createdAt, metadata, dedupeKey.
    """
    app_id = applicant_user["applicationId"]
    exc = create_exception(
        db=clean_db,
        application_id=app_id,
        exception_type=ExceptionType.DOB_MISMATCH.value,
        description="DOB differs from application record",
    )
    assert exc is not None

    notif = clean_db["notifications"].find_one({"applicationId": app_id, "type": "EXCEPTION_CREATED"})
    assert notif is not None
    assert notif["notificationId"].startswith("NOTIF-")
    assert notif["userId"] == applicant_user["userId"]
    assert notif["applicantId"] == applicant_user["userId"]
    assert notif["applicationId"] == app_id
    assert notif["read"] is False
    assert notif["metadata"]["exceptionId"] == exc["exceptionId"]
    assert notif["dedupeKey"] == f"NOTIF:EXC:{exc['exceptionId']}:CREATED"


# =====================================================================
# API Authorization & Ownership Boundary Tests
# =====================================================================

def test_admin_list_exceptions_with_filters(api_client: TestClient, admin_user: dict, applicant_user: dict, clean_db: Database):
    """Verify admin can list exceptions and filter by status, severity, and type."""
    app_id = applicant_user["applicationId"]
    create_exception(clean_db, app_id, ExceptionType.NAME_MISMATCH.value, "Name mismatch", metadata={"field": "name"})
    create_exception(clean_db, app_id, ExceptionType.MISSING_DOCUMENT.value, "Missing doc", metadata={"field": "doc"})

    res = api_client.get("/api/v1/exceptions", headers=admin_user["headers"])
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 2

    # Filter by severity HIGH
    res_high = api_client.get("/api/v1/exceptions?severity=HIGH", headers=admin_user["headers"])
    assert res_high.status_code == 200
    data_high = res_high.json()
    assert all(item["severity"] == "HIGH" for item in data_high)
    assert any(item["type"] == "NAME_MISMATCH" for item in data_high)

    # Filter by type MISSING_DOCUMENT
    res_type = api_client.get("/api/v1/exceptions?type=MISSING_DOCUMENT", headers=admin_user["headers"])
    assert res_type.status_code == 200
    data_type = res_type.json()
    assert all(item["type"] == "MISSING_DOCUMENT" for item in data_type)


def test_applicant_cannot_access_admin_exception_list(api_client: TestClient, applicant_user: dict):
    """Verify applicant role is rejected with 403 when trying to access admin exceptions list."""
    res = api_client.get("/api/v1/exceptions", headers=applicant_user["headers"])
    assert res.status_code == 403


def test_applicant_can_access_own_exceptions(api_client: TestClient, applicant_user: dict, clean_db: Database):
    """Verify applicant can access /api/v1/exceptions/me for their own records."""
    app_id = applicant_user["applicationId"]
    create_exception(clean_db, app_id, ExceptionType.NAME_MISMATCH.value, "My own exception")

    res = api_client.get("/api/v1/exceptions/me", headers=applicant_user["headers"])
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 1
    assert items[0]["applicationId"] == app_id


def test_strict_cross_applicant_isolation_on_detail_endpoint(
    api_client: TestClient, applicant_user: dict, second_applicant_user: dict, clean_db: Database
):
    """Verify an applicant cannot view another applicant's exception details (403 Forbidden)."""
    exc1 = create_exception(
        clean_db, applicant_user["applicationId"], ExceptionType.ACADEMIC_MISMATCH.value, "Marks discrepancy"
    )
    assert exc1 is not None
    exc_id = exc1["exceptionId"]

    # Owner applicant accessing own exception: 200 OK
    res_owner = api_client.get(f"/api/v1/exceptions/{exc_id}", headers=applicant_user["headers"])
    assert res_owner.status_code == 200

    # Second applicant accessing first applicant's exception: 403 Forbidden
    res_second = api_client.get(f"/api/v1/exceptions/{exc_id}", headers=second_applicant_user["headers"])
    assert res_second.status_code == 403


# =====================================================================
# Resolution & Precondition Tests
# =====================================================================

def test_empty_or_whitespace_resolution_reason_rejected(
    api_client: TestClient, admin_user: dict, applicant_user: dict, clean_db: Database
):
    """Verify that resolution requests with empty or short justification reasons are rejected."""
    exc = create_exception(
        clean_db, applicant_user["applicationId"], ExceptionType.NAME_MISMATCH.value, "Name mismatch"
    )
    exc_id = exc["exceptionId"]

    # Empty string
    res_empty = api_client.post(
        f"/api/v1/exceptions/{exc_id}/resolve",
        headers=admin_user["headers"],
        json={"resolutionReason": ""},
    )
    assert res_empty.status_code in (400, 422)

    # Whitespace only
    res_ws = api_client.post(
        f"/api/v1/exceptions/{exc_id}/resolve",
        headers=admin_user["headers"],
        json={"resolutionReason": "    "},
    )
    assert res_ws.status_code in (400, 422)

    # Too short (< 5 chars)
    res_short = api_client.post(
        f"/api/v1/exceptions/{exc_id}/resolve",
        headers=admin_user["headers"],
        json={"resolutionReason": "ok"},
    )
    assert res_short.status_code in (400, 422)


def test_applicant_cannot_resolve_exceptions(
    api_client: TestClient, applicant_user: dict, clean_db: Database
):
    """Verify that applicants cannot resolve exceptions (403 Forbidden)."""
    exc = create_exception(
        clean_db, applicant_user["applicationId"], ExceptionType.NAME_MISMATCH.value, "Name mismatch"
    )
    exc_id = exc["exceptionId"]

    res = api_client.post(
        f"/api/v1/exceptions/{exc_id}/resolve",
        headers=applicant_user["headers"],
        json={"resolutionReason": "Trying to self-resolve"},
    )
    assert res.status_code == 403


def test_missing_document_resolution_precondition_enforcement(
    api_client: TestClient, admin_user: dict, applicant_user: dict, clean_db: Database
):
    """
    Verify MISSING_DOCUMENT exception resolution requires the missing document to be uploaded.
    Cannot resolve if the document is still missing.
    """
    app_id = applicant_user["applicationId"]
    exc = create_exception(
        clean_db,
        app_id,
        ExceptionType.MISSING_DOCUMENT.value,
        "Missing Transfer Certificate",
        metadata={"documentType": "TRANSFER_CERTIFICATE"},
    )
    exc_id = exc["exceptionId"]

    # 1. Attempt resolution while document is NOT uploaded: must fail 400
    res_fail = api_client.post(
        f"/api/v1/exceptions/{exc_id}/resolve",
        headers=admin_user["headers"],
        json={"resolutionReason": "Trying to clear without file"},
    )
    assert res_fail.status_code == 400
    assert "has not been uploaded yet" in res_fail.json()["detail"]

    # 2. Upload/insert the document
    clean_db["documents"].insert_one({
        "documentId": "DOC-TC-123",
        "applicationId": app_id,
        "userId": applicant_user["userId"],
        "documentType": "TRANSFER_CERTIFICATE",
        "status": "UPLOADED",
        "processingStatus": "UPLOADED",
    })

    # 3. Now attempt resolution: must succeed
    res_ok = api_client.post(
        f"/api/v1/exceptions/{exc_id}/resolve",
        headers=admin_user["headers"],
        json={"resolutionReason": "Transfer Certificate verified and accepted manually"},
    )
    assert res_ok.status_code == 200
    data = res_ok.json()
    assert data["status"] == "RESOLVED"
    assert data["resolutionReason"] == "Transfer Certificate verified and accepted manually"
    assert data["resolvedBy"]["email"] == admin_user["email"]


def test_concurrent_double_resolution_conflict(
    api_client: TestClient, admin_user: dict, applicant_user: dict, clean_db: Database
):
    """Verify atomic CAS resolution prevents duplicate resolution (409 Conflict on second attempt)."""
    exc = create_exception(
        clean_db, applicant_user["applicationId"], ExceptionType.ACADEMIC_MISMATCH.value, "Marks mismatch"
    )
    exc_id = exc["exceptionId"]

    # First resolution: 200 OK
    res1 = api_client.post(
        f"/api/v1/exceptions/{exc_id}/resolve",
        headers=admin_user["headers"],
        json={"resolutionReason": "Approved mark sheet revision after university confirmation"},
    )
    assert res1.status_code == 200

    # Second resolution: 409 Conflict
    res2 = api_client.post(
        f"/api/v1/exceptions/{exc_id}/resolve",
        headers=admin_user["headers"],
        json={"resolutionReason": "Duplicate attempt to resolve"},
    )
    assert res2.status_code == 409


def test_resolution_audit_history_and_notification(clean_db: Database, admin_user: dict, applicant_user: dict):
    """Verify resolution records audit history and dispatches resolution notification."""
    app_id = applicant_user["applicationId"]
    exc = create_exception(
        clean_db, app_id, ExceptionType.DOB_MISMATCH.value, "DOB mismatch on TC"
    )
    exc_id = exc["exceptionId"]

    resolved = resolve_exception(
        db=clean_db,
        exception_id=exc_id,
        resolution_reason="Birth certificate presented in person and verified",
        admin_user=admin_user,
        resume_workflow=False,
    )

    assert resolved["status"] == "RESOLVED"
    assert resolved["resolvedAt"] is not None
    assert resolved["resolvedBy"]["email"] == admin_user["email"]
    assert len(resolved["auditEvents"]) == 2
    assert resolved["auditEvents"][1]["action"] == "RESOLVED"
    assert resolved["auditEvents"][1]["details"]["resolutionReason"] == "Birth certificate presented in person and verified"

    # Verify notification record in notifications collection
    notif = clean_db["notifications"].find_one({"applicationId": app_id, "type": "EXCEPTION_RESOLVED"})
    assert notif is not None
    assert notif["metadata"]["exceptionId"] == exc_id
    assert notif["dedupeKey"] == f"NOTIF:EXC:{exc_id}:RESOLVED"


def test_resolution_does_not_override_deterministic_eligibility(clean_db: Database, admin_user: dict, applicant_user: dict):
    """
    Invariant: Resolution clears procedural exception only.
    It must NOT permit an administrator to override deterministic eligibility rules or mark PROCESSING_COMPLETE directly.
    """
    app_id = applicant_user["applicationId"]
    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "EXCEPTION"}})

    exc = create_exception(
        clean_db,
        app_id,
        ExceptionType.ELIGIBILITY_CONFLICT.value,
        "Failed min percentage rule",
        metadata={"ruleId": "MIN_PERCENTAGE"},
    )
    exc_id = exc["exceptionId"]

    resolve_exception(
        db=clean_db,
        exception_id=exc_id,
        resolution_reason="Candidate submitted revised transcript for re-evaluation",
        admin_user=admin_user,
        resume_workflow=False,
    )

    app_after = clean_db["applications"].find_one({"applicationId": app_id})
    # Target status must be ELIGIBILITY_CHECK (to run through deterministic engine), never ELIGIBLE or PROCESSING_COMPLETE!
    assert app_after["status"] == "ELIGIBILITY_CHECK"
    assert app_after["status"] != "ELIGIBLE"
    assert app_after["status"] != "PROCESSING_COMPLETE"


def test_sync_exceptions_for_application(clean_db: Database, applicant_user: dict):
    """Verify sync_exceptions_for_application scans and generates exceptions for discrepancies."""
    app_id = applicant_user["applicationId"]

    # Insert a document with validation mismatch
    clean_db["documents"].insert_one({
        "documentId": "DOC-UG-999",
        "applicationId": app_id,
        "userId": applicant_user["userId"],
        "documentType": "UG_MARKSHEET",
        "status": "MISMATCH",
        "validationStatus": "MISMATCH",
        "validationResult": {
            "validationStatus": "MISMATCH",
            "fieldResults": {"candidateName": {"status": "MISMATCH"}},
            "reasons": ["Extracted name does not match application name"],
        },
    })

    found = sync_exceptions_for_application(clean_db, app_id)
    assert len(found) >= 1
    name_exc = next((e for e in found if e["type"] == ExceptionType.NAME_MISMATCH.value), None)
    assert name_exc is not None
    assert name_exc["severity"] == ExceptionSeverity.HIGH.value


def test_resolution_and_safe_orchestration_resumption(clean_db: Database, admin_user: dict, applicant_user: dict):
    """
    Verify that resolving the blocking exception updates document clearance,
    transitions application from EXCEPTION to PROCESSING, and safely resumes orchestration.
    """
    from app.agents.orchestrator import AgentOrchestrator, OrchestrationOutcome

    app_id = applicant_user["applicationId"]
    clean_db["applications"].update_one(
        {"applicationId": app_id},
        {"$set": {"programmeId": "mba", "status": "EXCEPTION", "statusReason": "Document validation discrepancy"}}
    )

    # Insert 6 documents; 5 are VALIDATED, 1 (UG_MARKSHEET) has MANUAL_REVIEW
    from app.agents.tools import REQUIRED_DOCUMENT_TYPES
    for dtype in REQUIRED_DOCUMENT_TYPES:
        doc_status = "MANUAL_REVIEW" if dtype == "UG_MARKSHEET" else "VALIDATED"
        doc_data = {
            "documentId": f"DOC-{dtype}-RESUME",
            "applicationId": app_id,
            "userId": applicant_user["userId"],
            "documentType": dtype,
            "fileName": f"{dtype.lower()}.pdf",
            "status": doc_status,
            "validationStatus": doc_status,
            "processingStatus": "COMPLETED",
        }
        if dtype == "UG_MARKSHEET":
            doc_data["processingResult"] = {
                "processingState": "COMPLETED",
                "fields": {
                    "cgpa": {"rawValue": "8.5", "normalizedValue": 8.5},
                    "cgpaScale": {"rawValue": "10", "normalizedValue": 10.0},
                    "candidateName": {"rawValue": "Applicant One", "normalizedValue": "Applicant One"},
                },
            }
        elif dtype == "DEGREE_CERTIFICATE":
            doc_data["processingResult"] = {
                "processingState": "COMPLETED",
                "fields": {
                    "degreeName": {"rawValue": "Bachelor of Computer Applications", "normalizedValue": "BCA"},
                    "candidateName": {"rawValue": "Applicant One", "normalizedValue": "Applicant One"},
                },
            }
        clean_db["documents"].insert_one(doc_data)

    # While in EXCEPTION, orchestrator run returns MANUAL_REVIEW_REQUIRED immediately
    user_doc = clean_db["users"].find_one({"_id": ObjectId(applicant_user["userId"])})
    orch = AgentOrchestrator(db=clean_db)
    res_before = orch.run(app_id, user_doc)
    assert res_before.outcome == OrchestrationOutcome.MANUAL_REVIEW_REQUIRED
    assert res_before.currentApplicationStatus == "EXCEPTION"

    # Create the blocking exception
    exc = create_exception(
        clean_db,
        app_id,
        ExceptionType.NAME_MISMATCH.value,
        "Name variation on UG marksheet",
        metadata={"documentId": "DOC-UG_MARKSHEET-RESUME", "documentType": "UG_MARKSHEET"},
    )
    assert exc is not None

    # Resolve the exception as admin with workflow resumption enabled
    resolved = resolve_exception(
        db=clean_db,
        exception_id=exc["exceptionId"],
        resolution_reason="Affidavit submitted in admissions office confirming name variation.",
        admin_user=admin_user,
        resume_workflow=True,
    )
    assert resolved["status"] == "RESOLVED"

    # Verify UG_MARKSHEET is now VALIDATED
    ug_doc = clean_db["documents"].find_one({"documentId": "DOC-UG_MARKSHEET-RESUME"})
    assert ug_doc["validationStatus"] == "VALIDATED"
    assert ug_doc["status"] == "VALIDATED"

    # Verify application advanced past EXCEPTION
    app_after = clean_db["applications"].find_one({"applicationId": app_id})
    assert app_after["status"] != "EXCEPTION"
    # With all documents validated, the orchestrator safely advanced past EXCEPTION to conclusion
    assert app_after["status"] in ("PROCESSING", "VERIFICATION_IN_PROGRESS", "ELIGIBILITY_CHECK", "ELIGIBLE", "PROCESSING_COMPLETE")

