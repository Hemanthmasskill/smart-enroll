import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.services.programme_rules import seed_programme_rules


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def clean_db():
    db = get_db()
    assert settings.DATABASE_NAME == "smartenroll_test"
    db["users"].delete_many({})
    db["applications"].delete_many({})
    db["documents"].delete_many({})
    db["eligibility_evaluations"].delete_many({})
    seed_programme_rules(db)
    yield db


def register_user(client, email: str, role: str = "applicant", name: str = "Test User") -> dict:
    if role == "admin":
        from app.core.security import get_password_hash
        db = get_db()
        db["users"].insert_one({
            "email": email,
            "hashed_password": get_password_hash("AdminPass123!"),
            "role": "admin",
            "full_name": name,
            "is_active": True,
            "tokenVersion": 1,
        })
        login = client.post(
            f"{settings.API_V1_STR}/auth/login",
            json={"email": email, "password": "AdminPass123!", "role": "admin"},
        )
        return login.json()
    else:
        reg = client.post(
            f"{settings.API_V1_STR}/auth/register",
            json={
                "fullName": name,
                "email": email,
                "mobile": "9876543210",
                "dob": "2000-01-15",
                "password": "Password123!",
            },
        )
        assert reg.status_code == 201
        return reg.json()


def create_application_for_user(client, auth_data: dict, programme_id: str = "mca") -> dict:
    full_name = auth_data.get("name") or auth_data.get("full_name") or "Test Applicant"
    res = client.post(
        f"{settings.API_V1_STR}/applications",
        headers={"Authorization": f"Bearer {auth_data['token']}"},
        json={
            "programmeId": programme_id,
            "fullName": full_name,
            "dob": "2000-01-15",
            "gender": "Male",
            "nationality": "Indian",
            "address": "123 Main St",
            "tenthPercentage": 85.0,
            "twelfthPercentage": 88.0,
            "ugDegree": "BCA",
            "cgpa": 8.5,
        },
    )
    assert res.status_code == 201
    return res.json()


def test_get_application_eligibility_authorization(client, clean_db):
    """
    Verify GET /api/v1/applications/{id}/eligibility:
    - 401 unauthenticated
    - 403 applicant A requesting applicant B's application (assert_owner)
    - 404 when not yet evaluated
    """
    user_a = register_user(client, "applicant.a@example.com", name="Applicant A")
    user_b = register_user(client, "applicant.b@example.com", name="Applicant B")

    app_a = create_application_for_user(client, user_a)
    app_id_a = app_a["applicationId"]

    # 1. Unauthenticated gets 401
    res_unauth = client.get(f"{settings.API_V1_STR}/applications/{app_id_a}/eligibility")
    assert res_unauth.status_code == 401

    # 2. Applicant B requesting Applicant A's eligibility gets 403 (assert_owner)
    res_b_req_a = client.get(
        f"{settings.API_V1_STR}/applications/{app_id_a}/eligibility",
        headers={"Authorization": f"Bearer {user_b['token']}"},
    )
    assert res_b_req_a.status_code == 403
    assert "Forbidden" in res_b_req_a.json()["detail"]

    # 3. Applicant A requesting own application before evaluation gets 404
    res_a_req_a = client.get(
        f"{settings.API_V1_STR}/applications/{app_id_a}/eligibility",
        headers={"Authorization": f"Bearer {user_a['token']}"},
    )
    assert res_a_req_a.status_code == 404
    assert "not been evaluated" in res_a_req_a.json()["detail"].lower()


def test_post_evaluate_eligibility_authorization_and_status_gate(client, clean_db):
    """
    Verify POST /api/v1/applications/{id}/eligibility/evaluate:
    - 401 unauthenticated
    - 403 when called by applicant role
    - 400 when application is NOT in ELIGIBILITY_CHECK status
    - 200 when called by admin in ELIGIBILITY_CHECK status, with atomic persistence and evaluation audit trail (D8)
    """
    user = register_user(client, "applicant@example.com", name="Applicant")
    admin = register_user(client, "admin@university.edu", role="admin", name="Admin")

    app_doc = create_application_for_user(client, user, programme_id="mca")
    app_id = app_doc["applicationId"]

    # 1. Unauthenticated gets 401
    res_unauth = client.post(f"{settings.API_V1_STR}/applications/{app_id}/eligibility/evaluate")
    assert res_unauth.status_code == 401

    # 2. Applicant gets 403 Forbidden
    res_app_call = client.post(
        f"{settings.API_V1_STR}/applications/{app_id}/eligibility/evaluate",
        headers={"Authorization": f"Bearer {user['token']}"},
    )
    assert res_app_call.status_code == 403
    assert "Operation not permitted" in res_app_call.json()["detail"]

    # 3. Admin calls while application is still in DRAFT status -> 400 Bad Request
    res_draft_eval = client.post(
        f"{settings.API_V1_STR}/applications/{app_id}/eligibility/evaluate",
        headers={"Authorization": f"Bearer {admin['token']}"},
    )
    assert res_draft_eval.status_code == 400
    assert "ELIGIBILITY_CHECK" in res_draft_eval.json()["detail"]

    # 4. Advance application to ELIGIBILITY_CHECK status and insert 6 validated documents
    clean_db["applications"].update_one(
        {"applicationId": app_id},
        {"$set": {"status": "ELIGIBILITY_CHECK"}},
    )

    doc_types = [
        "10TH_MARKSHEET",
        "12TH_MARKSHEET",
        "UG_MARKSHEET",
        "DEGREE_CERTIFICATE",
        "TRANSFER_CERTIFICATE",
        "GOVERNMENT_ID",
    ]
    for dtype in doc_types:
        d = {
            "applicationId": app_id,
            "documentId": f"doc_{dtype.lower()}",
            "documentType": dtype,
            "status": "VALIDATED",
            "validationStatus": "VALIDATED",
            "extractedFields": {},
        }
        if dtype == "UG_MARKSHEET":
            d["extractedFields"]["percentage"] = {"normalizedValue": 72.0}
            d["extractedFields"]["course"] = {"normalizedValue": "BCA"}
            d["extractedFields"]["mathematics"] = {"normalizedValue": True, "matchedLine": "Maths 80"}
        elif dtype == "DEGREE_CERTIFICATE":
            d["extractedFields"]["course"] = {"normalizedValue": "Bachelor of Computer Applications"}
        elif dtype == "12TH_MARKSHEET":
            d["extractedFields"]["mathematics"] = {"normalizedValue": True, "matchedLine": "Mathematics 88"}
        clean_db["documents"].insert_one(d)

    # Admin evaluates successfully
    res_eval = client.post(
        f"{settings.API_V1_STR}/applications/{app_id}/eligibility/evaluate",
        headers={"Authorization": f"Bearer {admin['token']}"},
    )
    assert res_eval.status_code == 200
    eval_data = res_eval.json()
    assert eval_data["status"] == "ELIGIBLE"
    assert "inputHash" in eval_data

    # Verify D8 atomic persistence on the application document
    app_after = clean_db["applications"].find_one({"applicationId": app_id})
    assert app_after["eligibilityResult"] is not None
    assert app_after["eligibilityResult"]["status"] == "ELIGIBLE"
    assert app_after["eligibilityResult"]["inputHash"] == eval_data["inputHash"]

    # Verify D8 append-only eligibility_evaluations entry
    eval_audit = clean_db["eligibility_evaluations"].find_one({"applicationId": app_id})
    assert eval_audit is not None
    assert eval_audit["status"] == "ELIGIBLE"
    assert eval_audit["evaluatorRole"] == "admin"
    assert eval_audit["inputHash"] == eval_data["inputHash"]

    # 5. Now applicant can retrieve their own eligibility
    res_app_get = client.get(
        f"{settings.API_V1_STR}/applications/{app_id}/eligibility",
        headers={"Authorization": f"Bearer {user['token']}"},
    )
    assert res_app_get.status_code == 200
    assert res_app_get.json()["status"] == "ELIGIBLE"

    # Admin can also retrieve applicant's eligibility
    res_admin_get = client.get(
        f"{settings.API_V1_STR}/applications/{app_id}/eligibility",
        headers={"Authorization": f"Bearer {admin['token']}"},
    )
    assert res_admin_get.status_code == 200
    assert res_admin_get.json()["status"] == "ELIGIBLE"
