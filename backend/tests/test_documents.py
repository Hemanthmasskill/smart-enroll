from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, get_password_hash
from app.main import app
from app.schemas.document import (
    DEGREE_VARIANTS,
    DOCUMENT_TYPES,
)

VALID_PDF_BYTES = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n%%EOF"
VALID_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)
VALID_JPEG_BYTES = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07"
    b"\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e"
    b"\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01"
    b"\x01\x11\x00\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
)


@pytest.fixture(autouse=True)
def setup_isolated_env(tmp_path, monkeypatch):
    """Use isolated temporary directory for storage and clear test database collections."""
    assert settings.DATABASE_NAME == "smartenroll_test", (
        f"Safety assertion failed: Expected 'smartenroll_test', got '{settings.DATABASE_NAME}'"
    )
    test_storage = tmp_path / "test_storage"
    test_storage.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "STORAGE_DIR", str(test_storage))
    monkeypatch.setattr(settings, "DATABASE_NAME", "smartenroll_test")

    with TestClient(app) as client:
        db = get_db()
        assert db.name == "smartenroll_test"
        db["users"].delete_many({})
        db["applications"].delete_many({})
        db["documents"].delete_many({})

        db["users"].create_index("email", unique=True)
        db["applications"].create_index("userId", unique=True, sparse=True)
        db["applications"].create_index("applicationId", unique=True, sparse=True)
        db["documents"].create_index([("applicationId", 1), ("documentType", 1)], unique=True)
        db["documents"].create_index("documentId", unique=True, sparse=True)
        yield
        assert db.name == "smartenroll_test"
        db["users"].delete_many({})
        db["applications"].delete_many({})
        db["documents"].delete_many({})


def register_applicant(
    client: TestClient,
    email: str = "applicant1@example.com",
    name: str = "Applicant One",
    programme_id: str = "mca",
):
    """Register applicant and create initial draft application."""
    reg_res = client.post(
        "/api/v1/auth/register",
        json={
            "fullName": name,
            "email": email,
            "mobile": "9876543210",
            "dob": "2001-01-01",
            "password": "Password123!",
        },
    )
    assert reg_res.status_code == 201
    token = reg_res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create draft application
    app_res = client.post(
        "/api/v1/applications",
        headers=headers,
        json={"programmeId": programme_id},
    )
    assert app_res.status_code == 201
    application_data = app_res.json()

    return {
        "headers": headers,
        "token": token,
        "applicationId": application_data["applicationId"],
        "user": reg_res.json(),
    }


def get_admin_headers():
    db = get_db()
    admin_doc = {
        "email": "admin@example.com",
        "hashed_password": get_password_hash("AdminPass123!"),
        "full_name": "Admin User",
        "role": "admin",
    }
    res = db["users"].insert_one(admin_doc)
    token = create_access_token(subject=str(res.inserted_id), role="admin")
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 1. Authentication and Authorization Tests
# ---------------------------------------------------------------------------


def test_unauthenticated_requests_rejected():
    client = TestClient(app)
    # Upload
    res = client.post(
        "/api/v1/documents/upload",
        files={"file": ("test.pdf", VALID_PDF_BYTES, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    assert res.status_code == 401

    # List
    res = client.get("/api/v1/documents")
    assert res.status_code == 401

    # Get single
    res = client.get("/api/v1/documents/doc_123")
    assert res.status_code == 401

    # Delete
    res = client.delete("/api/v1/documents/doc_123")
    assert res.status_code == 401


def test_applicant_cannot_access_or_delete_other_applicant_document():
    client = TestClient(app)
    applicant1 = register_applicant(client, "app1@example.com", "Applicant One")
    applicant2 = register_applicant(client, "app2@example.com", "Applicant Two")

    # Applicant 1 uploads 10TH_MARKSHEET
    upload_res = client.post(
        "/api/v1/documents/upload",
        headers=applicant1["headers"],
        files={"file": ("10th.pdf", VALID_PDF_BYTES, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["documentId"]

    # Applicant 2 tries to retrieve Applicant 1's document metadata -> 403
    get_res = client.get(f"/api/v1/documents/{doc_id}", headers=applicant2["headers"])
    assert get_res.status_code == 403

    # Applicant 2 tries to download Applicant 1's document file -> 403
    dl_res = client.get(f"/api/v1/documents/{doc_id}/download", headers=applicant2["headers"])
    assert dl_res.status_code == 403

    # Applicant 2 tries to delete Applicant 1's document -> 403
    del_res = client.delete(f"/api/v1/documents/{doc_id}", headers=applicant2["headers"])
    assert del_res.status_code == 403

    # Applicant 2 cannot upload on Applicant 1's applicationId
    spoof_upload = client.post(
        "/api/v1/documents/upload",
        headers=applicant2["headers"],
        files={"file": ("spoof.pdf", VALID_PDF_BYTES, "application/pdf")},
        data={"documentType": "12TH_MARKSHEET", "applicationId": applicant1["applicationId"]},
    )
    assert spoof_upload.status_code == 403


def test_admin_permissions_policy():
    client = TestClient(app)
    applicant = register_applicant(client, "app_policy@example.com", "Applicant Policy")
    admin_headers = get_admin_headers()

    # Upload document as applicant
    upload_res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("10th.pdf", VALID_PDF_BYTES, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["documentId"]

    # Admin CAN list documents for an application
    admin_list = client.get(
        f"/api/v1/documents?applicationId={applicant['applicationId']}",
        headers=admin_headers,
    )
    assert admin_list.status_code == 200
    slots = admin_list.json()
    assert len(slots) == 6

    # Admin CAN retrieve document metadata
    admin_get = client.get(f"/api/v1/documents/{doc_id}", headers=admin_headers)
    assert admin_get.status_code == 200
    assert admin_get.json()["documentId"] == doc_id
    assert "storagePath" not in admin_get.json()

    # Admin CAN download document file
    admin_dl = client.get(f"/api/v1/documents/{doc_id}/download", headers=admin_headers)
    assert admin_dl.status_code == 200
    assert admin_dl.content == VALID_PDF_BYTES

    # Admin CANNOT upload documents (403)
    admin_upload = client.post(
        "/api/v1/documents/upload",
        headers=admin_headers,
        files={"file": ("admin.pdf", VALID_PDF_BYTES, "application/pdf")},
        data={"documentType": "12TH_MARKSHEET"},
    )
    assert admin_upload.status_code == 403

    # Admin CANNOT delete documents (403)
    admin_del = client.delete(f"/api/v1/documents/{doc_id}", headers=admin_headers)
    assert admin_del.status_code == 403


def test_admin_delete_request_is_denied():
    from fastapi import HTTPException
    from app.services.document import delete_document

    client = TestClient(app)
    applicant = register_applicant(client, "app_admin_del@example.com", "Applicant Admin Del")
    admin_headers = get_admin_headers()

    upload_res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("10th.pdf", VALID_PDF_BYTES, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["documentId"]

    # 1. Route-level delete attempt by admin is denied (403)
    del_res = client.delete(f"/api/v1/documents/{doc_id}", headers=admin_headers)
    assert del_res.status_code == 403

    # 2. Service-level direct call with admin role is denied (403)
    admin_user = {"role": "admin", "_id": "admin_user_id"}
    with pytest.raises(HTTPException) as exc_info:
        delete_document(db=get_db(), current_user=admin_user, document_id=doc_id)
    assert exc_info.value.status_code == 403
    assert "Admin deletion" in exc_info.value.detail


# ---------------------------------------------------------------------------
# 2. Document Types and Degree Certificate Variants Tests
# ---------------------------------------------------------------------------


def test_all_six_document_types_supported():
    client = TestClient(app)
    applicant = register_applicant(client, "types@example.com", "Types Applicant")

    for dtype in DOCUMENT_TYPES:
        data = {"documentType": dtype}
        if dtype == "DEGREE_CERTIFICATE":
            data["documentVariant"] = "ORIGINAL_DEGREE_CERTIFICATE"

        res = client.post(
            "/api/v1/documents/upload",
            headers=applicant["headers"],
            files={"file": (f"{dtype.lower()}.pdf", VALID_PDF_BYTES, "application/pdf")},
            data=data,
        )
        assert res.status_code == 201
        assert res.json()["documentType"] == dtype
        assert res.json()["status"] == "UPLOADED"

    # Listing should show all 6 are UPLOADED
    list_res = client.get("/api/v1/documents", headers=applicant["headers"])
    assert list_res.status_code == 200
    slots = list_res.json()
    assert len(slots) == 6
    assert all(s["status"] == "UPLOADED" for s in slots)


def test_degree_certificate_variants_acceptance():
    client = TestClient(app)
    applicant = register_applicant(client, "degree@example.com", "Degree Applicant")

    for variant in DEGREE_VARIANTS:
        res = client.post(
            "/api/v1/documents/upload",
            headers=applicant["headers"],
            files={"file": ("degree.pdf", VALID_PDF_BYTES, "application/pdf")},
            data={
                "documentType": "DEGREE_CERTIFICATE",
                "documentVariant": variant,
            },
        )
        assert res.status_code == 201
        assert res.json()["documentVariant"] == variant
        assert res.json()["status"] == "UPLOADED"
        assert res.json()["status"] != "VERIFIED"

    # Final list must show exactly 1 degree slot, not 3, and status remains unverified
    list_res = client.get("/api/v1/documents", headers=applicant["headers"])
    degree_slots = [s for s in list_res.json() if s["documentType"] == "DEGREE_CERTIFICATE"]
    assert len(degree_slots) == 1
    assert degree_slots[0]["documentVariant"] == DEGREE_VARIANTS[-1]
    assert degree_slots[0]["status"] == "UPLOADED"
    assert degree_slots[0]["status"] != "VERIFIED"


def test_degree_certificate_missing_or_invalid_variant_rejected():
    client = TestClient(app)
    applicant = register_applicant(client, "degree_invalid@example.com", "Degree Invalid")

    # Missing variant
    res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("degree.pdf", VALID_PDF_BYTES, "application/pdf")},
        data={"documentType": "DEGREE_CERTIFICATE"},
    )
    assert res.status_code == 400
    assert "documentVariant" in res.json()["detail"]

    # Invalid variant
    res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("degree.pdf", VALID_PDF_BYTES, "application/pdf")},
        data={
            "documentType": "DEGREE_CERTIFICATE",
            "documentVariant": "NOT_A_VALID_VARIANT",
        },
    )
    assert res.status_code == 400
    assert "Allowed variants" in res.json()["detail"]


def test_variant_rejected_on_non_degree_document():
    client = TestClient(app)
    applicant = register_applicant(client, "non_degree@example.com", "Non Degree")

    res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("10th.pdf", VALID_PDF_BYTES, "application/pdf")},
        data={
            "documentType": "10TH_MARKSHEET",
            "documentVariant": "ORIGINAL_DEGREE_CERTIFICATE",
        },
    )
    assert res.status_code == 400
    assert "not allowed for document type" in res.json()["detail"]


# ---------------------------------------------------------------------------
# 3. File Validation Tests
# ---------------------------------------------------------------------------


def test_file_formats_pdf_png_jpeg_success():
    client = TestClient(app)
    applicant = register_applicant(client, "formats@example.com", "Formats Applicant")

    # PDF
    res_pdf = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("doc.pdf", VALID_PDF_BYTES, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    assert res_pdf.status_code == 201
    assert res_pdf.json()["contentType"] == "application/pdf"

    # PNG
    res_png = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("doc.png", VALID_PNG_BYTES, "image/png")},
        data={"documentType": "12TH_MARKSHEET"},
    )
    assert res_png.status_code == 201
    assert res_png.json()["contentType"] == "image/png"

    # JPEG
    res_jpg = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("doc.jpg", VALID_JPEG_BYTES, "image/jpeg")},
        data={"documentType": "UG_MARKSHEET"},
    )
    assert res_jpg.status_code == 201
    assert res_jpg.json()["contentType"] == "image/jpeg"


def test_file_validation_rejections():
    client = TestClient(app)
    applicant = register_applicant(client, "validation@example.com", "Validation Applicant")

    # 1. Unsupported extension (.txt)
    res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("test.txt", b"plain text", "text/plain")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    assert res.status_code == 400
    assert "Unsupported file extension" in res.json()["detail"]

    # 2. Empty file
    res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("empty.pdf", b"", "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    assert res.status_code == 400
    assert "empty" in res.json()["detail"].lower()

    # 3. Malformed signature (text in .pdf extension)
    res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("fake.pdf", b"This is not a pdf file header", "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    assert res.status_code == 400
    assert "signature" in res.json()["detail"].lower()

    # 4. Mismatched extension and signature (PNG data in .pdf file)
    res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("mismatch.pdf", VALID_PNG_BYTES, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    assert res.status_code == 400
    assert "does not match" in res.json()["detail"].lower()

    # 5. Oversized file (> 10 MiB)
    oversized_data = b"%PDF-" + b"A" * (10 * 1024 * 1024 + 1024)
    res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("large.pdf", oversized_data, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    assert res.status_code == 400
    assert "10mb" in res.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 4. Lifecycle, Storage & Replacement Tests
# ---------------------------------------------------------------------------


def test_initial_logical_slots_are_not_uploaded():
    client = TestClient(app)
    applicant = register_applicant(client, "slots@example.com", "Slots Applicant")

    res = client.get("/api/v1/documents", headers=applicant["headers"])
    assert res.status_code == 200
    slots = res.json()
    assert len(slots) == 6
    assert all(s["status"] == "NOT_UPLOADED" for s in slots)
    assert all(s["documentId"] is None for s in slots)

    # Check MongoDB: no fake physical records created
    db = get_db()
    count = db["documents"].count_documents({"applicationId": applicant["applicationId"]})
    assert count == 0


def test_replacement_and_storage_cleanup():
    client = TestClient(app)
    applicant = register_applicant(client, "replace@example.com", "Replace Applicant")
    storage_dir = Path(settings.STORAGE_DIR)

    # 1. Upload initial 10th marksheet
    res1 = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("10th_v1.pdf", VALID_PDF_BYTES, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    assert res1.status_code == 201
    doc_id1 = res1.json()["documentId"]

    # Check file exists on disk
    db = get_db()
    doc_record1 = db["documents"].find_one({"documentId": doc_id1})
    assert doc_record1 is not None
    stored_file1 = storage_dir / doc_record1["storedFileName"]
    assert stored_file1.exists()

    # 2. Attempt failed replacement with invalid file
    failed_res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("corrupt.pdf", b"corrupt data", "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    assert failed_res.status_code == 400
    # Old file MUST still exist!
    assert stored_file1.exists()
    doc_after_fail = db["documents"].find_one({"documentId": doc_id1})
    assert doc_after_fail["originalFileName"] == "10th_v1.pdf"

    # 3. Successful replacement with valid PNG file
    res2 = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("10th_v2.png", VALID_PNG_BYTES, "image/png")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    assert res2.status_code == 201
    doc_id2 = res2.json()["documentId"]

    # Old file MUST have been cleaned up
    assert not stored_file1.exists()

    # New file MUST exist
    doc_record2 = db["documents"].find_one({"documentId": doc_id2})
    stored_file2 = storage_dir / doc_record2["storedFileName"]
    assert stored_file2.exists()
    assert doc_record2["originalFileName"] == "10th_v2.png"

    # Exactly 1 active document record in MongoDB for this slot
    slot_count = db["documents"].count_documents(
        {"applicationId": applicant["applicationId"], "documentType": "10TH_MARKSHEET"}
    )
    assert slot_count == 1


def test_deletion_lifecycle():
    client = TestClient(app)
    applicant = register_applicant(client, "delete@example.com", "Delete Applicant")
    storage_dir = Path(settings.STORAGE_DIR)

    # Upload document
    upload_res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("transfer.pdf", VALID_PDF_BYTES, "application/pdf")},
        data={"documentType": "TRANSFER_CERTIFICATE"},
    )
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["documentId"]

    db = get_db()
    doc_record = db["documents"].find_one({"documentId": doc_id})
    file_path = storage_dir / doc_record["storedFileName"]
    assert file_path.exists()

    # Delete document
    del_res = client.delete(f"/api/v1/documents/{doc_id}", headers=applicant["headers"])
    assert del_res.status_code == 200

    # Physical file removed from disk
    assert not file_path.exists()

    # Record removed from MongoDB
    assert db["documents"].find_one({"documentId": doc_id}) is None

    # Listing reflects slot as NOT_UPLOADED
    list_res = client.get("/api/v1/documents", headers=applicant["headers"])
    slot = next(s for s in list_res.json() if s["documentType"] == "TRANSFER_CERTIFICATE")
    assert slot["status"] == "NOT_UPLOADED"
    assert slot["documentId"] is None


def test_frontend_id_compatibility_and_aliases():
    client = TestClient(app)
    applicant = register_applicant(client, "compat@example.com", "Compat Applicant")

    # Upload using frontend identifier "doc-transfer"
    upload_res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("tc.pdf", VALID_PDF_BYTES, "application/pdf")},
        data={"documentType": "doc-transfer"},
    )
    assert upload_res.status_code == 201
    data = upload_res.json()
    assert data["documentType"] == "TRANSFER_CERTIFICATE"
    assert data["id"] == "doc-transfer"
    assert data["fileName"] == "tc.pdf"
    assert data["name"] == "Transfer Certificate"


# ---------------------------------------------------------------------------
# 5. Targeted Defect Regression Tests
# ---------------------------------------------------------------------------


def test_ownership_when_both_applicants_have_none_applicant_id():
    """
    CRIT-1 Regression Test:
    Two distinct applicants both have applicant_id = None.
    User 2 must be rejected with 403 when attempting to access or delete User 1's document.
    """
    from datetime import datetime, timezone
    from app.core.security import create_access_token, get_password_hash

    client = TestClient(app)
    db = get_db()

    # User 1 with applicant_id = None
    u1 = {
        "email": "u1_none@example.com",
        "hashed_password": get_password_hash("Pass123!"),
        "full_name": "User 1 None",
        "role": "applicant",
        "applicant_id": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    res1 = db["users"].insert_one(u1)
    u1_id = str(res1.inserted_id)
    token1 = create_access_token(subject=u1_id, role="applicant")
    headers1 = {"Authorization": f"Bearer {token1}"}

    db["applications"].insert_one({
        "applicationId": "SE20261111",
        "userId": u1_id,
        "applicantId": None,
        "programmeId": "mca",
        "status": "DRAFT",
    })

    # User 2 with applicant_id = None
    u2 = {
        "email": "u2_none@example.com",
        "hashed_password": get_password_hash("Pass123!"),
        "full_name": "User 2 None",
        "role": "applicant",
        "applicant_id": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    res2 = db["users"].insert_one(u2)
    u2_id = str(res2.inserted_id)
    token2 = create_access_token(subject=u2_id, role="applicant")
    headers2 = {"Authorization": f"Bearer {token2}"}

    db["applications"].insert_one({
        "applicationId": "SE20262222",
        "userId": u2_id,
        "applicantId": None,
        "programmeId": "mca",
        "status": "DRAFT",
    })

    # User 1 uploads document
    upload_res = client.post(
        "/api/v1/documents/upload",
        headers=headers1,
        files={"file": ("doc1.pdf", VALID_PDF_BYTES, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["documentId"]

    # User 2 attempts to get metadata -> 403
    get_res = client.get(f"/api/v1/documents/{doc_id}", headers=headers2)
    assert get_res.status_code == 403

    # User 2 attempts to download file -> 403
    dl_res = client.get(f"/api/v1/documents/{doc_id}/download", headers=headers2)
    assert dl_res.status_code == 403

    # User 2 attempts to delete document -> 403
    del_res = client.delete(f"/api/v1/documents/{doc_id}", headers=headers2)
    assert del_res.status_code == 403

    # Legitimate owner (User 1) can get metadata, download and delete
    assert client.get(f"/api/v1/documents/{doc_id}", headers=headers1).status_code == 200
    assert client.get(f"/api/v1/documents/{doc_id}/download", headers=headers1).status_code == 200
    assert client.delete(f"/api/v1/documents/{doc_id}", headers=headers1).status_code == 200


def test_ownership_when_both_applicants_have_identical_applicant_id():
    """
    CRIT-1 Regression Test:
    Even if two users share the same applicant_id string, authoritative userId prevents cross-access.
    """
    from datetime import datetime, timezone
    from app.core.security import create_access_token, get_password_hash

    client = TestClient(app)
    db = get_db()

    u1 = {
        "email": "u1_shared@example.com",
        "hashed_password": get_password_hash("Pass123!"),
        "full_name": "User 1 Shared",
        "role": "applicant",
        "applicant_id": "APL-SHARED",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    res1 = db["users"].insert_one(u1)
    u1_id = str(res1.inserted_id)
    token1 = create_access_token(subject=u1_id, role="applicant")
    headers1 = {"Authorization": f"Bearer {token1}"}

    db["applications"].insert_one({
        "applicationId": "SE20263333",
        "userId": u1_id,
        "applicantId": "APL-SHARED",
        "programmeId": "mca",
        "status": "DRAFT",
    })

    u2 = {
        "email": "u2_shared@example.com",
        "hashed_password": get_password_hash("Pass123!"),
        "full_name": "User 2 Shared",
        "role": "applicant",
        "applicant_id": "APL-SHARED",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    res2 = db["users"].insert_one(u2)
    u2_id = str(res2.inserted_id)
    token2 = create_access_token(subject=u2_id, role="applicant")
    headers2 = {"Authorization": f"Bearer {token2}"}

    db["applications"].insert_one({
        "applicationId": "SE20264444",
        "userId": u2_id,
        "applicantId": "APL-SHARED",
        "programmeId": "mca",
        "status": "DRAFT",
    })

    upload_res = client.post(
        "/api/v1/documents/upload",
        headers=headers1,
        files={"file": ("doc.pdf", VALID_PDF_BYTES, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["documentId"]

    # User 2 rejected despite matching applicant_id
    assert client.get(f"/api/v1/documents/{doc_id}", headers=headers2).status_code == 403
    assert client.get(f"/api/v1/documents/{doc_id}/download", headers=headers2).status_code == 403
    assert client.delete(f"/api/v1/documents/{doc_id}", headers=headers2).status_code == 403


def test_concurrent_replacement_cas_conflict(monkeypatch):
    """
    HIGH-1 Regression Test:
    A competing replacement modifies storedFileName before this replacement executes.
    The CAS check detects matched_count == 0, unlinks the new file, retains the existing file,
    and returns HTTP 409 Conflict without leaving orphaned files.
    """
    import pymongo.collection

    client = TestClient(app)
    applicant = register_applicant(client, "cas@example.com", "CAS Applicant")
    storage_dir = Path(settings.STORAGE_DIR)

    # Initial upload
    res1 = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("initial.pdf", VALID_PDF_BYTES, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    assert res1.status_code == 201
    doc_id = res1.json()["documentId"]

    db = get_db()
    existing_doc = db["documents"].find_one({"documentId": doc_id})
    initial_file = storage_dir / existing_doc["storedFileName"]
    assert initial_file.exists()

    # Simulate race condition: another request modifies storedFileName right before replace_one runs
    real_replace_one = pymongo.collection.Collection.replace_one

    def race_replace_one(self, filter, replacement, *args, **kwargs):
        self.update_one(
            {"_id": existing_doc["_id"]},
            {"$set": {"storedFileName": "concurrent_replaced_file.pdf"}},
        )
        return real_replace_one(self, filter, replacement, *args, **kwargs)

    monkeypatch.setattr("pymongo.collection.Collection.replace_one", race_replace_one)

    # Attempt replacement upload
    files_before = set(storage_dir.iterdir())
    competing_res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("competing.pdf", VALID_PDF_BYTES, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    assert competing_res.status_code == 409
    assert "conflict" in competing_res.json()["detail"].lower()

    # Assert no new orphaned file was left on disk
    files_after = set(storage_dir.iterdir())
    assert files_after == files_before

    # Initial file still on disk
    assert initial_file.exists()

    # Database still reflects the concurrent file, not the failed competing upload
    current_db_doc = db["documents"].find_one({"documentId": doc_id})
    assert current_db_doc["storedFileName"] == "concurrent_replaced_file.pdf"


def test_failed_db_replacement_rollback(monkeypatch):
    """
    HIGH-1 Regression Test:
    Simulate a MongoDB error during replace_one.
    Ensures newly written file is unlinked and initial file remains intact.
    """
    import pymongo.collection

    client = TestClient(app)
    applicant = register_applicant(client, "rollback@example.com", "Rollback Applicant")
    storage_dir = Path(settings.STORAGE_DIR)

    res1 = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("v1.pdf", VALID_PDF_BYTES, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    assert res1.status_code == 201
    doc_id = res1.json()["documentId"]

    db = get_db()
    existing_doc = db["documents"].find_one({"documentId": doc_id})
    v1_file = storage_dir / existing_doc["storedFileName"]
    assert v1_file.exists()

    files_before = set(storage_dir.iterdir())

    # Monkeypatch replace_one on pymongo.collection.Collection to raise database exception
    def mock_replace_fail(*args, **kwargs):
        raise Exception("Simulated MongoDB connection failure")

    monkeypatch.setattr("pymongo.collection.Collection.replace_one", mock_replace_fail)

    res_fail = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("v2.pdf", VALID_PDF_BYTES, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    assert res_fail.status_code == 500

    # Cleaned up newly written file: no orphans left
    files_after = set(storage_dir.iterdir())
    assert files_after == files_before
    assert v1_file.exists()



def test_applicant_without_application_gets_404():
    """
    Regression Test:
    An applicant without an application gets 404 on upload and list.
    """
    client = TestClient(app)
    # Register user only, do not create application
    reg_res = client.post(
        "/api/v1/auth/register",
        json={
            "fullName": "No App User",
            "email": "noapp@example.com",
            "mobile": "9876543210",
            "dob": "2001-01-01",
            "password": "Password123!",
        },
    )
    headers = {"Authorization": f"Bearer {reg_res.json()['token']}"}

    # Upload -> 404
    up_res = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"file": ("doc.pdf", VALID_PDF_BYTES, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    assert up_res.status_code == 404

    # List -> 404
    list_res = client.get("/api/v1/documents", headers=headers)
    assert list_res.status_code == 404


def test_admin_unconstrained_listing():
    """
    Regression Test:
    Admin can list all documents across applications when applicationId filter is omitted.
    """
    client = TestClient(app)
    app1 = register_applicant(client, "a1@example.com", "App One")
    app2 = register_applicant(client, "a2@example.com", "App Two")
    admin_headers = get_admin_headers()

    client.post(
        "/api/v1/documents/upload",
        headers=app1["headers"],
        files={"file": ("doc1.pdf", VALID_PDF_BYTES, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    client.post(
        "/api/v1/documents/upload",
        headers=app2["headers"],
        files={"file": ("doc2.pdf", VALID_PDF_BYTES, "application/pdf")},
        data={"documentType": "12TH_MARKSHEET"},
    )

    admin_res = client.get("/api/v1/documents", headers=admin_headers)
    assert admin_res.status_code == 200
    docs = admin_res.json()
    assert len(docs) >= 2
    assert all("storagePath" not in d for d in docs)


def test_storage_path_safety_boundary():
    """
    Unit test for is_path_safe function.
    """
    from app.services.document import is_path_safe

    base = Path(settings.STORAGE_DIR).resolve()
    safe_child = base / "doc123.pdf"
    traversal_path = base / ".." / "secret.pdf"
    absolute_foreign = Path("/etc/passwd")

    assert is_path_safe(base, safe_child) is True
    assert is_path_safe(base, traversal_path) is False
    assert is_path_safe(base, absolute_foreign) is False
