from datetime import datetime, timezone
import uuid
import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.main import app

client = TestClient(app)


@pytest.fixture
def test_db():
    mongo_client = MongoClient(settings.MONGODB_URI)
    db = mongo_client[settings.DATABASE_NAME]
    yield db
    mongo_client.close()


@pytest.fixture
def setup_two_applicants(test_db):
    """
    Creates two distinct applicants in smartenroll_test and returns their IDs and auth headers.
    """
    db = test_db
    # Cleanup previous test users
    db["users"].delete_many({"email": {"$in": ["applicant_a@example.com", "applicant_b@example.com"]}})
    db["applications"].delete_many({"applicantId": {"$in": ["APL-TESTAAA1", "APL-TESTBBB2"]}})
    db["documents"].delete_many({"applicantId": {"$in": ["APL-TESTAAA1", "APL-TESTBBB2"]}})

    # Applicant A
    user_a = {
        "email": "applicant_a@example.com",
        "hashed_password": get_password_hash("ValidPass123!@#"),
        "full_name": "Applicant Alice",
        "mobile": "9876543210",
        "dob": "2000-01-01",
        "role": "applicant",
        "applicant_id": "APL-TESTAAA1",
        "tokenVersion": 1,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
    }
    res_a = db["users"].insert_one(user_a)
    user_a_id = str(res_a.inserted_id)
    token_a = create_access_token(user_a_id, role="applicant", token_version=1)

    # Applicant B
    user_b = {
        "email": "applicant_b@example.com",
        "hashed_password": get_password_hash("ValidPass123!@#"),
        "full_name": "Applicant Bob",
        "mobile": "9876543211",
        "dob": "2000-02-02",
        "role": "applicant",
        "applicant_id": "APL-TESTBBB2",
        "tokenVersion": 1,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
    }
    res_b = db["users"].insert_one(user_b)
    user_b_id = str(res_b.inserted_id)
    token_b = create_access_token(user_b_id, role="applicant", token_version=1)

    # Create Application for B
    app_b_id = "SE2026B999"
    db["applications"].insert_one({
        "applicationId": app_b_id,
        "applicantId": "APL-TESTBBB2",
        "userId": user_b_id,
        "programmeId": "mca",
        "fullName": "Applicant Bob",
        "email": "applicant_b@example.com",
        "mobile": "9876543211",
        "status": "DRAFT",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    })

    # Create Document for B
    doc_b_id = f"doc_{uuid.uuid4().hex[:12]}"
    db["documents"].insert_one({
        "documentId": doc_b_id,
        "applicationId": app_b_id,
        "userId": user_b_id,
        "applicantId": "APL-TESTBBB2",
        "documentType": "10TH_MARKSHEET",
        "status": "UPLOADED",
        "storedFilename": f"{doc_b_id}.pdf",
        "originalFileName": "tenth.pdf",
        "fileSize": 1024,
        "mimeType": "application/pdf",
        "uploadedAt": datetime.now(timezone.utc).isoformat(),
    })

    yield {
        "user_a_id": user_a_id,
        "token_a": token_a,
        "headers_a": {"Authorization": f"Bearer {token_a}"},
        "user_b_id": user_b_id,
        "token_b": token_b,
        "headers_b": {"Authorization": f"Bearer {token_b}"},
        "app_b_id": app_b_id,
        "doc_b_id": doc_b_id,
    }

    # Teardown
    db["users"].delete_many({"_id": {"$in": [res_a.inserted_id, res_b.inserted_id]}})
    db["applications"].delete_many({"applicationId": app_b_id})
    db["documents"].delete_many({"documentId": doc_b_id})


def test_unauthenticated_requests_return_401():
    """
    Verify every protected API route rejects unauthenticated calls with HTTP 401.
    """
    protected_routes = [
        ("GET", "/api/v1/auth/me"),
        ("GET", "/api/v1/applications/me"),
        ("GET", "/api/v1/applications"),
        ("POST", "/api/v1/applications"),
        ("GET", "/api/v1/applications/SE20260001"),
        ("PUT", "/api/v1/applications/SE20260001"),
        ("POST", "/api/v1/applications/SE20260001/submit"),
        ("GET", "/api/v1/documents"),
        ("POST", "/api/v1/documents/upload"),
        ("DELETE", "/api/v1/documents/doc-dummy-123"),
        ("POST", "/api/v1/documents/doc-dummy-123/process"),
        ("POST", "/api/v1/documents/doc-dummy-123/verify"),
        ("POST", "/api/v1/documents/doc-dummy-123/authoritative-verify"),
        ("GET", "/api/v1/agents/activity"),
        ("GET", "/api/v1/agents/activity/SE20260001"),
        ("GET", "/api/v1/agents/system-status"),
        ("GET", "/api/v1/agents/runs"),
        ("POST", "/api/v1/agents/orchestrate/SE20260001"),
    ]

    for method, path in protected_routes:
        if method == "GET":
            res = client.get(path)
        elif method == "POST":
            res = client.post(path, json={})
        elif method == "PUT":
            res = client.put(path, json={})
        elif method == "DELETE":
            res = client.delete(path)
        else:
            raise ValueError(f"Unsupported method {method}")

        assert res.status_code == 401, f"Expected 401 for unauthenticated {method} {path}, got {res.status_code}"


def test_cross_applicant_isolation_enforced(setup_two_applicants):
    """
    Verify strict horizontal access control:
    Applicant A cannot read, update, submit, delete, process, verify, view activity,
    or orchestrate resources belonging to Applicant B.
    """
    ctx = setup_two_applicants
    headers_a = ctx["headers_a"]
    app_b_id = ctx["app_b_id"]
    doc_b_id = ctx["doc_b_id"]

    # 1. Applicant A cannot read Applicant B's application
    res = client.get(f"/api/v1/applications/{app_b_id}", headers=headers_a)
    assert res.status_code == 403

    # 2. Applicant A cannot update Applicant B's application
    res = client.put(f"/api/v1/applications/{app_b_id}", json={"address": "Hacked Address"}, headers=headers_a)
    assert res.status_code == 403

    # 3. Applicant A cannot submit Applicant B's application
    res = client.post(f"/api/v1/applications/{app_b_id}/submit", headers=headers_a)
    assert res.status_code == 403

    # 4. Applicant A cannot delete Applicant B's document
    res = client.delete(f"/api/v1/documents/{doc_b_id}", headers=headers_a)
    assert res.status_code == 403

    # 5. Applicant A cannot trigger document processing on Applicant B's document
    res = client.post(f"/api/v1/documents/{doc_b_id}/process", headers=headers_a)
    assert res.status_code == 403

    # 6. Applicant A cannot trigger document verification on Applicant B's document
    res = client.post(f"/api/v1/documents/{doc_b_id}/verify", headers=headers_a)
    assert res.status_code == 403

    # 7. Applicant A cannot trigger authoritative verify on Applicant B's document
    res = client.post(f"/api/v1/documents/{doc_b_id}/authoritative-verify", headers=headers_a)
    assert res.status_code == 403

    # 8. Applicant A cannot read Applicant B's agent activity
    res = client.get(f"/api/v1/agents/activity/{app_b_id}", headers=headers_a)
    assert res.status_code == 403

    # 9. Applicant A cannot trigger orchestration on Applicant B's application
    res = client.post(f"/api/v1/agents/orchestrate/{app_b_id}", headers=headers_a)
    assert res.status_code == 403


def test_application_mutation_forbidden_after_submission(setup_two_applicants, test_db):
    """
    Verify application cannot be updated or resubmitted once it has transitioned to SUBMITTED.
    """
    ctx = setup_two_applicants
    headers_b = ctx["headers_b"]
    app_b_id = ctx["app_b_id"]

    # Transition B's application to SUBMITTED
    test_db["applications"].update_one(
        {"applicationId": app_b_id},
        {"$set": {"status": "SUBMITTED", "submittedAt": datetime.now(timezone.utc).isoformat()}},
    )

    # 1. Update attempt on SUBMITTED application must fail with 400
    res = client.put(f"/api/v1/applications/{app_b_id}", json={"address": "New Address"}, headers=headers_b)
    assert res.status_code == 400
    assert "Cannot edit an application that has already been submitted" in res.json().get("detail", "")

    # 2. Resubmission attempt on SUBMITTED application must fail with 409 Conflict
    res = client.post(f"/api/v1/applications/{app_b_id}/submit", headers=headers_b)
    assert res.status_code == 409
    assert "Application is already submitted" in res.json().get("detail", "")


def test_upload_scanner_configuration_safety():
    """
    Verify UPLOAD_SCANNER configuration safety:
    - noop is allowed only in development and test.
    - staging and production require a real scanner (e.g. clamav) and refuse to start on missing or unrecognized settings.
    """
    from app.core.config import Settings
    from app.services.scanner import get_upload_scanner, validate_upload_scanner

    strong_secret = "a-very-strong-production-secret-key-at-least-32-chars!"

    # 1. Development allows noop
    s_dev = Settings(ENV="development", SECRET_KEY="any-secret", UPLOAD_SCANNER="noop")
    assert s_dev.UPLOAD_SCANNER == "noop"

    # 2. Test environment allows noop
    s_test = Settings(ENV="test", SECRET_KEY=strong_secret, UPLOAD_SCANNER="noop")
    assert s_test.UPLOAD_SCANNER == "noop"

    # 3. Staging forbids noop
    with pytest.raises(ValueError, match="UPLOAD_SCANNER 'noop' is strictly forbidden"):
        Settings(ENV="staging", SECRET_KEY=strong_secret, UPLOAD_SCANNER="noop")

    # 4. Production forbids noop
    with pytest.raises(ValueError, match="UPLOAD_SCANNER 'noop' is strictly forbidden"):
        Settings(ENV="production", SECRET_KEY=strong_secret, UPLOAD_SCANNER="noop")

    # 5. Production allows clamav
    s_prod_clamav = Settings(ENV="production", SECRET_KEY=strong_secret, UPLOAD_SCANNER="clamav")
    assert s_prod_clamav.UPLOAD_SCANNER == "clamav"

    # 6. Production forbids missing/empty scanner
    with pytest.raises(ValueError, match="UPLOAD_SCANNER cannot be missing or empty"):
        Settings(ENV="production", SECRET_KEY=strong_secret, UPLOAD_SCANNER="")

    # 7. Any environment forbids unrecognized scanner
    with pytest.raises(ValueError, match="Unrecognized UPLOAD_SCANNER 'unknown_scanner'"):
        Settings(ENV="development", SECRET_KEY="any-secret", UPLOAD_SCANNER="unknown_scanner")

    with pytest.raises(ValueError, match="Unrecognized UPLOAD_SCANNER 'bogus_engine'"):
        Settings(ENV="production", SECRET_KEY=strong_secret, UPLOAD_SCANNER="bogus_engine")


def test_clamav_readiness_checks(monkeypatch):
    """
    Verify production scanner readiness:
    - missing pyclamd fails startup
    - daemon unreachable / ping failure fails startup
    - daemon ready succeeds
    - no-op remains permitted in development and test without attempting daemon connection
    """
    from unittest.mock import MagicMock, patch
    from app.core.config import settings
    from app.services.scanner import validate_upload_scanner

    # 1. Missing pyclamd in production raises RuntimeError
    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(settings, "UPLOAD_SCANNER", "clamav")
    with patch.dict("sys.modules", {"pyclamd": None}):
        with pytest.raises(RuntimeError, match="'pyclamd' package is not installed"):
            validate_upload_scanner()

    # 2. Daemon unreachable / ping returns False in staging raises RuntimeError
    monkeypatch.setattr(settings, "ENV", "staging")
    monkeypatch.setattr(settings, "UPLOAD_SCANNER", "clamav")
    mock_socket_fail = MagicMock()
    mock_socket_fail.ping.return_value = False
    with patch("pyclamd.ClamdNetworkSocket", return_value=mock_socket_fail):
        with pytest.raises(RuntimeError, match="failed ping check"):
            validate_upload_scanner()

    # 3. Daemon connection error in production raises RuntimeError
    monkeypatch.setattr(settings, "ENV", "production")
    with patch("pyclamd.ClamdNetworkSocket", side_effect=ConnectionRefusedError("Connection refused")):
        with pytest.raises(RuntimeError, match="ClamAV daemon unreachable"):
            validate_upload_scanner()

    # 4. Daemon ready in production passes startup check
    mock_socket_ok = MagicMock()
    mock_socket_ok.ping.return_value = True
    with patch("pyclamd.ClamdNetworkSocket", return_value=mock_socket_ok):
        # Must not raise
        validate_upload_scanner()

    # 5. No-op remains permitted in development and test without attempting daemon ping
    monkeypatch.setattr(settings, "ENV", "development")
    monkeypatch.setattr(settings, "UPLOAD_SCANNER", "noop")
    validate_upload_scanner()

    monkeypatch.setattr(settings, "ENV", "test")
    monkeypatch.setattr(settings, "UPLOAD_SCANNER", "noop")
    validate_upload_scanner()
