from datetime import datetime, timezone
import io
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from PIL import Image
import pymupdf

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, get_password_hash
from app.main import app
from app.schemas.document_processing import (
    ClassificationResult,
    DocumentProcessingResult,
    ExtractedFields,
)
from app.services.ocr.classifier import classify_document
from app.services.ocr.engine import (
    MockOCREngine,
    OCREngineUnavailableError,
    TesseractOCREngine,
    get_ocr_engine,
    set_ocr_engine,
)
from app.services.ocr.field_extractor import (
    extract_fields_from_text,
    normalize_date_string,
    normalize_numeric_string,
)
from app.services.ocr.image_processor import (
    extract_text_from_image_bytes,
    validate_and_open_image,
)
from app.services.ocr.pdf_processor import process_pdf_bytes
from app.services.ocr.pipeline import (
    compute_overall_confidence,
    run_document_processing_pipeline,
)


def create_synthetic_pdf(text_lines: list[str], pages: int = 1) -> bytes:
    """Create in-memory synthetic PDF with digital native text."""
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page()
        y = 50
        for line in text_lines:
            page.insert_text((50, y), line)
            y += 25
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_synthetic_image(width: int = 300, height: int = 150, color=(255, 255, 255)) -> bytes:
    """Create in-memory synthetic PNG image."""
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def setup_isolated_env(tmp_path, monkeypatch):
    """Isolate storage and test database for pytest runs."""
    assert settings.DATABASE_NAME == "smartenroll_test"
    test_storage = tmp_path / "test_storage"
    test_storage.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "STORAGE_DIR", str(test_storage))
    monkeypatch.setattr(settings, "DATABASE_NAME", "smartenroll_test")

    # Reset any OCR engine overrides
    set_ocr_engine(None)

    with TestClient(app) as client:
        db = get_db()
        db["users"].delete_many({})
        db["applications"].delete_many({})
        db["documents"].delete_many({})
        yield
        set_ocr_engine(None)
        db["users"].delete_many({})
        db["applications"].delete_many({})
        db["documents"].delete_many({})


def register_applicant(
    client: TestClient,
    email: str = "ocr_applicant@example.com",
    name: str = "OCR Applicant",
):
    """Helper to register user and create draft application."""
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "fullName": name,
            "email": email,
            "mobile": "9876543210",
            "dob": "2001-05-15",
            "password": "Password123!",
        },
    )
    assert reg.status_code == 201
    token = reg.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    app_res = client.post(
        "/api/v1/applications",
        headers=headers,
        json={"programmeId": "mca"},
    )
    assert app_res.status_code == 201
    return {
        "headers": headers,
        "token": token,
        "applicationId": app_res.json()["applicationId"],
        "user": reg.json(),
    }


def get_admin_headers():
    db = get_db()
    admin_doc = {
        "email": "admin_ocr@example.com",
        "hashed_password": get_password_hash("AdminPass123!"),
        "full_name": "Admin User",
        "role": "admin",
    }
    res = db["users"].insert_one(admin_doc)
    token = create_access_token(subject=str(res.inserted_id), role="admin")
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 1. Pipeline & Processing Logic Unit Tests
# ---------------------------------------------------------------------------


def test_native_text_pdf_processing():
    text_content = [
        "CENTRAL BOARD OF SECONDARY EDUCATION",
        "Secondary School Examination (Class X)",
        "Candidate's Name: Priya Sharma",
        "Roll No: 1234567",
        "Date of Birth: 15/08/2004",
        "Total Marks: 450 / 500",
        "Percentage: 90.0%",
        "Institution: Delhi Public School",
    ]
    pdf_bytes = create_synthetic_pdf(text_content)

    mock_engine = MockOCREngine(mock_text="unneeded mock text")
    res = run_document_processing_pipeline(
        file_bytes=pdf_bytes,
        content_type="application/pdf",
        document_id="doc_pdf_1",
        document_type="10TH_MARKSHEET",
        engine=mock_engine,
    )

    assert res.processingState == "COMPLETED"
    assert res.textExtracted is True
    assert res.classification.predictedType == "10TH_MARKSHEET"
    assert res.classification.confidence > 0.70
    assert res.fields.candidateName is not None
    assert res.fields.candidateName.normalizedValue == "Priya Sharma"
    assert res.fields.registrationNumber.normalizedValue == "1234567"
    assert res.fields.dob.normalizedValue == "2004-08-15"
    assert res.fields.marksObtained.normalizedValue == 450.0
    assert res.fields.maxMarks.normalizedValue == 500.0
    assert res.fields.percentage.normalizedValue == 90.0
    assert res.overallConfidence > 0.75
    # Native text extraction was used; no OCR fallback needed
    assert mock_engine.call_count == 0


def test_scanned_pdf_processing_with_ocr_adapter():
    # Empty page simulating scanned image page (0 native text characters)
    empty_pdf = create_synthetic_pdf([], pages=1)

    ocr_mock_text = (
        "CENTRAL BOARD OF SECONDARY EDUCATION\n"
        "Secondary School Examination\n"
        "Name: Rahul Verma\n"
        "Roll No: 7654321\n"
        "Date of Birth: 10/12/2003\n"
        "Marks Obtained: 420\n"
        "Maximum Marks: 500\n"
        "Institution: St Joseph Higher Secondary School\n"
    )
    mock_engine = MockOCREngine(mock_text=ocr_mock_text)

    res = run_document_processing_pipeline(
        file_bytes=empty_pdf,
        content_type="application/pdf",
        document_id="doc_scanned_1",
        document_type="10TH_MARKSHEET",
        engine=mock_engine,
    )

    assert res.processingState == "COMPLETED"
    assert mock_engine.call_count == 1
    assert res.fields.candidateName.normalizedValue == "Rahul Verma"
    assert res.fields.registrationNumber.normalizedValue == "7654321"
    assert res.fields.dob.normalizedValue == "2003-12-10"
    assert res.fields.marksObtained.normalizedValue == 420.0
    assert res.fields.maxMarks.normalizedValue == 500.0
    assert any("Scanned page rendering" in w for w in res.warnings)


def test_image_processing_with_ocr_adapter():
    img_bytes = create_synthetic_image(400, 200)
    mock_ocr = (
        "ANNA UNIVERSITY CHENNAI\n"
        "Consolidated Statement of Marks\n"
        "Bachelor of Technology in Information Technology\n"
        "Candidate Name: Ananya Krishnan\n"
        "Register No: 312219205001\n"
        "CGPA: 8.75 / 10\n"
        "Passing Year: 2023\n"
    )
    mock_engine = MockOCREngine(mock_text=mock_ocr)

    res = run_document_processing_pipeline(
        file_bytes=img_bytes,
        content_type="image/png",
        document_id="doc_img_1",
        document_type="UG_MARKSHEET",
        engine=mock_engine,
    )

    assert res.processingState == "COMPLETED"
    assert res.pageCount == 1
    assert res.classification.predictedType == "UG_MARKSHEET"
    assert res.fields.candidateName.normalizedValue == "Ananya Krishnan"
    assert res.fields.registrationNumber.normalizedValue == "312219205001"
    assert res.fields.cgpa.normalizedValue == 8.75
    assert res.fields.cgpaScale.normalizedValue == 10.0
    assert res.fields.passingYear.normalizedValue == 2023
    assert res.overallConfidence > 0.70


def test_cgpa_scale_extraction_from_text():
    """Verify field extractor captures both CGPA and CGPA scale from various formatting styles."""
    from app.services.ocr.field_extractor import extract_fields_from_text

    # Scale 4.0
    fields_4 = extract_fields_from_text("Cumulative Grade Point Average: 3.5 / 4.0\nCandidate: Test")
    assert fields_4.cgpa is not None
    assert fields_4.cgpa.normalizedValue == 3.5
    assert fields_4.cgpaScale is not None
    assert fields_4.cgpaScale.normalizedValue == 4.0

    # Scale 10.0
    fields_10 = extract_fields_from_text("Final CGPA: 8.5 out of 10.0\nCourse: BCA")
    assert fields_10.cgpa is not None
    assert fields_10.cgpa.normalizedValue == 8.5
    assert fields_10.cgpaScale is not None
    assert fields_10.cgpaScale.normalizedValue == 10.0

    # Standalone scale label
    fields_scale_label = extract_fields_from_text("CGPA: 7.2\nGrade Scale: 10\nUniversity: Madras")
    assert fields_scale_label.cgpa is not None
    assert fields_scale_label.cgpa.normalizedValue == 7.2
    assert fields_scale_label.cgpaScale is not None
    assert fields_scale_label.cgpaScale.normalizedValue == 10.0


def test_ocr_engine_unavailable_graceful_failure():
    pdf_bytes = create_synthetic_pdf([], pages=1)
    unavailable_engine = MockOCREngine(is_available=False)

    res = run_document_processing_pipeline(
        file_bytes=pdf_bytes,
        content_type="application/pdf",
        document_id="doc_unavail_1",
        document_type="10TH_MARKSHEET",
        engine=unavailable_engine,
    )

    assert res.processingState == "FAILED"
    assert res.overallConfidence == 0.0
    assert "unavailable" in (res.errorMessage or "").lower()


def test_real_tesseract_engine_adapter_state():
    engine = TesseractOCREngine()
    assert engine.languages == "eng+tam+hin"
    custom_eng = TesseractOCREngine(languages="eng")
    assert custom_eng.languages == "eng"

    available = engine.is_available()
    engine_name = engine.get_engine_name()
    if not available:
        assert engine_name == "tesseract-ocr-unavailable"
        img = Image.new("RGB", (100, 100))
        with pytest.raises(OCREngineUnavailableError) as exc_info:
            engine.extract_text_from_image(img)
        assert "tesseract ocr engine is not installed or discoverable" in str(exc_info.value).lower()
    else:
        assert "tesseract" in engine_name.lower()
        # Exercise real extraction with the configured eng+tam+hin language target
        from PIL import ImageDraw
        img = Image.new("RGB", (300, 80), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.text((10, 10), "Smart Enroll Admission", fill=(0, 0, 0))
        extracted = engine.extract_text_from_image(img)
        assert len(extracted.strip()) > 0


def test_corrupt_pdf_and_malformed_image():
    mock_engine = MockOCREngine()

    # Corrupt PDF
    corrupt_pdf = b"%PDF-1.4\nthis is corrupt data"
    res_pdf = run_document_processing_pipeline(
        file_bytes=corrupt_pdf,
        content_type="application/pdf",
        document_id="doc_corrupt",
        document_type="10TH_MARKSHEET",
        engine=mock_engine,
    )
    assert res_pdf.processingState == "FAILED"
    assert "corrupt" in (res_pdf.errorMessage or "").lower()

    # Malformed Image
    corrupt_img = b"\x89PNG\r\n\x1a\ncorrupt PNG bytes"
    res_img = run_document_processing_pipeline(
        file_bytes=corrupt_img,
        content_type="image/png",
        document_id="doc_corrupt_img",
        document_type="10TH_MARKSHEET",
        engine=mock_engine,
    )
    assert res_img.processingState == "FAILED"
    assert "malformed" in (res_img.errorMessage or "").lower()


def test_unsupported_format_and_empty_content():
    mock_engine = MockOCREngine()

    # Empty content
    res_empty = run_document_processing_pipeline(
        file_bytes=b"",
        content_type="application/pdf",
        document_id="doc_empty",
        document_type="10TH_MARKSHEET",
        engine=mock_engine,
    )
    assert res_empty.processingState == "FAILED"
    assert "empty" in (res_empty.errorMessage or "").lower()

    # Unsupported format
    res_txt = run_document_processing_pipeline(
        file_bytes=b"plain text",
        content_type="text/plain",
        document_id="doc_txt",
        document_type="10TH_MARKSHEET",
        engine=mock_engine,
    )
    assert res_txt.processingState == "FAILED"
    assert "unsupported" in (res_txt.errorMessage or "").lower()


def test_pdf_page_limits():
    # 15 page document
    multi_page_pdf = create_synthetic_pdf(["Sample line for pagination test"], pages=15)
    mock_engine = MockOCREngine()

    text, total_pages, warnings = process_pdf_bytes(multi_page_pdf, ocr_engine=mock_engine)
    assert total_pages == 15
    # Warning added regarding 10-page bound
    assert any("bounded to the first 10 pages" in w for w in warnings)


def test_image_dimension_bounds():
    # Mock excessive dimension check
    oversized_img = Image.new("RGB", (4200, 100), (255, 255, 255))
    buf = io.BytesIO()
    oversized_img.save(buf, format="PNG")
    oversized_bytes = buf.getvalue()

    with pytest.raises(ValueError) as exc_info:
        validate_and_open_image(oversized_bytes)
    assert "exceeds maximum dimension" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 2. Classification & Field Extraction Unit Tests
# ---------------------------------------------------------------------------


def test_explainable_classification_all_types():
    cases = [
        ("Central Board of Secondary Education Secondary School Examination Class X", "10TH_MARKSHEET"),
        ("Council of Higher Secondary Education Senior School Certificate Examination Class XII", "12TH_MARKSHEET"),
        ("Consolidated Statement of Marks Bachelor of Technology Semester Grade Card CGPA", "UG_MARKSHEET"),
        ("This is to certify that has been admitted to the degree of Bachelor of Engineering Convocation", "DEGREE_CERTIFICATE"),
        ("Transfer Certificate Conduct Certificate Date of leaving the institution", "TRANSFER_CERTIFICATE"),
        ("Unique Identification Authority of India Government of India Aadhaar Number", "GOVERNMENT_ID"),
    ]

    for sample_text, expected in cases:
        res = classify_document(sample_text, expected_type=expected)
        assert res.predictedType == expected
        assert res.confidence >= 0.50
        assert len(res.evidence) >= 1
        assert res.typeMismatch is False


def test_classification_discrepancy_observation():
    # Text clearly says Transfer Certificate, but uploaded into 10TH_MARKSHEET slot
    tc_text = "Transfer Certificate College Leaving Certificate Date of leaving 2024"
    res = classify_document(tc_text, expected_type="10TH_MARKSHEET")

    assert res.predictedType == "TRANSFER_CERTIFICATE"
    assert res.typeMismatch is True
    assert "differs from the uploaded slot" in (res.observation or "")


def test_unidentifiable_classification():
    vague_text = "Hello world this is some random text without any academic labels."
    res = classify_document(vague_text, expected_type="10TH_MARKSHEET")
    assert res.predictedType is None
    assert res.confidence == 0.0
    assert "insufficient" in (res.observation or "").lower()


def test_normalization_utilities():
    # Date normalization
    assert normalize_date_string("15/08/2001") == "2001-08-15"
    assert normalize_date_string("2001-08-15") == "2001-08-15"
    assert normalize_date_string("15-08-2001") == "2001-08-15"
    assert normalize_date_string("15 August 2001") == "2001-08-15"
    assert normalize_date_string("invalid-date") is None
    assert normalize_date_string("99/99/9999") is None

    # Numeric normalization
    assert normalize_numeric_string("85.5") == 85.5
    assert normalize_numeric_string("1,200") == 1200.0
    assert normalize_numeric_string("abc") is None


def test_field_extraction_preserves_unambiguous_and_leaves_missing():
    raw_text = (
        "Name: Ankit Kumar\n"
        "Date of Birth: 22/04/2002\n"
        "Registration No: REG-998877\n"
        "Institution: Crescent Institute of Science and Technology\n"
        "Course: Bachelor of Computer Applications\n"
        "Marks Obtained: 450\n"
        "Maximum Marks: 500\n"
        "CGPA: 9.1\n"
        "Certificate No: CERT-0012\n"
        "Year of Passing: 2023\n"
    )
    fields = extract_fields_from_text(raw_text)

    assert fields.candidateName.normalizedValue == "Ankit Kumar"
    assert fields.dob.normalizedValue == "2002-04-22"
    assert fields.registrationNumber.normalizedValue == "REG-998877"
    assert fields.marksObtained.normalizedValue == 450.0
    assert fields.maxMarks.normalizedValue == 500.0
    assert fields.percentage.normalizedValue == 90.0  # Derived from 450/500
    assert fields.cgpa.normalizedValue == 9.1
    assert fields.certificateNumber.normalizedValue == "CERT-0012"
    assert fields.passingYear.normalizedValue == 2023

    # Field not in text is None, NEVER fabricated
    missing_text = "Name: John Doe"
    sparse_fields = extract_fields_from_text(missing_text)
    assert sparse_fields.candidateName.normalizedValue == "John Doe"
    assert sparse_fields.dob is None
    assert sparse_fields.registrationNumber is None
    assert sparse_fields.marksObtained is None
    assert sparse_fields.cgpa is None


def test_confidence_bounds_and_semantics():
    fields = ExtractedFields()
    class_res = ClassificationResult()

    # Empty text -> 0.0
    assert compute_overall_confidence("", class_res, fields) == 0.0

    # Bounded between 0.0 and 1.0
    class_res.confidence = 0.95
    assert 0.0 <= compute_overall_confidence("Sample content with adequate words", class_res, fields) <= 1.0


# ---------------------------------------------------------------------------
# 3. Authenticated Processing Endpoints & Persistence Tests
# ---------------------------------------------------------------------------


def test_process_and_retrieve_processing_result():
    client = TestClient(app)
    applicant = register_applicant(client, "test_proc@example.com", "Test Process Applicant")

    pdf_bytes = create_synthetic_pdf([
        "SECONDARY SCHOOL EXAMINATION",
        "Candidate's Name: Priya Sharma",
        "Roll No: 1234567",
        "Date of Birth: 15/08/2004",
        "Total Marks: 450 / 500",
        "Percentage: 90.0%",
    ])

    # 1. Upload document
    up_res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("10th.pdf", pdf_bytes, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    assert up_res.status_code == 201
    doc_id = up_res.json()["documentId"]

    # 2. Process document
    proc_res = client.post(
        f"/api/v1/documents/{doc_id}/process",
        headers=applicant["headers"],
    )
    assert proc_res.status_code == 200
    data = proc_res.json()
    assert data["documentId"] == doc_id
    assert data["processingState"] == "COMPLETED"
    assert data["classification"]["predictedType"] == "10TH_MARKSHEET"
    assert data["fields"]["candidateName"]["normalizedValue"] == "Priya Sharma"
    assert data["fields"]["dob"]["normalizedValue"] == "2004-08-15"
    assert data["overallConfidence"] >= 0.70

    # CRITICAL VERIFICATION: Document status must reflect validated lifecycle status, NEVER VERIFIED!
    db = get_db()
    stored_doc = db["documents"].find_one({"documentId": doc_id})
    assert stored_doc["status"] in ("UPLOADED", "MANUAL_REVIEW", "MISMATCH", "VALIDATED")
    assert stored_doc["status"] != "VERIFIED"
    assert stored_doc["processingStatus"] == "COMPLETED"
    assert stored_doc["processingResult"] is not None

    # 3. Retrieve processing result
    get_res = client.get(
        f"/api/v1/documents/{doc_id}/processing-result",
        headers=applicant["headers"],
    )
    assert get_res.status_code == 200
    assert get_res.json()["documentId"] == doc_id
    assert get_res.json()["processingState"] == "COMPLETED"

    # 4. List documents reflects processingStatus without leaking OCR text/PII
    list_res = client.get("/api/v1/documents", headers=applicant["headers"])
    assert list_res.status_code == 200
    slot = next(s for s in list_res.json() if s["documentId"] == doc_id)
    assert slot["processingStatus"] == "COMPLETED"
    assert slot["processingConfidence"] is not None
    assert "fields" not in slot
    assert "classification" not in slot


def test_repeated_processing_idempotence():
    client = TestClient(app)
    applicant = register_applicant(client, "reprocess@example.com", "Reprocess Applicant")

    pdf_bytes = create_synthetic_pdf([
        "SECONDARY SCHOOL EXAMINATION",
        "Candidate's Name: Priya Sharma",
        "Roll No: 1234567",
    ])

    up_res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("10th.pdf", pdf_bytes, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    doc_id = up_res.json()["documentId"]

    # First processing
    p1 = client.post(f"/api/v1/documents/{doc_id}/process", headers=applicant["headers"])
    assert p1.status_code == 200
    assert p1.json()["processingState"] == "COMPLETED"

    # Second processing succeeds and updates timestamp
    p2 = client.post(f"/api/v1/documents/{doc_id}/process", headers=applicant["headers"])
    assert p2.status_code == 200
    assert p2.json()["processingState"] == "COMPLETED"


def test_concurrency_conflict_returns_409():
    client = TestClient(app)
    applicant = register_applicant(client, "conflict@example.com", "Conflict Applicant")

    pdf_bytes = create_synthetic_pdf(["SECONDARY SCHOOL EXAMINATION", "Name: Tester"])
    up_res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("10th.pdf", pdf_bytes, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    doc_id = up_res.json()["documentId"]

    # Manually mark as PROCESSING to simulate ongoing background job
    db = get_db()
    db["documents"].update_one(
        {"documentId": doc_id},
        {"$set": {"processingStatus": "PROCESSING"}},
    )

    conflict_res = client.post(f"/api/v1/documents/{doc_id}/process", headers=applicant["headers"])
    assert conflict_res.status_code == 409
    assert "in progress" in conflict_res.json()["detail"].lower()


def test_cross_applicant_denial():
    client = TestClient(app)
    app1 = register_applicant(client, "user1@example.com", "User One")
    app2 = register_applicant(client, "user2@example.com", "User Two")

    pdf_bytes = create_synthetic_pdf(["SECONDARY SCHOOL EXAMINATION", "Name: User One"])
    up_res = client.post(
        "/api/v1/documents/upload",
        headers=app1["headers"],
        files={"file": ("10th.pdf", pdf_bytes, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    doc_id = up_res.json()["documentId"]

    # User 2 tries to trigger processing on User 1's document -> 403
    p_res = client.post(f"/api/v1/documents/{doc_id}/process", headers=app2["headers"])
    assert p_res.status_code == 403

    # User 1 processes successfully
    client.post(f"/api/v1/documents/{doc_id}/process", headers=app1["headers"])

    # User 2 tries to retrieve User 1's processing result -> 403
    r_res = client.get(f"/api/v1/documents/{doc_id}/processing-result", headers=app2["headers"])
    assert r_res.status_code == 403


def test_admin_processing_is_denied_but_retrieval_is_permitted():
    from fastapi import HTTPException
    from app.services.document import process_document

    client = TestClient(app)
    applicant = register_applicant(client, "app_admin_target@example.com", "Admin Target Applicant")
    admin_headers = get_admin_headers()
    other_applicant = register_applicant(client, "other_app@example.com", "Other Applicant")

    pdf_bytes = create_synthetic_pdf(["SECONDARY SCHOOL EXAMINATION", "Name: Target Applicant"])
    up_res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("10th.pdf", pdf_bytes, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    assert up_res.status_code == 201
    doc_id = up_res.json()["documentId"]

    # 1. Admin route attempt to trigger processing is denied with 403 Forbidden
    admin_proc = client.post(f"/api/v1/documents/{doc_id}/process", headers=admin_headers)
    assert admin_proc.status_code == 403
    assert "not permitted" in admin_proc.json()["detail"].lower()

    # 2. Service layer directly rejects admin user with 403 Forbidden
    db = get_db()
    admin_user = db["users"].find_one({"role": "admin"})
    with pytest.raises(HTTPException) as exc_info:
        process_document(db=db, current_user=admin_user, document_id=doc_id)
    assert exc_info.value.status_code == 403
    assert "Only applicants are permitted to process documents" in exc_info.value.detail

    # 3. Another applicant is denied processing (403) and denied result retrieval (403)
    assert client.post(f"/api/v1/documents/{doc_id}/process", headers=other_applicant["headers"]).status_code == 403
    assert client.get(f"/api/v1/documents/{doc_id}/processing-result", headers=other_applicant["headers"]).status_code == 403

    # 4. Owning applicant processes document successfully
    app_proc = client.post(f"/api/v1/documents/{doc_id}/process", headers=applicant["headers"])
    assert app_proc.status_code == 200
    assert app_proc.json()["processingState"] == "COMPLETED"

    # 5. Admin CAN retrieve the already-existing processing result for permitted inspection
    admin_get = client.get(f"/api/v1/documents/{doc_id}/processing-result", headers=admin_headers)
    assert admin_get.status_code == 200
    assert admin_get.json()["documentId"] == doc_id
    assert admin_get.json()["processingState"] == "COMPLETED"

    # 6. Owning applicant can retrieve their own processing result
    app_get = client.get(f"/api/v1/documents/{doc_id}/processing-result", headers=applicant["headers"])
    assert app_get.status_code == 200
    assert app_get.json()["documentId"] == doc_id


def test_atomic_concurrency_cas_conflict(monkeypatch):
    """
    Deterministic CAS Regression Test:
    Simulates a competing request by causing the conditional update
    {"processingStatus": {"$ne": "PROCESSING"}} to return matched_count == 0.
    Verifies that HTTP 409 is returned, OCR pipeline is not invoked,
    and no data from the competing request overwrites existing data.
    """
    import pymongo.collection

    client = TestClient(app)
    applicant = register_applicant(client, "cas_atomic@example.com", "CAS Atomic Applicant")

    pdf_bytes = create_synthetic_pdf(["SECONDARY SCHOOL EXAMINATION", "Name: CAS Tester"])
    up_res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("10th.pdf", pdf_bytes, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    doc_id = up_res.json()["documentId"]

    db = get_db()
    existing_doc = db["documents"].find_one({"documentId": doc_id})
    assert existing_doc.get("processingStatus") in (None, "NOT_STARTED")

    # Hook update_one to simulate another request claiming the document right before CAS
    real_update_one = pymongo.collection.Collection.update_one

    def race_update_one(self, filter, update, *args, **kwargs):
        if "processingStatus" in filter:
            # Simulate a competing request claiming processing right before this update
            real_update_one(self, {"documentId": doc_id}, {"$set": {"processingStatus": "PROCESSING"}})
        return real_update_one(self, filter, update, *args, **kwargs)

    monkeypatch.setattr(pymongo.collection.Collection, "update_one", race_update_one)

    conflict_res = client.post(f"/api/v1/documents/{doc_id}/process", headers=applicant["headers"])
    assert conflict_res.status_code == 409
    assert "in progress" in conflict_res.json()["detail"].lower()

    # Verify document was not completed and processingResult was not written by this failed call
    doc_after = db["documents"].find_one({"documentId": doc_id})
    assert "processingResult" not in doc_after or doc_after["processingResult"] is None


def test_database_error_during_claim_prevents_processing(monkeypatch, caplog):
    """
    Simulates a MongoDB database failure during the conditional claim update.
    Confirms that the OCR pipeline is never invoked, HTTP 500 returns a generic
    message without exposing raw PyMongo error details or database internals,
    and server-side logging records diagnostic information.
    """
    import logging
    import pymongo.collection
    import pymongo.errors

    client = TestClient(app)
    applicant = register_applicant(client, "db_err@example.com", "DB Err Applicant")

    pdf_bytes = create_synthetic_pdf(["SECONDARY SCHOOL EXAMINATION", "Name: DB Error Test"])
    up_res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("10th.pdf", pdf_bytes, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    doc_id = up_res.json()["documentId"]

    real_update_one = pymongo.collection.Collection.update_one

    def failing_update_one(self, filter, update, *args, **kwargs):
        if "processingStatus" in filter:
            raise pymongo.errors.PyMongoError("Simulated internal DB socket timeout: replica set disconnected")
        return real_update_one(self, filter, update, *args, **kwargs)

    monkeypatch.setattr(pymongo.collection.Collection, "update_one", failing_update_one)

    with caplog.at_level(logging.ERROR):
        res = client.post(f"/api/v1/documents/{doc_id}/process", headers=applicant["headers"])

    # 1. Status code is 500
    assert res.status_code == 500

    # 2. Detail message is generic and stable
    detail = res.json()["detail"]
    assert detail == "Unable to initiate document processing due to a server error. Please try again later."

    # 3. Raw exception text and database internals are NOT leaked to client
    assert "simulated internal db socket timeout" not in detail.lower()
    assert "replica set disconnected" not in detail.lower()
    assert "pymongo" not in detail.lower()
    assert "database" not in detail.lower()

    # 4. Diagnostic failure was recorded in server logs without sensitive payload
    assert any(doc_id in record.message for record in caplog.records)
    assert any("Database error while claiming document" in record.message for record in caplog.records)

    # 5. Pipeline did not run and document processingResult was not written
    db = get_db()
    stored_doc = db["documents"].find_one({"documentId": doc_id})
    assert stored_doc is not None
    assert "processingResult" not in stored_doc or stored_doc["processingResult"] is None


def test_real_concurrent_processing_requests(monkeypatch):
    """
    Real concurrency test:
    Fires two simultaneous requests using ThreadPoolExecutor while one is in-flight.
    Verifies that the atomic claim allows exactly one to proceed (200),
    while the competing concurrent request receives HTTP 409.
    """
    import concurrent.futures
    import time
    from app.services import document as doc_module

    client = TestClient(app)
    applicant = register_applicant(client, "thread_concur@example.com", "Thread Concurrency")

    pdf_bytes = create_synthetic_pdf(["SECONDARY SCHOOL EXAMINATION", "Name: Thread Concurrency"])
    up_res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("10th.pdf", pdf_bytes, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    doc_id = up_res.json()["documentId"]

    # Introduce a realistic in-flight execution window so the competing request arrives while PROCESSING
    real_run_pipeline = doc_module.run_document_processing_pipeline

    def delayed_pipeline(*args, **kwargs):
        time.sleep(0.25)
        return real_run_pipeline(*args, **kwargs)

    monkeypatch.setattr(doc_module, "run_document_processing_pipeline", delayed_pipeline)

    def call_process():
        c = TestClient(app)
        return c.post(f"/api/v1/documents/{doc_id}/process", headers=applicant["headers"])

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(call_process)
        f2 = executor.submit(call_process)
        r1 = f1.result()
        r2 = f2.result()

    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [200, 409]


def test_original_document_preserved_after_processing():
    client = TestClient(app)
    applicant = register_applicant(client, "preserve@example.com", "Preserve Applicant")
    storage_dir = Path(settings.STORAGE_DIR)

    pdf_bytes = create_synthetic_pdf(["SECONDARY SCHOOL EXAMINATION", "Original content check"])
    up_res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("10th.pdf", pdf_bytes, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    doc_id = up_res.json()["documentId"]

    db = get_db()
    stored_doc = db["documents"].find_one({"documentId": doc_id})
    file_path = storage_dir / stored_doc["storedFileName"]
    assert file_path.exists()
    original_size = file_path.stat().st_size

    # Process
    client.post(f"/api/v1/documents/{doc_id}/process", headers=applicant["headers"])

    # Physical file on disk is unchanged
    assert file_path.exists()
    assert file_path.stat().st_size == original_size
    with open(file_path, "rb") as f:
        assert f.read() == pdf_bytes


def test_retrieval_before_processing_returns_404():
    client = TestClient(app)
    applicant = register_applicant(client, "unprocessed@example.com", "Unprocessed")

    pdf_bytes = create_synthetic_pdf(["Content"])
    up_res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("10th.pdf", pdf_bytes, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    doc_id = up_res.json()["documentId"]

    # Not processed yet -> 404
    get_res = client.get(f"/api/v1/documents/{doc_id}/processing-result", headers=applicant["headers"])
    assert get_res.status_code == 404
    assert "no processing result" in get_res.json()["detail"].lower()


def test_oversized_pdf_page_rejected_before_rasterization(monkeypatch):
    """
    Regression test for bounded PDF page rendering:
    Validates expected raster dimensions against explicit safety limits.
    Rejects pages exceeding limits with ValueError without allocating an image,
    and confirms page.get_pixmap is never invoked.
    """
    doc = pymupdf.open()
    # 3000 x 3000 points. At 150 DPI, raster is 6250 x 6250 = 39,062,500 px (> 10 MP) and edge 6250 (> 4096)
    doc.new_page(width=3000, height=3000)
    oversized_pdf_bytes = doc.tobytes()
    doc.close()

    real_get_pixmap = pymupdf.Page.get_pixmap
    pixmap_called = False

    def spy_get_pixmap(self, *args, **kwargs):
        nonlocal pixmap_called
        pixmap_called = True
        return real_get_pixmap(self, *args, **kwargs)

    monkeypatch.setattr(pymupdf.Page, "get_pixmap", spy_get_pixmap)

    mock_engine = MockOCREngine()

    # Direct call to process_pdf_bytes raises ValueError before rasterization
    with pytest.raises(ValueError) as exc_info:
        process_pdf_bytes(oversized_pdf_bytes, ocr_engine=mock_engine)

    assert "safety limits" in str(exc_info.value).lower()
    assert pixmap_called is False

    # Pipeline handles the error safely, returning processingState FAILED
    res = run_document_processing_pipeline(
        file_bytes=oversized_pdf_bytes,
        content_type="application/pdf",
        document_id="doc_oversized_test",
        document_type="10TH_MARKSHEET",
        engine=mock_engine,
    )
    assert res.processingState == "FAILED"
    assert "safety limits" in (res.errorMessage or "").lower()
    assert pixmap_called is False


def test_pipeline_returns_failed_state_with_http_200_and_allows_retry():
    """
    Regression test for OCR failure reporting:
    Validates that when the OCR engine fails during processing:
    1. The API returns HTTP 200 with processingState: 'FAILED'.
    2. errorMessage is populated with the diagnostic failure detail.
    3. The document processingStatus in the database is persisted as 'FAILED'.
    4. Subsequent retry requests are accepted and succeed once the underlying issue is resolved.
    """
    client = TestClient(app)
    applicant = register_applicant(client, "fail_retry@example.com", "Fail Retry Applicant")

    # Upload empty scanned-like page that triggers OCR engine fallback
    scanned_pdf = create_synthetic_pdf([], pages=1)
    up_res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("10th.pdf", scanned_pdf, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    assert up_res.status_code == 201
    doc_id = up_res.json()["documentId"]

    # Configure engine failure
    set_ocr_engine(MockOCREngine(is_available=False))

    res = client.post(f"/api/v1/documents/{doc_id}/process", headers=applicant["headers"])
    assert res.status_code == 200
    body = res.json()
    assert body["processingState"] == "FAILED"
    assert body["overallConfidence"] == 0.0
    assert "unavailable" in (body["errorMessage"] or "").lower()

    # Verify MongoDB persistence of FAILED status
    db = get_db()
    stored_doc = db["documents"].find_one({"documentId": doc_id})
    assert stored_doc is not None
    assert stored_doc.get("processingStatus") == "FAILED"
    assert stored_doc.get("status") == "UPLOADED"  # Never changed to VERIFIED

    # Test retry: restore working engine and reprocess
    retry_engine = MockOCREngine(
        mock_text=(
            "CENTRAL BOARD OF SECONDARY EDUCATION\n"
            "Secondary School Examination (Class X)\n"
            "Name: Retry Success\n"
            "Roll No: 9988776\n"
            "Date of Birth: 12/05/2004\n"
            "Marks Obtained: 460\n"
            "Maximum Marks: 500\n"
        )
    )
    set_ocr_engine(retry_engine)

    retry_res = client.post(f"/api/v1/documents/{doc_id}/process", headers=applicant["headers"])
    assert retry_res.status_code == 200
    retry_body = retry_res.json()
    assert retry_body["processingState"] == "COMPLETED"
    assert retry_body["overallConfidence"] > 0.70
    assert retry_body["fields"]["candidateName"]["normalizedValue"] == "Retry Success"

    stored_doc_after = db["documents"].find_one({"documentId": doc_id})
    assert stored_doc_after.get("processingStatus") == "COMPLETED"


def test_mathematics_evidence_extraction():
    """Verify deterministic, ReDoS-safe mathematics subject and marks extraction for 12th and UG marksheets."""
    # 1. 12th Marksheet with Mathematics
    text_12th = (
        "BOARD OF HIGHER SECONDARY EDUCATION\n"
        "Candidate Name: Rahul Sharma\n"
        "Roll No: 1234567\n"
        "Physics: 82\n"
        "Chemistry: 78\n"
        "Mathematics: 91\n"
        "English: 85\n"
    )
    fields_12th = extract_fields_from_text(text_12th, document_type="12TH_MARKSHEET")
    assert fields_12th.mathematics is not None
    assert fields_12th.mathematics.normalizedValue is True
    assert fields_12th.mathematics.rawValue == "91"
    assert "Mathematics: 91" in fields_12th.mathematics.evidence

    # 2. UG Marksheet with Maths abbreviation
    text_ug = (
        "STATE TECHNICAL UNIVERSITY\n"
        "Semester Examination\n"
        "Candidate Name: Priya Patel\n"
        "Engineering Maths - I: 88.5\n"
        "Computer Programming: 92\n"
    )
    fields_ug = extract_fields_from_text(text_ug, document_type="UG_MARKSHEET")
    assert fields_ug.mathematics is not None
    assert fields_ug.mathematics.normalizedValue is True
    assert fields_ug.mathematics.rawValue == "88.5"

    # 3. Marksheet without mathematics
    text_no_math = (
        "HIGHER SECONDARY EXAMINATION\n"
        "History: 75\n"
        "Political Science: 80\n"
        "Economics: 85\n"
    )
    fields_no_math = extract_fields_from_text(text_no_math, document_type="12TH_MARKSHEET")
    assert fields_no_math.mathematics is None

    # 4. ReDoS resistance & input length cap
    adversarial_math_text = "Mathematics " * 50_000 + " 95"
    start_time = datetime.now()
    res_adv = extract_fields_from_text(adversarial_math_text, document_type="12TH_MARKSHEET")
    duration = (datetime.now() - start_time).total_seconds()
    assert duration < 2.0

