"""
Increment 11 — Application Management Tests.
Covers:
- Authentication & authorization on all endpoints
- Applicant creation (draft state, server-side ID generation, ownership assignment)
- Duplicate application prevention (409 Conflict)
- Get endpoints (GET /me, GET /{id}, ownership enforcement, 404 handling)
- Update endpoints (PUT /{id}, draft only, rejection of submitted updates, protected field immunity)
- Programme selection validation (mca, mba, msc-cs, mtech-cs, rejection of unsupported)
- Basic application validation (email, mobile, PIN, percentage, CGPA, graduation year)
- Submission lifecycle (incomplete rejection, valid submission, timestamping, state transition, idempotent re-submit rejection)
- Admin access (GET list, GET details, RBAC 403 for applicants)
- Seed compatibility with Increment 9
"""

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.security import create_access_token, get_password_hash
from app.main import app


@pytest.fixture(autouse=True)
def clean_db():
    """Ensure clean collections and correct indexes for each test."""
    with TestClient(app):
        db = get_db()
        db["users"].delete_many({})
        db["applications"].delete_many({})
        db["users"].create_index("email", unique=True)
        db["applications"].create_index("userId", unique=True, sparse=True)
        db["applications"].create_index("applicationId", unique=True, sparse=True)
        yield
        db["users"].delete_many({})
        db["applications"].delete_many({})


def register_applicant(client: TestClient, email: str = "applicant1@example.com", name: str = "Applicant One"):
    payload = {
        "fullName": name,
        "email": email,
        "mobile": "9876543210",
        "dob": "2001-01-01",
        "password": "Password123!",
    }
    res = client.post("/api/v1/auth/register", json=payload)
    assert res.status_code == 201
    data = res.json()
    token = data["token"]
    headers = {"Authorization": f"Bearer {token}"}
    return data, headers


def get_admin_headers():
    db = get_db()
    admin_doc = {
        "email": "admin@example.com",
        "hashed_password": get_password_hash("AdminPass123!"),
        "full_name": "Admin User",
        "role": "admin",
        "applicant_id": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    res = db["users"].insert_one(admin_doc)
    token = create_access_token(subject=str(res.inserted_id), role="admin")
    return {"Authorization": f"Bearer {token}"}


COMPLETE_APPLICATION_PAYLOAD = {
    "programmeId": "mca",
    "applicationMode": "Regular",
    "fullName": "Applicant One",
    "dob": "2001-01-01",
    "gender": "Male",
    "nationality": "Indian",
    "email": "applicant1@example.com",
    "mobile": "9876543210",
    "address": "123 Anna Salai",
    "city": "Chennai",
    "state": "Tamil Nadu",
    "pinCode": "600001",
    "tenthBoard": "State Board",
    "tenthPercentage": 88.0,
    "twelfthBoard": "State Board",
    "twelfthPercentage": 84.0,
    "ugDegree": "BCA",
    "university": "Madras University",
    "graduationYear": 2023,
    "cgpa": 8.5,
}


# ==============================================================================
# 1. AUTHENTICATION REQUIREMENTS
# ==============================================================================

def test_unauthenticated_requests_fail_with_401():
    with TestClient(app) as client:
        # Missing tokens on all protected endpoints
        assert client.get("/api/v1/applications/me").status_code == 401
        assert client.post("/api/v1/applications", json={"programmeId": "mca"}).status_code == 401
        assert client.get("/api/v1/applications").status_code == 401
        assert client.get("/api/v1/applications/SE20260001").status_code == 401
        assert client.put("/api/v1/applications/SE20260001", json={"city": "Salem"}).status_code == 401
        assert client.post("/api/v1/applications/SE20260001/submit").status_code == 401


def test_invalid_token_fails_with_401():
    with TestClient(app) as client:
        bad_headers = {"Authorization": "Bearer invalid.jwt.token"}
        assert client.get("/api/v1/applications/me", headers=bad_headers).status_code == 401
        assert client.post("/api/v1/applications", json={"programmeId": "mca"}, headers=bad_headers).status_code == 401


# ==============================================================================
# 2. APPLICANT CREATION REQUIREMENTS
# ==============================================================================

def test_authenticated_applicant_can_create_draft_application():
    with TestClient(app) as client:
        user_info, headers = register_applicant(client)

        res = client.post("/api/v1/applications", json={"programmeId": "mca"}, headers=headers)
        assert res.status_code == 201
        data = res.json()

        assert data["status"] == "DRAFT"
        assert data["applicationId"].startswith("SE")
        assert data["applicantId"] == user_info["applicantId"]
        assert data["programmeId"] == "mca"
        assert data["createdAt"] is not None
        assert data["updatedAt"] is not None
        assert data["submittedAt"] is None


def test_client_cannot_override_ownership_or_status():
    with TestClient(app) as client:
        user_info, headers = register_applicant(client)

        spoofed_payload = {
            "programmeId": "mca",
            "applicationId": "SE99999999",
            "userId": "attacker_user_id",
            "applicantId": "APL-SPOOF",
            "status": "SUBMITTED",
            "submittedAt": "2020-01-01T00:00:00Z",
        }

        res = client.post("/api/v1/applications", json=spoofed_payload, headers=headers)
        assert res.status_code == 201
        data = res.json()

        # Server overrides all client-controlled metadata
        assert data["applicationId"] != "SE99999999"
        assert data["applicationId"].startswith("SE")
        assert data["applicantId"] == user_info["applicantId"]
        assert data["status"] == "DRAFT"
        assert data["submittedAt"] is None


# ==============================================================================
# 3. DUPLICATE APPLICATION PREVENTION
# ==============================================================================

def test_same_applicant_cannot_create_second_application():
    with TestClient(app) as client:
        _, headers = register_applicant(client)

        # First creation succeeds
        res1 = client.post("/api/v1/applications", json={"programmeId": "mca"}, headers=headers)
        assert res1.status_code == 201

        # Second creation returns 409 Conflict
        res2 = client.post("/api/v1/applications", json={"programmeId": "mba"}, headers=headers)
        assert res2.status_code == 409
        assert "already exists" in res2.json()["detail"].lower()


# ==============================================================================
# 4. GET APPLICATION ENDPOINTS
# ==============================================================================

def test_applicant_can_retrieve_own_application():
    with TestClient(app) as client:
        _, headers = register_applicant(client)
        create_res = client.post("/api/v1/applications", json={"programmeId": "mca"}, headers=headers)
        app_id = create_res.json()["applicationId"]

        # GET /me
        me_res = client.get("/api/v1/applications/me", headers=headers)
        assert me_res.status_code == 200
        assert me_res.json()["applicationId"] == app_id

        # GET /{application_id}
        by_id_res = client.get(f"/api/v1/applications/{app_id}", headers=headers)
        assert by_id_res.status_code == 200
        assert by_id_res.json()["applicationId"] == app_id


def test_applicant_with_no_application_gets_404_on_me():
    with TestClient(app) as client:
        _, headers = register_applicant(client)
        res = client.get("/api/v1/applications/me", headers=headers)
        assert res.status_code == 404
        assert "no application found" in res.json()["detail"].lower()


def test_applicant_cannot_retrieve_another_applicant_application():
    with TestClient(app) as client:
        _, headers1 = register_applicant(client, email="app1@example.com")
        create_res1 = client.post("/api/v1/applications", json={"programmeId": "mca"}, headers=headers1)
        app1_id = create_res1.json()["applicationId"]

        _, headers2 = register_applicant(client, email="app2@example.com")

        # Applicant 2 attempts to get Applicant 1's application
        res = client.get(f"/api/v1/applications/{app1_id}", headers=headers2)
        assert res.status_code == 403
        assert "not authorized" in res.json()["detail"].lower()


def test_admin_can_retrieve_any_applicant_application():
    with TestClient(app) as client:
        _, applicant_headers = register_applicant(client)
        create_res = client.post("/api/v1/applications", json={"programmeId": "mca"}, headers=applicant_headers)
        app_id = create_res.json()["applicationId"]

        admin_headers = get_admin_headers()
        res = client.get(f"/api/v1/applications/{app_id}", headers=admin_headers)
        assert res.status_code == 200
        assert res.json()["applicationId"] == app_id


def test_get_nonexistent_application_returns_404():
    with TestClient(app) as client:
        admin_headers = get_admin_headers()
        res = client.get("/api/v1/applications/UNKNOWN", headers=admin_headers)
        assert res.status_code == 404
        assert res.json()["detail"] == "Application not found"


# ==============================================================================
# 5. UPDATE APPLICATION ENDPOINTS
# ==============================================================================

def test_applicant_can_update_own_draft():
    with TestClient(app) as client:
        _, headers = register_applicant(client)
        create_res = client.post("/api/v1/applications", json={"programmeId": "mca"}, headers=headers)
        app_id = create_res.json()["applicationId"]

        update_payload = {
            "city": "Coimbatore",
            "state": "Tamil Nadu",
            "cgpa": 9.2,
        }
        res = client.put(f"/api/v1/applications/{app_id}", json=update_payload, headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["city"] == "Coimbatore"
        assert data["cgpa"] == "9.2" or data["cgpa"] == 9.2


def test_applicant_cannot_update_another_applicant_application():
    with TestClient(app) as client:
        _, headers1 = register_applicant(client, email="app1@example.com")
        create_res = client.post("/api/v1/applications", json={"programmeId": "mca"}, headers=headers1)
        app1_id = create_res.json()["applicationId"]

        _, headers2 = register_applicant(client, email="app2@example.com")

        res = client.put(f"/api/v1/applications/{app1_id}", json={"city": "Trichy"}, headers=headers2)
        assert res.status_code == 403
        assert "not authorized" in res.json()["detail"].lower()


def test_server_managed_fields_cannot_be_changed_via_update():
    with TestClient(app) as client:
        _, headers = register_applicant(client)
        create_res = client.post("/api/v1/applications", json={"programmeId": "mca"}, headers=headers)
        app_id = create_res.json()["applicationId"]

        malicious_update = {
            "applicationId": "SE99999999",
            "status": "ELIGIBLE",
            "userId": "other_id",
            "submittedAt": "2026-01-01T00:00:00Z",
            "city": "Madurai",
        }
        res = client.put(f"/api/v1/applications/{app_id}", json=malicious_update, headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["applicationId"] == app_id
        assert data["status"] == "DRAFT"
        assert data["submittedAt"] is None
        assert data["city"] == "Madurai"


def test_cannot_update_submitted_application():
    with TestClient(app) as client:
        _, headers = register_applicant(client)
        create_res = client.post("/api/v1/applications", json=COMPLETE_APPLICATION_PAYLOAD, headers=headers)
        app_id = create_res.json()["applicationId"]

        # Submit
        submit_res = client.post(f"/api/v1/applications/{app_id}/submit", headers=headers)
        assert submit_res.status_code == 200
        assert submit_res.json()["status"] == "SUBMITTED"

        # Attempt update
        update_res = client.put(f"/api/v1/applications/{app_id}", json={"city": "Salem"}, headers=headers)
        assert update_res.status_code == 400
        assert "already been submitted" in update_res.json()["detail"].lower()


# ==============================================================================
# 6. PROGRAMME VALIDATION
# ==============================================================================

def test_supported_programmes_are_accepted():
    for prog in ["mca", "mba", "msc-cs", "mtech-cs"]:
        with TestClient(app) as client:
            _, headers = register_applicant(client, email=f"{prog}@example.com")
            res = client.post("/api/v1/applications", json={"programmeId": prog}, headers=headers)
            assert res.status_code == 201
            assert res.json()["programmeId"] == prog


def test_unsupported_programme_is_rejected():
    with TestClient(app) as client:
        _, headers = register_applicant(client)
        res = client.post("/api/v1/applications", json={"programmeId": "bachelor-arts"}, headers=headers)
        assert res.status_code == 422


# ==============================================================================
# 7. BASIC INPUT VALIDATION
# ==============================================================================

def test_validation_errors():
    with TestClient(app) as client:
        _, headers = register_applicant(client)

        # Missing required programmeId on creation
        assert client.post("/api/v1/applications", json={}, headers=headers).status_code == 422

        # Invalid email
        assert client.post("/api/v1/applications", json={"programmeId": "mca", "email": "invalid-email"}, headers=headers).status_code == 422

        # Invalid mobile (not 10 digits)
        assert client.post("/api/v1/applications", json={"programmeId": "mca", "mobile": "12345"}, headers=headers).status_code == 422
        assert client.post("/api/v1/applications", json={"programmeId": "mca", "mobile": "abcdefghij"}, headers=headers).status_code == 422

        # Invalid PIN code (not 6 digits)
        assert client.post("/api/v1/applications", json={"programmeId": "mca", "pinCode": "123"}, headers=headers).status_code == 422
        assert client.post("/api/v1/applications", json={"programmeId": "mca", "pinCode": "abcdef"}, headers=headers).status_code == 422

        # Invalid percentage (> 100 or < 0)
        assert client.post("/api/v1/applications", json={"programmeId": "mca", "tenthPercentage": 150}, headers=headers).status_code == 422
        assert client.post("/api/v1/applications", json={"programmeId": "mca", "twelfthPercentage": -5}, headers=headers).status_code == 422

        # Invalid CGPA (> 10.0 or < 0)
        assert client.post("/api/v1/applications", json={"programmeId": "mca", "cgpa": 12.0}, headers=headers).status_code == 422

        # Invalid graduation year (out of range)
        assert client.post("/api/v1/applications", json={"programmeId": "mca", "graduationYear": 1850}, headers=headers).status_code == 422
        assert client.post("/api/v1/applications", json={"programmeId": "mca", "graduationYear": 3050}, headers=headers).status_code == 422


# ==============================================================================
# 8. SUBMISSION WORKFLOW
# ==============================================================================

def test_incomplete_draft_cannot_be_submitted():
    with TestClient(app) as client:
        _, headers = register_applicant(client)
        # Create minimal draft with only programmeId
        create_res = client.post("/api/v1/applications", json={"programmeId": "mca"}, headers=headers)
        app_id = create_res.json()["applicationId"]

        # Attempt to submit incomplete draft
        submit_res = client.post(f"/api/v1/applications/{app_id}/submit", headers=headers)
        assert submit_res.status_code == 400
        assert "incomplete application" in submit_res.json()["detail"].lower()


def test_complete_draft_submits_successfully():
    with TestClient(app) as client:
        _, headers = register_applicant(client)
        create_res = client.post("/api/v1/applications", json=COMPLETE_APPLICATION_PAYLOAD, headers=headers)
        app_id = create_res.json()["applicationId"]

        # Submit
        submit_res = client.post(f"/api/v1/applications/{app_id}/submit", headers=headers)
        assert submit_res.status_code == 200
        data = submit_res.json()
        assert data["status"] == "SUBMITTED"
        assert data["submittedAt"] is not None
        assert data["updatedAt"] is not None


def test_already_submitted_application_cannot_be_submitted_again():
    with TestClient(app) as client:
        _, headers = register_applicant(client)
        create_res = client.post("/api/v1/applications", json=COMPLETE_APPLICATION_PAYLOAD, headers=headers)
        app_id = create_res.json()["applicationId"]

        # First submit
        res1 = client.post(f"/api/v1/applications/{app_id}/submit", headers=headers)
        assert res1.status_code == 200

        # Second submit
        res2 = client.post(f"/api/v1/applications/{app_id}/submit", headers=headers)
        assert res2.status_code == 400
        assert "already submitted" in res2.json()["detail"].lower()


def test_applicant_cannot_submit_another_applicant_application():
    with TestClient(app) as client:
        _, headers1 = register_applicant(client, email="app1@example.com")
        create_res = client.post("/api/v1/applications", json=COMPLETE_APPLICATION_PAYLOAD, headers=headers1)
        app1_id = create_res.json()["applicationId"]

        _, headers2 = register_applicant(client, email="app2@example.com")
        res = client.post(f"/api/v1/applications/{app1_id}/submit", headers=headers2)
        assert res.status_code == 403
        assert "not authorized" in res.json()["detail"].lower()


# ==============================================================================
# 9. ADMIN ACCESS ENDPOINTS
# ==============================================================================

def test_admin_can_list_applications():
    with TestClient(app) as client:
        # Create an application
        _, applicant_headers = register_applicant(client)
        client.post("/api/v1/applications", json=COMPLETE_APPLICATION_PAYLOAD, headers=applicant_headers)

        admin_headers = get_admin_headers()
        res = client.get("/api/v1/applications", headers=admin_headers)
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "applicationId" in data[0]
        assert "status" in data[0]


def test_applicant_cannot_use_admin_listing_endpoint():
    with TestClient(app) as client:
        _, applicant_headers = register_applicant(client)
        res = client.get("/api/v1/applications", headers=applicant_headers)
        assert res.status_code == 403
        assert "not permitted" in res.json()["detail"].lower()


# ==============================================================================
# 10. SEED COMPATIBILITY WITH INCREMENT 9
# ==============================================================================

def test_seed_and_get_application():
    with TestClient(app) as client:
        seed_response = client.post("/api/v1/applications/seed")
        assert seed_response.status_code == 200
        assert seed_response.json() == {"status": "Database seeded successfully"}

        admin_headers = get_admin_headers()
        get_response = client.get("/api/v1/applications/APL-1001", headers=admin_headers)
        assert get_response.status_code == 200
        data = get_response.json()
        assert data["applicantId"] == "APL-1001"
