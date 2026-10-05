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

from app.api.deps import RequireRole
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


# Register test routes if not already registered
if not any(getattr(route, "path", None) == "/applicant-test" for route in app.routes):
    app.include_router(auth_test_router)


@pytest.fixture(autouse=True)
def clean_users_collection():
    """Ensure clean users collection before each test."""
    with TestClient(app):
        db = get_db()
        db["users"].delete_many({})
        db["users"].create_index("email", unique=True)
        yield
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
        assert len(data["applicantId"]) == 10  # APL- + 6 hex chars
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

