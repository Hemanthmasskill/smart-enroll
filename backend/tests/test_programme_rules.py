import pytest
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.services.programme_rules import (
    CANONICAL_PROGRAMME_RULES_V1,
    get_programme_rules,
    seed_programme_rules,
)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def clean_db():
    db = get_db()
    assert settings.DATABASE_NAME == "smartenroll_test"
    db["users"].delete_many({})
    db["applications"].delete_many({})
    db["programme_rules"].delete_many({})
    yield db


@pytest.fixture
def applicant_auth(client, clean_db):
    reg = client.post(
        f"{settings.API_V1_STR}/auth/register",
        json={
            "fullName": "Jane Doe",
            "email": "jane.doe@example.com",
            "mobile": "9876543210",
            "dob": "2000-01-15",
            "password": "Password123!",
        },
    )
    assert reg.status_code == 201
    return reg.json()


@pytest.fixture
def admin_auth(client, clean_db):
    from app.core.security import get_password_hash
    clean_db["users"].insert_one({
        "email": "admin@university.edu",
        "hashed_password": get_password_hash("AdminPassword123!"),
        "role": "admin",
        "full_name": "Admin User",
        "is_active": True,
        "tokenVersion": 1,
    })
    login = client.post(
        f"{settings.API_V1_STR}/auth/login",
        json={"email": "admin@university.edu", "password": "AdminPassword123!", "role": "admin"},
    )
    assert login.status_code == 200
    return login.json()


def test_seed_programme_rules_is_idempotent(clean_db):
    """Verify that calling seed_programme_rules multiple times does not produce duplicates."""
    count1 = seed_programme_rules(clean_db)
    assert count1 == 4

    count2 = seed_programme_rules(clean_db)
    assert count2 == 4

    # Ensure exactly 4 records exist in the collection
    assert clean_db["programme_rules"].count_documents({}) == 4

    # Check each canonical programme exists with expected fields
    for p in ["mca", "mba", "msc-cs", "mtech-cs"]:
        rule = clean_db["programme_rules"].find_one({"programmeId": p})
        assert rule is not None
        assert rule["version"] == "1.0.0"
        assert "effectiveFrom" in rule
        assert "minPercentage" in rule
        assert "mathematicsRequirement" in rule
        assert "allowedDegreeFamilies" in rule


def test_programme_rules_unique_index_enforcement(clean_db):
    """Verify unique compound index on (programmeId, version) rejects duplicates."""
    seed_programme_rules(clean_db)
    with pytest.raises(DuplicateKeyError):
        clean_db["programme_rules"].insert_one({
            "programmeId": "mca",
            "version": "1.0.0",
            "name": "Duplicate MCA",
        })


def test_get_programme_rules_endpoint_requires_auth(client):
    """Unauthenticated access to GET /api/v1/programmes/{id}/rules must return 401."""
    response = client.get(f"{settings.API_V1_STR}/programmes/mca/rules")
    assert response.status_code == 401


def test_get_programme_rules_endpoint_success(client, applicant_auth, admin_auth, clean_db):
    """Authenticated applicants and admins can retrieve rules for all 4 seeded programmes."""
    seed_programme_rules(clean_db)

    headers_applicant = {"Authorization": f"Bearer {applicant_auth['token']}"}
    headers_admin = {"Authorization": f"Bearer {admin_auth['token']}"}

    # MCA
    res_mca = client.get(f"{settings.API_V1_STR}/programmes/mca/rules", headers=headers_applicant)
    assert res_mca.status_code == 200
    mca_data = res_mca.json()
    assert mca_data["programmeId"] == "mca"
    assert mca_data["minPercentage"] == 50.0
    assert mca_data["mathematicsRequirement"] == "10+2_OR_GRADUATION"
    assert mca_data["degreeLevel"] == "BACHELORS"
    assert mca_data["cgpaToPercentageFactor"] == 9.5

    # MBA
    res_mba = client.get(f"{settings.API_V1_STR}/programmes/mba/rules", headers=headers_admin)
    assert res_mba.status_code == 200
    mba_data = res_mba.json()
    assert mba_data["programmeId"] == "mba"
    assert mba_data["minPercentage"] == 50.0
    assert mba_data["mathematicsRequirement"] == "NONE"

    # MSc CS
    res_msc = client.get(f"{settings.API_V1_STR}/programmes/msc-cs/rules", headers=headers_applicant)
    assert res_msc.status_code == 200
    msc_data = res_msc.json()
    assert msc_data["programmeId"] == "msc-cs"
    assert msc_data["minPercentage"] == 55.0
    assert msc_data["mathematicsRequirement"] == "GRADUATION"

    # MTech CS
    res_mtech = client.get(f"{settings.API_V1_STR}/programmes/mtech-cs/rules", headers=headers_applicant)
    assert res_mtech.status_code == 200
    mtech_data = res_mtech.json()
    assert mtech_data["programmeId"] == "mtech-cs"
    assert mtech_data["minPercentage"] == 60.0
    assert mtech_data["mathematicsRequirement"] == "GRADUATION"
    assert mtech_data["allowedDegreeFamilies"] == ["ENGINEERING_TECHNOLOGY"]


def test_get_programme_rules_endpoint_not_found(client, applicant_auth, clean_db):
    """Querying rules for an unknown programme returns 404."""
    seed_programme_rules(clean_db)
    headers = {"Authorization": f"Bearer {applicant_auth['token']}"}
    response = client.get(f"{settings.API_V1_STR}/programmes/nonexistent-program/rules", headers=headers)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
