"""
Unit and Integration Tests for API Hardening, Rate Limiting, and Security (Phases 4: H4, H6, M1, M10)
"""

import logging
from unittest.mock import patch
from bson import ObjectId
from fastapi.testclient import TestClient
import jwt
import pytest

from pydantic import ValidationError

from app.core.config import Settings, settings
from app.core.concurrency import acquire_ocr_worker
from app.core.logging_config import SensitiveDataRedactionFilter
from app.core.rate_limit import limiter, SlidingWindowRateLimiter, get_client_ip
from app.core.security import (
    create_access_token,
    get_password_hash,
    validate_password_strength,
)
from app.main import app


@pytest.fixture
def clean_db():
    from app.core.database import get_db
    db = get_db()
    db["users"].delete_many({})
    db["applications"].delete_many({})
    db["documents"].delete_many({})
    db["agent_activity"].delete_many({})
    yield db


# =====================================================================
# 1. Rate Limiting Tests (Finding H4)
# =====================================================================

def test_rate_limit_login(clean_db):
    """POST /auth/login throttles after 5 attempts per IP+email per minute with 429 and Retry-After."""
    limiter.reset()
    with TestClient(app) as client:
        # 5 attempts allowed
        for i in range(5):
            res = client.post(
                "/api/v1/auth/login",
                json={"email": "ratelimit_login@example.com", "password": "WrongPassword123!", "role": "user"},
            )
            assert res.status_code == 401

        # 6th attempt must be 429
        res = client.post(
            "/api/v1/auth/login",
            json={"email": "ratelimit_login@example.com", "password": "WrongPassword123!", "role": "user"},
        )
        assert res.status_code == 429
        assert "Retry-After" in res.headers
        assert "Too many login attempts" in res.json()["detail"]


def test_rate_limit_register(clean_db):
    """POST /auth/register throttles after 3 attempts per IP per minute."""
    limiter.reset()
    payload = {
        "email": "test_rl_reg@example.com",
        "password": "StrongPassword123!",
        "confirmPassword": "StrongPassword123!",
        "fullName": "Test RL",
        "mobile": "9876543210",
        "dob": "2000-01-01",
        "agree": True,
    }
    with TestClient(app) as client:
        for i in range(3):
            p = dict(payload)
            p["email"] = f"test_rl_reg_{i}@example.com"
            res = client.post("/api/v1/auth/register", json=p)
            assert res.status_code == 201

        # 4th attempt throttled
        p = dict(payload)
        p["email"] = "test_rl_reg_4@example.com"
        res = client.post("/api/v1/auth/register", json=p)
        assert res.status_code == 429
        assert "Retry-After" in res.headers

def test_rate_limit_orchestrate(clean_db):
    """POST /agents/orchestrate/{id} throttles after 5 runs per user per minute."""
    limiter.reset()
    user_id = ObjectId()
    app_id = "SE20269999"
    clean_db["users"].insert_one({
        "_id": user_id,
        "email": "orch_user@example.com",
        "role": "applicant",
        "full_name": "Orch Applicant",
        "applicant_id": "APL-9999",
        "tokenVersion": 1,
    })
    clean_db["applications"].insert_one({
        "applicationId": app_id,
        "userId": str(user_id),
        "applicantId": "APL-9999",
        "status": "DRAFT",
    })

    token = create_access_token(subject=str(user_id), role="applicant")

    with TestClient(app) as client:
        for _ in range(5):
            res = client.post(
                f"/api/v1/agents/orchestrate/{app_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert res.status_code == 200

        # 6th attempt throttled
        res = client.post(
            f"/api/v1/agents/orchestrate/{app_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 429
        assert "Retry-After" in res.headers

# =====================================================================
# 2. Concurrency Limiter Tests (Finding H4)
# =====================================================================

def test_ocr_worker_concurrency_saturation():
    """Simulating worker semaphore saturation raises 503 Service Unavailable."""
    from app.core.concurrency import _ocr_semaphore

    # Drain semaphore
    for _ in range(4):
        _ocr_semaphore.acquire()

    try:
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            with acquire_ocr_worker(timeout=0.01):
                pass
        assert exc_info.value.status_code == 503
        assert "Retry-After" in exc_info.value.headers
    finally:
        # Release acquired slots
        for _ in range(4):
            _ocr_semaphore.release()


# =====================================================================
# 3. Password Policy & Auth Hardening (Finding M1)
# =====================================================================

def test_password_policy_validation():
    """Verify password policy complexity checks."""
    from fastapi import HTTPException

    # Too short
    with pytest.raises(HTTPException) as exc:
        validate_password_strength("Short1!")
    assert "at least 10 characters" in exc.value.detail

    # Missing uppercase
    with pytest.raises(HTTPException) as exc:
        validate_password_strength("lowercase123!")
    assert "uppercase" in exc.value.detail

    # Missing lowercase
    with pytest.raises(HTTPException) as exc:
        validate_password_strength("UPPERCASE123!")
    assert "lowercase" in exc.value.detail

    # Missing digit
    with pytest.raises(HTTPException) as exc:
        validate_password_strength("NoDigitsHere!")
    assert "digit" in exc.value.detail

    # Missing special char
    with pytest.raises(HTTPException) as exc:
        validate_password_strength("NoSpecial123")
    assert "special character" in exc.value.detail

    # Common password
    with pytest.raises(HTTPException) as exc:
        validate_password_strength("password123")
    assert "common or easily guessable" in exc.value.detail

    # Valid password passes cleanly
    validate_password_strength("SuperSecurePass123!")


def test_token_version_revocation(clean_db):
    """Incrementing tokenVersion on user invalidates existing access tokens."""
    user_id = ObjectId()
    clean_db["users"].insert_one({
        "_id": user_id,
        "email": "revocation_test@example.com",
        "role": "applicant",
        "full_name": "Revocation User",
        "applicant_id": "APL-7777",
        "tokenVersion": 1,
    })

    # Issue token with version 1
    token_v1 = create_access_token(subject=str(user_id), role="applicant", token_version=1)

    with TestClient(app) as client:
        # Token v1 is valid
        res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_v1}"})
        assert res.status_code == 200

        # Increment tokenVersion to 2 (simulating logout/session revocation)
        clean_db["users"].update_one({"_id": user_id}, {"$set": {"tokenVersion": 2}})

        # Token v1 must now be rejected with 401
        res2 = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_v1}"})
        assert res2.status_code == 401
        assert "revoked" in res2.json()["detail"].lower()


def test_jwt_claims_aud_and_iss():
    """Verify generated tokens contain aud and iss claims, and forged claims are rejected."""
    token = create_access_token(subject="user_123", role="applicant", token_version=1)
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"], audience="smart-enroll-api")
    assert payload["iss"] == "smart-enroll"
    assert payload["aud"] == "smart-enroll-api"
    assert payload["tokenVersion"] == 1

    # Forged audience token must be rejected by get_current_user
    bad_aud_token = jwt.encode(
        {"sub": str(ObjectId()), "role": "applicant", "aud": "wrong-api", "iss": "smart-enroll", "exp": 9999999999},
        settings.SECRET_KEY,
        algorithm="HS256",
    )
    with TestClient(app) as client:
        res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {bad_aud_token}"})
        assert res.status_code == 401


# =====================================================================
# 4. Endpoints & Logging Hardening (Finding H6, M10)
# =====================================================================

def test_db_health_sanitized():
    """GET /api/v1/db-health returns sanitized status ok."""
    with TestClient(app) as client:
        res = client.get("/api/v1/db-health")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}


def test_request_id_middleware():
    """Verify X-Request-ID is attached and echoed back in response headers."""
    with TestClient(app) as client:
        # Generated request ID
        res = client.get("/health")
        assert "X-Request-ID" in res.headers
        assert len(res.headers["X-Request-ID"]) > 10

        # Echoed custom request ID
        custom_id = "req-custom-trace-12345"
        res2 = client.get("/health", headers={"X-Request-ID": custom_id})
        assert res2.headers["X-Request-ID"] == custom_id


def test_log_redaction_filter():
    """Verify SensitiveDataRedactionFilter strips passwords and tokens."""
    flt = SensitiveDataRedactionFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg='User authenticated with "password": "SuperSecretPassword123!" and Bearer eyJhbGciOi...',
        args=(),
        exc_info=None,
    )
    flt.filter(record)
    assert "SuperSecretPassword123!" not in record.msg
    assert '"password": "[REDACTED]"' in record.msg
    assert "Bearer [REDACTED]" in record.msg


def test_pagination_on_admin_applications(clean_db):
    """Verify skip and limit pagination on GET /api/v1/applications."""
    admin_id = ObjectId()
    clean_db["users"].insert_one({
        "_id": admin_id,
        "email": "admin_pagination@example.com",
        "role": "admin",
        "tokenVersion": 1,
    })
    token = create_access_token(subject=str(admin_id), role="admin")

    # Insert 5 test applications
    for i in range(5):
        clean_db["applications"].insert_one({
            "applicationId": f"SE2026{i:04d}",
            "userId": str(ObjectId()),
            "status": "DRAFT",
            "programmeId": "mca",
            "createdAt": f"2026-01-0{i+1}T00:00:00Z",
        })

    with TestClient(app) as client:
        res = client.get(
            "/api/v1/applications?skip=0&limit=2",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 2

        res2 = client.get(
            "/api/v1/applications?skip=2&limit=2",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res2.status_code == 200
        data2 = res2.json()
        assert len(data2) == 2
        assert data[0]["applicationId"] != data2[0]["applicationId"]


# =====================================================================
# 6. Advanced Rate Limiting, Proxy, and Storage Tests (Follow-up Task 3)
# =====================================================================

def test_rate_limit_independent_ip_and_account(clean_db):
    """Verify independent IP and account throttling on POST /auth/login."""
    limiter.reset()
    with TestClient(app) as client:
        # 1. Account throttling across multiple forwarded IPs
        for i in range(5):
            res = client.post(
                "/api/v1/auth/login",
                json={"email": "target_account@example.com", "password": "WrongPassword123!", "role": "user"},
                headers={"X-Forwarded-For": f"198.51.100.{i+1}"},
            )
            assert res.status_code == 401

        # 6th attempt from a fresh IP still throttled due to account limit
        res = client.post(
            "/api/v1/auth/login",
            json={"email": "target_account@example.com", "password": "WrongPassword123!", "role": "user"},
            headers={"X-Forwarded-For": "198.51.100.99"},
        )
        assert res.status_code == 429
        assert "login attempts for this account" in res.json()["detail"]

    # 2. IP throttling across multiple accounts from single IP
    limiter.reset()
    with TestClient(app) as client:
        for i in range(20):
            res = client.post(
                "/api/v1/auth/login",
                json={"email": f"diff_account_{i}@example.com", "password": "WrongPassword123!", "role": "user"},
            )
            assert res.status_code == 401

        # 21st attempt from same IP throttled even for a brand-new account
        res = client.post(
            "/api/v1/auth/login",
            json={"email": "diff_account_fresh@example.com", "password": "WrongPassword123!", "role": "user"},
        )
        assert res.status_code == 429
        assert "login attempts from this IP" in res.json()["detail"]


def test_trusted_proxy_client_ip_resolution():
    """Verify get_client_ip respects TRUSTED_PROXIES and rejects spoofed headers from untrusted clients."""
    from fastapi import Request

    class DummyClient:
        def __init__(self, host):
            self.host = host

    # Trusted proxy scenario: peer is 127.0.0.1
    scope_trusted = {
        "type": "http",
        "client": ("127.0.0.1", 12345),
        "headers": [(b"x-forwarded-for", b"203.0.113.50, 10.0.0.1")],
    }
    req_trusted = Request(scope_trusted)
    assert get_client_ip(req_trusted) == "203.0.113.50"

    # Untrusted peer scenario: peer is 198.51.100.5 (not in TRUSTED_PROXIES)
    scope_untrusted = {
        "type": "http",
        "client": ("198.51.100.5", 12345),
        "headers": [(b"x-forwarded-for", b"1.1.1.1")],
    }
    req_untrusted = Request(scope_untrusted)
    # Must ignore spoofed header and return peer IP
    assert get_client_ip(req_untrusted) == "198.51.100.5"


def test_rate_limit_sliding_window_bounded_and_pruning():
    """Verify SlidingWindowRateLimiter limits maximum keys and prunes expired keys."""
    bounded_limiter = SlidingWindowRateLimiter(max_keys=5)

    # Insert 5 keys
    for i in range(5):
        allowed, _ = bounded_limiter.check(f"key_{i}", max_requests=10, window_seconds=60)
        assert allowed is True

    assert len(bounded_limiter._requests) == 5

    # Insert a 6th key; capacity enforcement should prevent unbounded growth
    allowed, _ = bounded_limiter.check("key_5", max_requests=10, window_seconds=60)
    assert allowed is True
    assert len(bounded_limiter._requests) <= 5

    # Test pruning of stale keys
    import time
    bounded_limiter._requests["stale_key"] = [time.monotonic() - 400]
    pruned = bounded_limiter.prune(max_idle_seconds=300)
    assert pruned >= 1
    assert "stale_key" not in bounded_limiter._requests


def test_rate_limit_authoritative_verify(clean_db):
    """Verify POST /documents/{id}/authoritative-verify is throttled after 10 requests/min."""
    limiter.reset()
    user_id = ObjectId()
    doc_id = str(ObjectId())
    clean_db["users"].insert_one({
        "_id": user_id,
        "email": "doc_auth_user@example.com",
        "role": "applicant",
        "tokenVersion": 1,
    })
    clean_db["documents"].insert_one({
        "_id": ObjectId(doc_id),
        "applicantId": str(user_id),
        "documentType": "aadhaar",
        "status": "UPLOADED",
    })
    token = create_access_token(subject=str(user_id), role="applicant")

    with TestClient(app) as client:
        with patch("app.api.documents.authoritative_verify_document") as mock_auth_verify:
            mock_auth_verify.return_value = {
                "documentId": doc_id,
                "verified": True,
                "status": "VALIDATED",
                "source": "SIMULATED_UIDAI",
                "authority": "Unique Identification Authority of India",
                "timestamp": "2026-01-01T00:00:00Z",
                "disclaimer": "Simulated",
            }
            # 10 allowed requests
            for _ in range(10):
                res = client.post(
                    f"/api/v1/documents/{doc_id}/authoritative-verify",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert res.status_code == 200

            # 11th request must be throttled
            res = client.post(
                f"/api/v1/documents/{doc_id}/authoritative-verify",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert res.status_code == 429
            assert "Retry-After" in res.headers


def test_rate_limit_application_create_and_update(clean_db):
    """Verify application creation and update endpoints are rate-limited."""
    limiter.reset()
    user_id = ObjectId()
    clean_db["users"].insert_one({
        "_id": user_id,
        "email": "app_rate_user@example.com",
        "role": "applicant",
        "tokenVersion": 1,
    })
    token = create_access_token(subject=str(user_id), role="applicant")

    with TestClient(app) as client:
        # Application creation limit is 10/min
        for i in range(10):
            limiter.check(f"app_create:{user_id}", max_requests=10, window_seconds=60)

        # 11th call triggers 429
        res = client.post(
            "/api/v1/applications",
            json={"programmeId": "mca"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 429
        assert "Retry-After" in res.headers
        # Application update limit is 30/min
        for i in range(30):
            limiter.check(f"app_update:{user_id}", max_requests=30, window_seconds=60)

        res = client.put(
            "/api/v1/applications/SE202600001",
            json={"personalDetails": {"nationality": "Indian"}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 429
        assert "Retry-After" in res.headers


# =====================================================================
# 7. Fail-Safe Production Configuration Tests (Follow-up Task 4)
# =====================================================================

def test_config_env_validation():
    """Verify ENV only accepts development, staging, production, or test."""
    for valid_env in ["development", "staging", "production", "test", "PRODUCTION", "Development "]:
        cfg = Settings(ENV=valid_env, SECRET_KEY="a" * 32, ENABLE_DEV_SEED=False)
        assert cfg.ENV in {"development", "staging", "production", "test"}

    for invalid_env in ["local", "prod", "sandbox", "docker", ""]:
        with pytest.raises(ValidationError) as exc:
            Settings(ENV=invalid_env, SECRET_KEY="a" * 32)
        assert "Invalid ENV" in str(exc.value)


def test_config_secret_key_validation():
    """Verify strong SECRET_KEY is enforced outside development."""
    dev_cfg = Settings(ENV="development", SECRET_KEY="short-key")
    assert dev_cfg.SECRET_KEY == "short-key"

    with pytest.raises(ValidationError) as exc:
        Settings(ENV="production", SECRET_KEY="too-short")
    assert "at least 32 characters long" in str(exc.value)

    with pytest.raises(ValidationError) as exc:
        Settings(ENV="staging", SECRET_KEY="your-secret-key-change-in-production")
    assert "Insecure placeholder SECRET_KEY" in str(exc.value)

    prod_cfg = Settings(ENV="production", SECRET_KEY="super-secret-key-that-is-at-least-32-chars-long!")
    assert len(prod_cfg.SECRET_KEY) >= 32


def test_config_default_deny_dev_seed(clean_db):
    """Verify ENABLE_DEV_SEED is strictly forbidden outside development and disabled by default."""
    cfg = Settings(SECRET_KEY="a" * 32)
    assert cfg.ENABLE_DEV_SEED is False

    with pytest.raises(ValidationError) as exc:
        Settings(ENV="production", SECRET_KEY="a" * 32, ENABLE_DEV_SEED=True)
    assert "ENABLE_DEV_SEED is strictly forbidden" in str(exc.value)

    admin_id = ObjectId()
    clean_db["users"].insert_one({
        "_id": admin_id,
        "email": "seed_admin@example.com",
        "role": "admin",
        "tokenVersion": 1,
    })
    token = create_access_token(subject=str(admin_id), role="admin")

    with TestClient(app) as client:
        res = client.post(
            "/api/v1/applications/seed",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 404
        assert "Dev seed endpoint is disabled" in res.json()["detail"]

