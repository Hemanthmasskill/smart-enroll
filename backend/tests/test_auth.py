"""
Tests for Increment 10 Authentication & Authorization Layer.
Covers registration, login, role mapping, JWT lifecycle, RBAC enforcement,
security constraints, and backward compatibility.
"""

from datetime import datetime, timedelta, timezone
from bson import ObjectId
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
import jwt
import pytest

from app.api.deps import RequireRole, get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_password_hash
from app.main import app

# Define test-only routes for authorization testing
auth_test_router = APIRouter()


@auth_test_router.get("/applicant-test")
def applicant_test_route(user: dict = Depends(RequireRole(["applicant"]))):
    return {"message": "Applicant access granted", "role": user["role"]}


@auth_test_router.get("/admin-test")
def admin_test_route(user: dict = Depends(RequireRole(["admin"]))):
    return {"message": "Admin access granted", "role": user["role"]}


@auth_test_router.get("/me-test")
def me_test_route(user: dict = Depends(get_current_user)):
    user_copy = user.copy()
    user_copy["_id"] = str(user_copy["_id"])
    return user_copy


# Register test routes if not already registered
if not any(getattr(route, "path", None) == "/applicant-test" for route in app.routes):
    app.include_router(auth_test_router)


@pytest.fixture(autouse=True)
def clean_users_collection():
    """Ensure clean users collection before each test in test database."""
    assert settings.DATABASE_NAME == "smartenroll_test", (
        f"Safety assertion failed: Expected 'smartenroll_test', got '{settings.DATABASE_NAME}'"
    )
    with TestClient(app):
        db = get_db()
        assert db.name == "smartenroll_test"
        db["users"].delete_many({})
        db["users"].create_index("email", unique=True)
        db["users"].create_index("applicant_id", unique=True, partialFilterExpression={"applicant_id": {"$type": "string"}})
        yield
        assert db.name == "smartenroll_test"
        db["users"].delete_many({})


@pytest.fixture
def seeded_admin():
    """Seed an admin user directly into the database."""
    db = get_db()
    admin_doc = {
        "email": "admin@example.com",
        "hashed_password": get_password_hash("AdminPass123!"),
        "full_name": "Admin User",
        "role": "admin",
        "applicant_id": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    result = db["users"].insert_one(admin_doc)
    admin_doc["_id"] = result.inserted_id
    return admin_doc


APPLICANT_PAYLOAD = {
    "fullName": "Hemanth M.P.",
    "email": "hemanth@example.com",
    "mobile": "9876543210",
    "dob": "2001-06-14",
    "password": "Password123!",
    "confirmPassword": "Password123!",
    "agree": True,
}


# 1. Successful applicant registration
def test_successful_applicant_registration():
    with TestClient(app) as client:
        res = client.post("/api/v1/auth/register", json=APPLICANT_PAYLOAD)
        assert res.status_code == 201
        data = res.json()

        assert data["role"] == "user"
        assert data["name"] == "Hemanth M.P."
        assert data["email"] == "hemanth@example.com"
        assert data["applicantId"].startswith("APL-")
        # Task 2.2: secrets.token_hex(6) generates 12 hex chars -> 'APL-' + 12 chars = 16 chars
        assert len(data["applicantId"]) == 16
        assert isinstance(data["token"], str)
        assert len(data["token"]) > 20

        # Verify DB document
        db = get_db()
        user_in_db = db["users"].find_one({"email": "hemanth@example.com"})
        assert user_in_db is not None
        assert user_in_db["role"] == "applicant"
        assert user_in_db["applicant_id"] == data["applicantId"]


# 2. Attempted role escalation during public registration
def test_registration_prevents_role_escalation():
    with TestClient(app) as client:
        payload = APPLICANT_PAYLOAD.copy()
        payload["role"] = "admin"  # Malicious attempt to register as admin

        res = client.post("/api/v1/auth/register", json=payload)
        assert res.status_code == 201
        data = res.json()

        # Frontend role must still be "user"
        assert data["role"] == "user"

        # Database record must strictly be "applicant"
        db = get_db()
        user_in_db = db["users"].find_one({"email": "hemanth@example.com"})
        assert user_in_db is not None
        assert user_in_db["role"] == "applicant"


# 3. Duplicate email returns 409 Conflict
def test_duplicate_email_returns_409():
    with TestClient(app) as client:
        res1 = client.post("/api/v1/auth/register", json=APPLICANT_PAYLOAD)
        assert res1.status_code == 201

        # Attempt to register with the same email
        res2 = client.post("/api/v1/auth/register", json=APPLICANT_PAYLOAD)
        assert res2.status_code == 409
        assert "already registered" in res2.json()["detail"].lower()


# 4. Successful applicant login
def test_successful_applicant_login():
    with TestClient(app) as client:
        # First register
        reg_res = client.post("/api/v1/auth/register", json=APPLICANT_PAYLOAD)
        assert reg_res.status_code == 201
        registered_applicant_id = reg_res.json()["applicantId"]

        # Log in
        login_res = client.post(
            "/api/v1/auth/login",
            json={
                "email": "hemanth@example.com",
                "password": "Password123!",
                "role": "user",
            },
        )
        assert login_res.status_code == 200
        data = login_res.json()

        assert data["role"] == "user"
        assert data["name"] == "Hemanth M.P."
        assert data["email"] == "hemanth@example.com"
        assert data["applicantId"] == registered_applicant_id
        assert isinstance(data["token"], str)


# 5. Successful admin login using seeded admin
def test_successful_admin_login(seeded_admin):
    with TestClient(app) as client:
        res = client.post(
            "/api/v1/auth/login",
            json={
                "email": "admin@example.com",
                "password": "AdminPass123!",
                "role": "admin",
            },
        )
        assert res.status_code == 200
        data = res.json()

        assert data["role"] == "admin"
        assert data["name"] == "Admin User"
        assert data["email"] == "admin@example.com"
        assert data["applicantId"] is None
        assert isinstance(data["token"], str)


# 6. Incorrect password returns 401
def test_incorrect_password_returns_401(seeded_admin):
    with TestClient(app) as client:
        res = client.post(
            "/api/v1/auth/login",
            json={
                "email": "admin@example.com",
                "password": "WrongPassword!",
                "role": "admin",
            },
        )
        assert res.status_code == 401


# 7. Nonexistent user returns 401
def test_nonexistent_user_returns_401():
    with TestClient(app) as client:
        res = client.post(
            "/api/v1/auth/login",
            json={
                "email": "ghost@example.com",
                "password": "Password123!",
                "role": "user",
            },
        )
        assert res.status_code == 401


# 8. Missing token returns 401
def test_missing_token_returns_401():
    with TestClient(app) as client:
        res = client.get("/applicant-test")
        assert res.status_code == 401


# 9. Invalid token returns 401
def test_invalid_token_returns_401():
    with TestClient(app) as client:
        res = client.get(
            "/applicant-test",
            headers={"Authorization": "Bearer not.a.valid.jwt.token"},
        )
        assert res.status_code == 401

        # Token signed with wrong secret key (>= 32 bytes)
        forged_token = jwt.encode(
            {"sub": str(ObjectId()), "role": "applicant", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
            "wrong-secret-key-at-least-32-bytes-long!",
            algorithm="HS256",
        )
        res_forged = client.get(
            "/applicant-test",
            headers={"Authorization": f"Bearer {forged_token}"},
        )
        assert res_forged.status_code == 401


# 10. Expired token returns 401
def test_expired_token_returns_401():
    with TestClient(app) as client:
        expired_token = jwt.encode(
            {
                "sub": str(ObjectId()),
                "role": "applicant",
                "exp": datetime.now(timezone.utc) - timedelta(minutes=10),
            },
            settings.SECRET_KEY,
            algorithm="HS256",
        )
        res = client.get(
            "/applicant-test",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert res.status_code == 401


# 11. Missing required JWT claim returns 401
def test_missing_jwt_claim_returns_401():
    with TestClient(app) as client:
        # Missing role
        no_role = jwt.encode(
            {"sub": str(ObjectId()), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
            settings.SECRET_KEY,
            algorithm="HS256",
        )
        res1 = client.get("/applicant-test", headers={"Authorization": f"Bearer {no_role}"})
        assert res1.status_code == 401

        # Missing sub
        no_sub = jwt.encode(
            {"role": "applicant", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
            settings.SECRET_KEY,
            algorithm="HS256",
        )
        res2 = client.get("/applicant-test", headers={"Authorization": f"Bearer {no_sub}"})
        assert res2.status_code == 401

        # Missing exp
        no_exp = jwt.encode(
            {"sub": str(ObjectId()), "role": "applicant"},
            settings.SECRET_KEY,
            algorithm="HS256",
        )
        res3 = client.get("/applicant-test", headers={"Authorization": f"Bearer {no_exp}"})
        assert res3.status_code == 401


# 12. Valid applicant token accesses /applicant-test (200)
def test_valid_applicant_accesses_applicant_route():
    with TestClient(app) as client:
        reg = client.post("/api/v1/auth/register", json=APPLICANT_PAYLOAD)
        token = reg.json()["token"]

        res = client.get("/applicant-test", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        assert res.json()["message"] == "Applicant access granted"


# 13. Applicant accessing /admin-test returns 403
def test_applicant_accessing_admin_route_returns_403():
    with TestClient(app) as client:
        reg = client.post("/api/v1/auth/register", json=APPLICANT_PAYLOAD)
        token = reg.json()["token"]

        res = client.get("/admin-test", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 403
        assert "not permitted" in res.json()["detail"].lower()


# 14. Valid admin accesses /admin-test (200)
def test_valid_admin_accesses_admin_route(seeded_admin):
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "AdminPass123!", "role": "admin"},
        )
        token = login.json()["token"]

        res = client.get("/admin-test", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        assert res.json()["message"] == "Admin access granted"


# 15. Ensure hashed_password never appears in auth responses
def test_hashed_password_never_exposed(seeded_admin):
    with TestClient(app) as client:
        # Register response
        reg_res = client.post("/api/v1/auth/register", json=APPLICANT_PAYLOAD)
        assert "hashed_password" not in reg_res.json()
        assert "password" not in reg_res.json()

        # Applicant login response
        app_login = client.post(
            "/api/v1/auth/login",
            json={"email": "hemanth@example.com", "password": "Password123!", "role": "user"},
        )
        assert "hashed_password" not in app_login.json()
        assert "password" not in app_login.json()

        # Admin login response
        adm_login = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "AdminPass123!", "role": "admin"},
        )
        assert "hashed_password" not in adm_login.json()
        assert "password" not in adm_login.json()

        # get_current_user response for authenticated user
        token = reg_res.json()["token"]
        me_res = client.get("/me-test", headers={"Authorization": f"Bearer {token}"})
        assert me_res.status_code == 200
        assert "hashed_password" not in me_res.json()
        assert "password" not in me_res.json()


# Focused test: get_current_user excludes hashed_password and retains required fields
def test_get_current_user_excludes_hashed_password():
    with TestClient(app) as client:
        reg_res = client.post("/api/v1/auth/register", json=APPLICANT_PAYLOAD)
        token = reg_res.json()["token"]

        me_res = client.get("/me-test", headers={"Authorization": f"Bearer {token}"})
        assert me_res.status_code == 200
        user_data = me_res.json()

        # Focused assertion: hashed_password must never be returned by get_current_user()
        assert "hashed_password" not in user_data
        assert "password" not in user_data

        # Required fields for authorization and downstream endpoints
        assert "_id" in user_data
        assert user_data["email"] == "hemanth@example.com"
        assert user_data["full_name"] == "Hemanth M.P."
        assert user_data["role"] == "applicant"
        assert user_data["applicant_id"].startswith("APL-")


# 16. Verify frontend-compatible response structure and role mapping
def test_frontend_compatible_response_structure_and_role_mapping(seeded_admin):
    with TestClient(app) as client:
        reg_res = client.post("/api/v1/auth/register", json=APPLICANT_PAYLOAD)
        expected_keys = {"role", "name", "email", "applicantId", "token"}
        assert set(reg_res.json().keys()) == expected_keys
        assert reg_res.json()["role"] == "user"

        adm_login = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "AdminPass123!", "role": "admin"},
        )
        assert set(adm_login.json().keys()) == expected_keys
        assert adm_login.json()["role"] == "admin"


# 17. Verify applicantId is returned for applicants and null for admins
def test_applicant_id_returned_for_applicant_and_null_for_admin(seeded_admin):
    with TestClient(app) as client:
        reg_res = client.post("/api/v1/auth/register", json=APPLICANT_PAYLOAD)
        assert reg_res.json()["applicantId"] is not None
        assert reg_res.json()["applicantId"].startswith("APL-")

        adm_login = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "AdminPass123!", "role": "admin"},
        )
        assert adm_login.json()["applicantId"] is None


# 18. Verify email normalization
def test_email_normalization():
    with TestClient(app) as client:
        messy_payload = APPLICANT_PAYLOAD.copy()
        messy_payload["email"] = "  HeMaNtH.NoRmAlIzEd@ExAmPlE.cOm  "

        reg_res = client.post("/api/v1/auth/register", json=messy_payload)
        assert reg_res.status_code == 201
        assert reg_res.json()["email"] == "hemanth.normalized@example.com"

        # Verify DB stored normalized lowercase
        db = get_db()
        user_in_db = db["users"].find_one({"email": "hemanth.normalized@example.com"})
        assert user_in_db is not None

        # Login with different casing and whitespace
        login_res = client.post(
            "/api/v1/auth/login",
            json={
                "email": "   HEMANTH.NORMALIZED@EXAMPLE.COM ",
                "password": "Password123!",
                "role": "user",
            },
        )
        assert login_res.status_code == 200
        assert login_res.json()["email"] == "hemanth.normalized@example.com"


# Additional check: Role mismatch on login fails with 401
def test_role_mismatch_login_fails(seeded_admin):
    with TestClient(app) as client:
        # Register user as applicant
        client.post("/api/v1/auth/register", json=APPLICANT_PAYLOAD)

        # Applicant trying to log in claiming role="admin"
        res1 = client.post(
            "/api/v1/auth/login",
            json={"email": "hemanth@example.com", "password": "Password123!", "role": "admin"},
        )
        assert res1.status_code == 401

        # Admin trying to log in claiming role="user"
        res2 = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "AdminPass123!", "role": "user"},
        )
        assert res2.status_code == 401


# 19. Controlled Admin Creation script test
def test_create_admin_script():
    from scripts.create_admin import create_admin

    # First creation succeeds
    success = create_admin("newadmin@example.com", "New Admin", "AdminPassword123!")
    assert success is True

    # Duplicate creation fails safely
    duplicate = create_admin("newadmin@example.com", "New Admin", "AdminPassword123!")
    assert duplicate is False

    # The created admin can log in through the public API
    with TestClient(app) as client:
        res = client.post(
            "/api/v1/auth/login",
            json={
                "email": "newadmin@example.com",
                "password": "AdminPassword123!",
                "role": "admin",
            },
        )
        assert res.status_code == 200
        assert res.json()["role"] == "admin"
        assert res.json()["name"] == "New Admin"
        assert res.json()["applicantId"] is None

def test_applicant_id_cryptographically_secure_and_unique():
    """
    Regression test for H2 (Task 2.2):
    Verify applicant ID format matches APL-[0-9A-F]{12} (12 hex characters),
    and unique index prevents collisions.
    """
    import re
    from scripts.migrate_applicant_ids import migrate_applicant_ids

    with TestClient(app) as client:
        res = client.post(
            "/api/v1/auth/register",
            json={
                "fullName": "Secure Applicant",
                "email": "secure.applicant@example.com",
                "mobile": "9876543210",
                "dob": "2000-01-01",
                "password": "Password123!",
            },
        )
        assert res.status_code == 201
        data = res.json()
        applicant_id = data["applicantId"]
        assert re.match(r"^APL-[0-9A-F]{12}$", applicant_id), f"Unexpected ID format: {applicant_id}"

        # Test migration script on clean database
        db = get_db()
        # Seed an applicant with legacy short ID
        db["users"].insert_one({
            "email": "legacy@example.com",
            "hashed_password": "hash",
            "full_name": "Legacy Applicant",
            "role": "applicant",
            "applicant_id": "APL-1234",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        # Run migration in dry-run mode
        dry_res = migrate_applicant_ids(apply_changes=False, db=db)
        assert dry_res["needs_migration"] == 1
        assert dry_res["migrated"] == 0

        # Run migration in apply mode
        apply_res = migrate_applicant_ids(apply_changes=True, db=db)
        assert apply_res["needs_migration"] == 1
        assert apply_res["migrated"] == 1

        # Verify the legacy user now has a compliant ID
        migrated_user = db["users"].find_one({"email": "legacy@example.com"})
        assert re.match(r"^APL-[0-9A-F]{12}$", migrated_user["applicant_id"])

        # Running again is idempotent
        repeat_res = migrate_applicant_ids(apply_changes=True, db=db)
        assert repeat_res["needs_migration"] == 0
        assert repeat_res["migrated"] == 0


# =====================================================================
# Strict JWT Claim Enforcement (Follow-up Task 5)
# =====================================================================

def test_jwt_claims_mandatory_iss_aud_tokenversion():
    """Verify get_current_user strictly rejects tokens missing iss, aud, or tokenVersion."""
    db = get_db()
    user_id = ObjectId()
    db["users"].insert_one({
        "_id": user_id,
        "email": "jwt_strict@example.com",
        "role": "applicant",
        "full_name": "JWT Strict User",
        "applicant_id": "APL-1234567890AB",
        "tokenVersion": 1,
    })

    base_payload = {
        "sub": str(user_id),
        "role": "applicant",
        "iss": "smart-enroll",
        "aud": "smart-enroll-api",
        "tokenVersion": 1,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }

    with TestClient(app) as client:
        # 1. Valid token passes
        valid_token = jwt.encode(base_payload, settings.SECRET_KEY, algorithm="HS256")
        res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {valid_token}"})
        assert res.status_code == 200

        # 2. Missing iss claim
        no_iss = dict(base_payload)
        del no_iss["iss"]
        tok = jwt.encode(no_iss, settings.SECRET_KEY, algorithm="HS256")
        res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
        assert res.status_code == 401

        # 3. Invalid iss claim
        bad_iss = dict(base_payload, iss="untrusted-issuer")
        tok = jwt.encode(bad_iss, settings.SECRET_KEY, algorithm="HS256")
        res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
        assert res.status_code == 401

        # 4. Missing aud claim
        no_aud = dict(base_payload)
        del no_aud["aud"]
        tok = jwt.encode(no_aud, settings.SECRET_KEY, algorithm="HS256")
        res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
        assert res.status_code == 401

        # 5. Invalid aud claim
        bad_aud = dict(base_payload, aud="wrong-audience")
        tok = jwt.encode(bad_aud, settings.SECRET_KEY, algorithm="HS256")
        res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
        assert res.status_code == 401

        # 6. Missing tokenVersion claim
        no_ver = dict(base_payload)
        del no_ver["tokenVersion"]
        tok = jwt.encode(no_ver, settings.SECRET_KEY, algorithm="HS256")
        res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
        assert res.status_code == 401
        assert "tokenVersion" in res.json()["detail"]

        # 7. Mismatched tokenVersion
        mismatched_ver = dict(base_payload, tokenVersion=99)
        tok = jwt.encode(mismatched_ver, settings.SECRET_KEY, algorithm="HS256")
        res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
        assert res.status_code == 401
        assert "revoked or invalidated" in res.json()["detail"]


# =====================================================================
# Field-Length and Format Validation Tests (Follow-up Task 6)
# =====================================================================

def test_user_create_field_validation():
    """Verify UserCreate rejects invalid field lengths and formats with 422."""
    valid_payload = {
        "fullName": "Valid Candidate",
        "email": "candidate@example.com",
        "mobile": "9876543210",
        "dob": "2000-01-15",
        "password": "StrongPassword123!",
    }

    with TestClient(app) as client:
        # 1. Blank full name
        bad_name = dict(valid_payload, fullName="   ")
        res = client.post("/api/v1/auth/register", json=bad_name)
        assert res.status_code == 422
        # 2. Name exceeds 100 characters
        too_long_name = dict(valid_payload, fullName="A" * 101)
        res = client.post("/api/v1/auth/register", json=too_long_name)
        assert res.status_code == 422
        # 3. Invalid mobile length/format
        bad_mobile = dict(valid_payload, mobile="12345")
        res = client.post("/api/v1/auth/register", json=bad_mobile)
        assert res.status_code == 422
        bad_mobile_alpha = dict(valid_payload, mobile="98765abcde")
        res = client.post("/api/v1/auth/register", json=bad_mobile_alpha)
        assert res.status_code == 422
        # 4. Invalid DOB format
        bad_dob_slash = dict(valid_payload, dob="2000/01/15")
        res = client.post("/api/v1/auth/register", json=bad_dob_slash)
        assert res.status_code == 422
        bad_dob_calendar = dict(valid_payload, dob="2000-02-31")
        res = client.post("/api/v1/auth/register", json=bad_dob_calendar)
        assert res.status_code == 422
        # 5. Password length boundaries in schema
        short_pwd = dict(valid_payload, password="Short1!")
        res = client.post("/api/v1/auth/register", json=short_pwd)
        assert res.status_code == 422
        long_pwd = dict(valid_payload, password="A" * 129)
        res = client.post("/api/v1/auth/register", json=long_pwd)
        assert res.status_code == 422

def test_user_login_field_validation():
    """Verify UserLogin rejects invalid roles and oversized passwords with 422."""
    with TestClient(app) as client:
        # 1. Invalid role
        res = client.post(
            "/api/v1/auth/login",
            json={"email": "login@example.com", "password": "Password123!", "role": "superuser"},
        )
        assert res.status_code == 422
        assert "Invalid role" in str(res.json())

        # 2. Oversized password (> 128 characters)
        res = client.post(
            "/api/v1/auth/login",
            json={"email": "login@example.com", "password": "A" * 130, "role": "user"},
        )
        assert res.status_code == 422
        # 3. Empty password
        res = client.post(
            "/api/v1/auth/login",
            json={"email": "login@example.com", "password": "", "role": "user"},
        )
        assert res.status_code == 422


# =====================================================================
# Docstring Placement Tests (Follow-up Task 9)
# =====================================================================

def test_docstring_placement_in_auth_and_security():
    """Verify function docstrings are properly accessible on __doc__ for OpenAPI reflection."""
    from app.api.auth import register, login
    from app.core.security import validate_password_strength

    assert register.__doc__ is not None
    assert "Public registration endpoint" in register.__doc__

    assert login.__doc__ is not None
    assert "User/Admin login endpoint" in login.__doc__

    assert validate_password_strength.__doc__ is not None
    assert "Enforce enterprise password complexity" in validate_password_strength.__doc__
