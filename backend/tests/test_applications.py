from fastapi.testclient import TestClient

from app.main import app


def test_get_application_not_found():
    with TestClient(app) as client:
        response = client.get("/api/v1/applications/UNKNOWN")
        assert response.status_code == 404
        assert response.json()["detail"] == "Application not found"


def test_seed_and_get_application():
    with TestClient(app) as client:
        seed_response = client.post("/api/v1/applications/seed")
        assert seed_response.status_code == 200
        assert seed_response.json() == {"status": "Database seeded successfully"}

        get_response = client.get("/api/v1/applications/APL-1001")
        assert get_response.status_code == 200
        data = get_response.json()
        assert data["applicantId"] == "APL-1001"
