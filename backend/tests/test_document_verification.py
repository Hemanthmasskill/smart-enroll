from datetime import datetime, timezone
import io
import pytest
from fastapi.testclient import TestClient
from PIL import Image
import pymupdf

from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.schemas.verification import (
    AuthoritativeVerificationRecord,
    DocumentValidationResult,
    DocumentVerificationDetailsResponse,
    FieldValidationResult,
    CrossDocumentCheckResult,
    VALIDATION_OUTCOMES,
    DOCUMENT_VALIDATION_STATUSES,
    FIELD_VALIDATION_STATUSES,
    CROSS_DOCUMENT_STATUSES,
    AUTHORITATIVE_STATUSES,
)
from app.services.verification import (
    compare_names,
    parse_and_compare_dob,
    compare_percentages,
    compare_cgpa,
    compare_years,
    compare_board,
    compare_course,
    compare_institution,
    run_cross_document_checks,
    SyntheticAuthoritativeVerificationProvider,
    validate_document_content,
)
from app.services.ocr.engine import set_ocr_engine


def create_synthetic_pdf(text_lines: list[str]) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    y = 50
    for line in text_lines:
        page.insert_text((50, y), line)
        y += 25
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.fixture(autouse=True)
def setup_isolated_env(tmp_path, monkeypatch):
    """Isolate storage and test database for pytest runs."""
    assert settings.DATABASE_NAME == "smartenroll_test"
    test_storage = tmp_path / "test_storage"
    test_storage.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "STORAGE_DIR", str(test_storage))
    monkeypatch.setattr(settings, "DATABASE_NAME", "smartenroll_test")
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
    email: str = "applicant_verif@example.com",
    name: str = "Hemanth M.P.",
    dob: str = "2000-05-15",
):
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "fullName": name,
            "email": email,
            "mobile": "9876543210",
            "dob": dob,
            "password": "Password123!",
        },
    )
    assert reg.status_code == 201
    auth_data = reg.json()
    token = auth_data["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create canonical application
    app_res = client.post(
        "/api/v1/applications",
        headers=headers,
        json={
            "programmeId": "mca",
            "fullName": name,
            "dob": dob,
            "gender": "Male",
            "tenthBoard": "CBSE",
            "tenthPercentage": 86.5,
            "twelfthBoard": "State Board",
            "twelfthPercentage": 84.0,
            "ugDegree": "BCA",
            "university": "B.S. Abdur Rahman Crescent Institute",
            "graduationYear": 2022,
            "cgpa": 8.45,
        },
    )
    assert app_res.status_code == 201
    app_data = app_res.json()

    return {
        "auth": auth_data,
        "token": token,
        "headers": headers,
        "application": app_data,
    }


def register_admin(client: TestClient, email: str = "admin_verif@example.com"):
    client.post(
        "/api/v1/auth/register",
        json={
            "fullName": "Admin Verifier",
            "email": email,
            "mobile": "9998887776",
            "dob": "1990-01-01",
            "password": "AdminPassword123!",
        },
    )
    db = get_db()
    db["users"].update_one({"email": email}, {"$set": {"role": "admin"}})
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "AdminPassword123!", "role": "admin"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["token"]
    return {"headers": {"Authorization": f"Bearer {token}"}}


# ==============================================================================
# 1. Schema and State Definitions
# ==============================================================================

def test_validation_schemas_and_status_definitions():
    assert "VALIDATED" in VALIDATION_OUTCOMES
    assert "MISMATCH" in VALIDATION_OUTCOMES
    assert "MANUAL_REVIEW" in VALIDATION_OUTCOMES
    assert "ERROR" in VALIDATION_OUTCOMES

    assert "NOT_RUN" in DOCUMENT_VALIDATION_STATUSES
    assert "MATCH" in FIELD_VALIDATION_STATUSES
    assert "SKIPPED" in CROSS_DOCUMENT_STATUSES
    assert "SIMULATED_MATCH" in AUTHORITATIVE_STATUSES

    res = DocumentValidationResult(
        documentId="doc-test-1",
        documentType="10TH_MARKSHEET",
        validationStatus="VALIDATED",
        fieldResults={
            "candidateName": FieldValidationResult(
                fieldName="candidateName",
                status="MATCH",
                extractedValue="Hemanth M.P.",
                authoritativeValue="Hemanth M.P.",
            )
        },
    )
    assert res.validationStatus == "VALIDATED"
    assert res.fieldResults["candidateName"].status == "MATCH"


# ==============================================================================
# 2. Deterministic Name Normalization and Matching
# ==============================================================================

def test_name_exact_agreement_and_whitespace():
    status, msg = compare_names("Hemanth M.P.", "Hemanth M.P.")
    assert status == "MATCH"

    status, msg = compare_names("  hemanth   m.p.  ", "Hemanth M.P.")
    assert status == "MATCH"


def test_name_punctuation_and_honorifics():
    status, msg = compare_names("Mr. Hemanth M.P.", "Hemanth M.P.")
    assert status == "MATCH"

    status, msg = compare_names("Kumari Priya Sharma", "Priya Sharma")
    assert status == "MATCH"


def test_name_token_reordering():
    status, msg = compare_names("M.P. Hemanth", "Hemanth M.P.")
    assert status == "MATCH"


def test_name_initials_and_omitted_components_return_manual_review():
    status, msg = compare_names("Hemanth M.P.", "Hemanth Madanapalli Prakash")
    assert status == "MANUAL_REVIEW"

    status, msg = compare_names("John Smith", "John Michael Smith")
    assert status == "MANUAL_REVIEW"


def test_name_initials_only_returns_manual_review():
    status, msg = compare_names("H. M.", "Hemanth")
    assert status == "MANUAL_REVIEW"


def test_name_conflicting_tokens_return_mismatch():
    status, msg = compare_names("John Smith", "John Adams")
    assert status == "MISMATCH"

    status, msg = compare_names("Priya Sharma", "Rahul Verma")
    assert status == "MISMATCH"


def test_name_empty_or_unusable_returns_not_extracted():
    status, msg = compare_names("", "Hemanth")
    assert status == "NOT_EXTRACTED"

    status, msg = compare_names("Hemanth", None)
    assert status == "MANUAL_REVIEW"


def test_name_cross_script_detection_returns_manual_review():
    # Latin vs Tamil
    status, msg = compare_names("Hemanth", "ஹேமந்த்")
    assert status == "MANUAL_REVIEW"
    assert "Different scripts" in msg

    # Latin vs Devanagari
    status, msg = compare_names("Priya", "प्रिया")
    assert status == "MANUAL_REVIEW"


# ==============================================================================
# 3. Deterministic DOB Parsing
# ==============================================================================

def test_dob_iso_and_named_month_formats():
    status, msg, dt = parse_and_compare_dob("2000-05-15", "2000-05-15")
    assert status == "MATCH"

    status, msg, dt = parse_and_compare_dob("15 August 2004", "2004-08-15")
    assert status == "MATCH"

    status, msg, dt = parse_and_compare_dob("15-Aug-2004", "2004-08-15")
    assert status == "MATCH"


def test_dob_ambiguous_numeric_dates_return_manual_review():
    # 04/05/2000 has part1 <= 12 and part2 <= 12 and part1 != part2
    status, msg, dt = parse_and_compare_dob("04/05/2000", "2000-05-04")
    assert status == "MANUAL_REVIEW"
    assert "ambiguous" in msg.lower()


def test_dob_equal_day_month_parsed_and_calendar_validated():
    # 05/05/2005 has no ambiguity
    status, msg, dt = parse_and_compare_dob("05/05/2005", "2005-05-05")
    assert status == "MATCH"

    status, msg, dt = parse_and_compare_dob("05/05/2005", "2005-06-05")
    assert status == "MISMATCH"


def test_dob_leap_year_handling():
    # 2000 is leap year -> 29/02/2000 valid
    status, msg, dt = parse_and_compare_dob("29/02/2000", "2000-02-29")
    assert status == "MATCH"

    # 2001 is NOT leap year -> 29/02/2001 invalid calendar date
    status, msg, dt = parse_and_compare_dob("29/02/2001", "2001-02-28")
    assert status == "MANUAL_REVIEW"
    assert "invalid calendar date" in msg.lower()


def test_dob_unparseable_date_returns_manual_review_safely():
    status, msg, dt = parse_and_compare_dob("Not A Date", "2000-05-15")
    assert status == "MANUAL_REVIEW"


# ==============================================================================
# 4. Numeric, Percentage, CGPA, and Academic Entity Comparisons
# ==============================================================================

def test_percentage_direct_and_calculated_from_marks():
    # Direct percentage
    status, msg, eff = compare_percentages(86.5, None, None, 86.5)
    assert status == "MATCH"

    # Calculated from marks: 432 / 500 = 86.4% -> within 0.5% of 86.5%
    status, msg, eff = compare_percentages(None, 432, 500, 86.5)
    assert status == "MATCH"
    assert eff == 86.4


def test_percentage_tolerance_bounds():
    # Within 0.5%
    status, msg, _ = compare_percentages(86.2, None, None, 86.5)
    assert status == "MATCH"

    # Beyond 0.5%
    status, msg, _ = compare_percentages(85.8, None, None, 86.5)
    assert status == "MISMATCH"


def test_cgpa_tolerance_and_scale():
    # Within 0.05
    status, msg, _ = compare_cgpa(8.42, 8.45)
    assert status == "MATCH"

    # Beyond 0.05
    status, msg, _ = compare_cgpa(8.35, 8.45)
    assert status == "MISMATCH"


def test_graduation_year_exact_comparison():
    status, msg, yr = compare_years(2022, 2022)
    assert status == "MATCH"

    status, msg, yr = compare_years(2023, 2022)
    assert status == "MISMATCH"


def test_board_alias_resolution_and_mismatch():
    status, msg = compare_board("Central Board of Secondary Education", "CBSE")
    assert status == "MATCH"

    status, msg = compare_board("ICSE", "CBSE")
    assert status == "MANUAL_REVIEW" or status == "MISMATCH"


def test_course_degree_alias_and_mismatch():
    status, msg = compare_course("Bachelor of Computer Applications", "BCA")
    assert status == "MATCH"

    status, msg = compare_course("B.Tech", "BCA")
    assert status == "MISMATCH"


def test_low_confidence_decisive_field_downgrades_to_manual_review():
    status, msg, _ = compare_percentages(86.5, None, None, 86.5, confidence=0.72)
    assert status == "MANUAL_REVIEW"
    assert "below decisive threshold" in msg.lower()


# ==============================================================================
# 5. Document Types and Mandatory Content Engine
# ==============================================================================

def test_missing_mandatory_fields_in_marksheet():
    doc = {
        "documentId": "doc-missing-test",
        "documentType": "10TH_MARKSHEET",
        "processingResult": {
            "fields": {
                # Candidate name and percentage are missing!
            }
        },
    }
    app_data = {"fullName": "Hemanth M.P.", "tenthPercentage": 86.5}
    result = validate_document_content(None, doc, app_data, None)
    assert result.validationStatus == "MANUAL_REVIEW"
    assert "candidateName" in result.missingMandatoryFields
    assert "percentage" in result.missingMandatoryFields


def test_degree_certificate_mandatory_fields():
    doc = {
        "documentId": "doc-deg-test",
        "documentType": "DEGREE_CERTIFICATE",
        "processingResult": {
            "fields": {
                "candidateName": {"normalizedValue": "Hemanth M.P.", "confidence": 0.92},
                # course is missing
            }
        },
    }
    app_data = {"fullName": "Hemanth M.P.", "ugDegree": "BCA"}
    result = validate_document_content(None, doc, app_data, None)
    assert result.validationStatus == "MANUAL_REVIEW"
    assert "course" in result.missingMandatoryFields


# ==============================================================================
# 6. Cross-Document Consistency Checks
# ==============================================================================

def test_cross_document_name_and_academic_consistency():
    curr_doc = {
        "documentId": "doc-ug",
        "documentType": "UG_MARKSHEET",
        "userId": "user-123",
        "processingResult": {
            "fields": {
                "candidateName": {"normalizedValue": "Hemanth M.P.", "confidence": 0.90},
                "registrationNumber": {"normalizedValue": "2022MCA041", "confidence": 0.90},
                "passingYear": {"normalizedValue": 2022, "confidence": 0.90},
            }
        },
    }
    # Matching sibling degree certificate
    matching_sibling = {
        "documentId": "doc-deg",
        "documentType": "DEGREE_CERTIFICATE",
        "processingStatus": "COMPLETED",
        "processingResult": {
            "fields": {
                "candidateName": {"normalizedValue": "Hemanth M.P.", "confidence": 0.90},
                "registrationNumber": {"normalizedValue": "2022MCA041", "confidence": 0.90},
                "passingYear": {"normalizedValue": 2022, "confidence": 0.90},
            }
        },
    }
    checks = run_cross_document_checks(None, curr_doc, [matching_sibling])
    statuses = {c.checkName: c.status for c in checks}
    assert any(c.status == "MATCH" for c in checks)


def test_cross_document_missing_sibling_marked_skipped():
    curr_doc = {
        "documentId": "doc-ug",
        "documentType": "UG_MARKSHEET",
        "processingResult": {
            "fields": {
                "candidateName": {"normalizedValue": "Hemanth M.P."},
            }
        },
    }
    # Unprocessed sibling
    unproc_sibling = {
        "documentId": "doc-deg",
        "documentType": "DEGREE_CERTIFICATE",
        "processingStatus": "NOT_STARTED",
        "processingResult": None,
    }
    checks = run_cross_document_checks(None, curr_doc, [unproc_sibling])
    assert len(checks) > 0
    assert all(c.status == "SKIPPED" for c in checks)


# ==============================================================================
# 7. Authoritative Simulation
# ==============================================================================

def test_authoritative_simulation_no_identifier_returns_unavailable():
    provider = SyntheticAuthoritativeVerificationProvider()
    record = provider.verify_document_credential("10TH_MARKSHEET", {})
    assert record.status == "SIMULATION_UNAVAILABLE"


def test_authoritative_simulation_unknown_identifier_returns_not_found():
    provider = SyntheticAuthoritativeVerificationProvider()
    fields = {"registrationNumber": {"normalizedValue": "UNKNOWN-ID-9999"}}
    record = provider.verify_document_credential("10TH_MARKSHEET", fields)
    assert record.status == "SIMULATED_NOT_FOUND"


def test_authoritative_simulation_matching_fixture_returns_simulated_match():
    provider = SyntheticAuthoritativeVerificationProvider()
    fields = {
        "registrationNumber": {"normalizedValue": "SYNTH-REG-2022-001", "confidence": 0.95},
        "candidateName": {"normalizedValue": "Hemanth M.P.", "confidence": 0.95},
        "dob": {"normalizedValue": "2000-05-15", "confidence": 0.95},
    }
    record = provider.verify_document_credential("UG_MARKSHEET", fields, candidate_name="Hemanth M.P.")
    assert record.status == "SIMULATED_MATCH"
    assert record.isSimulated is True
    assert "DigiLocker" in record.message or "simulation" in record.message.lower()


def test_authoritative_simulation_conflicting_fixture_returns_simulated_mismatch():
    provider = SyntheticAuthoritativeVerificationProvider()
    fields = {"registrationNumber": {"normalizedValue": "SYNTH-REG-CONFLICT-002"}}
    record = provider.verify_document_credential("UG_MARKSHEET", fields)
    assert record.status == "SIMULATED_MISMATCH"


def test_authoritative_simulation_fault_returns_unavailable():
    provider = SyntheticAuthoritativeVerificationProvider(simulate_provider_fault=True)
    fields = {"registrationNumber": {"normalizedValue": "SYNTH-REG-2022-001"}}
    record = provider.verify_document_credential("UG_MARKSHEET", fields)
    assert record.status == "SIMULATION_UNAVAILABLE"


# --- Finding 1: DOB Ambiguity & Conflict Regression Tests ---

def test_authoritative_simulation_malformed_dob_returns_unavailable():
    """Unparseable or malformed DOB on document must not produce SIMULATED_MATCH."""
    provider = SyntheticAuthoritativeVerificationProvider()
    fields = {
        "registrationNumber": {"normalizedValue": "SYNTH-REG-2022-001", "confidence": 0.95},
        "candidateName": {"normalizedValue": "Hemanth M.P.", "confidence": 0.95},
        "dob": {"rawValue": "not-a-valid-date-str", "confidence": 0.95},
    }
    record = provider.verify_document_credential("UG_MARKSHEET", fields, candidate_name="Hemanth M.P.")
    assert record.status == "SIMULATION_UNAVAILABLE"
    assert "could not be decisively verified" in record.message.lower() or "dob" in record.message.lower()


def test_authoritative_simulation_ambiguous_dob_returns_unavailable():
    """Ambiguous DOB (e.g., day/month transposition producing MANUAL_REVIEW) must not produce SIMULATED_MATCH."""
    provider = SyntheticAuthoritativeVerificationProvider()
    fields = {
        "registrationNumber": {"normalizedValue": "SYNTH-REG-2022-001", "confidence": 0.95},
        "candidateName": {"normalizedValue": "Hemanth M.P.", "confidence": 0.95},
        # "05/06/2000" compared to fixture "2000-05-15" produces MANUAL_REVIEW or MISMATCH
        "dob": {"rawValue": "05/06/2000", "confidence": 0.95},
    }
    record = provider.verify_document_credential("UG_MARKSHEET", fields, candidate_name="Hemanth M.P.")
    assert record.status in ("SIMULATION_UNAVAILABLE", "SIMULATED_MISMATCH")
    assert record.status != "SIMULATED_MATCH"


def test_authoritative_simulation_definite_dob_conflict_returns_mismatch():
    """Definite DOB mismatch produces SIMULATED_MISMATCH."""
    provider = SyntheticAuthoritativeVerificationProvider()
    fields = {
        "registrationNumber": {"normalizedValue": "SYNTH-REG-2022-001", "confidence": 0.95},
        "candidateName": {"normalizedValue": "Hemanth M.P.", "confidence": 0.95},
        "dob": {"normalizedValue": "1999-12-31", "confidence": 0.95},
    }
    record = provider.verify_document_credential("UG_MARKSHEET", fields, candidate_name="Hemanth M.P.")
    assert record.status == "SIMULATED_MISMATCH"
    assert "DOB conflict" in record.message or "does not match" in record.message


def test_authoritative_simulation_missing_required_dob_returns_unavailable():
    """When fixture has DOB, document missing DOB must return SIMULATION_UNAVAILABLE."""
    provider = SyntheticAuthoritativeVerificationProvider()
    fields = {
        "registrationNumber": {"normalizedValue": "SYNTH-REG-2022-001", "confidence": 0.95},
        "candidateName": {"normalizedValue": "Hemanth M.P.", "confidence": 0.95},
    }
    record = provider.verify_document_credential("UG_MARKSHEET", fields, candidate_name="Hemanth M.P.")
    assert record.status == "SIMULATION_UNAVAILABLE"
    assert "missing" in record.message.lower() and "birth" in record.message.lower()


# --- Finding 3: 0.80 Confidence Threshold Regression Tests ---

def test_authoritative_simulation_low_confidence_candidate_name_returns_unavailable():
    """Candidate name confidence below 0.80 must produce SIMULATION_UNAVAILABLE."""
    provider = SyntheticAuthoritativeVerificationProvider()
    fields = {
        "registrationNumber": {"normalizedValue": "SYNTH-REG-2022-001", "confidence": 0.95},
        "candidateName": {"normalizedValue": "Hemanth M.P.", "confidence": 0.72},
        "dob": {"normalizedValue": "2000-05-15", "confidence": 0.95},
    }
    record = provider.verify_document_credential("UG_MARKSHEET", fields, candidate_name="Hemanth M.P.")
    assert record.status == "SIMULATION_UNAVAILABLE"
    assert "0.80" in record.message
    assert "candidate name" in record.message.lower()


def test_authoritative_simulation_missing_candidate_name_confidence_returns_unavailable():
    """Missing candidate name confidence must not be silently treated as high-confidence."""
    provider = SyntheticAuthoritativeVerificationProvider()
    fields = {
        "registrationNumber": {"normalizedValue": "SYNTH-REG-2022-001", "confidence": 0.95},
        "candidateName": {"normalizedValue": "Hemanth M.P."},
        "dob": {"normalizedValue": "2000-05-15", "confidence": 0.95},
    }
    record = provider.verify_document_credential("UG_MARKSHEET", fields, candidate_name="Hemanth M.P.")
    assert record.status == "SIMULATION_UNAVAILABLE"
    assert "0.80" in record.message


def test_authoritative_simulation_low_confidence_lookup_identifier_returns_unavailable():
    """Lookup identifier confidence below 0.80 must produce SIMULATION_UNAVAILABLE."""
    provider = SyntheticAuthoritativeVerificationProvider()
    fields = {
        "registrationNumber": {"normalizedValue": "SYNTH-REG-2022-001", "confidence": 0.65},
        "candidateName": {"normalizedValue": "Hemanth M.P.", "confidence": 0.95},
        "dob": {"normalizedValue": "2000-05-15", "confidence": 0.95},
    }
    record = provider.verify_document_credential("UG_MARKSHEET", fields, candidate_name="Hemanth M.P.")
    assert record.status == "SIMULATION_UNAVAILABLE"
    assert "0.80" in record.message
    assert "registrationNumber" in record.message


def test_authoritative_simulation_low_confidence_dob_returns_unavailable():
    """DOB confidence below 0.80 must produce SIMULATION_UNAVAILABLE."""
    provider = SyntheticAuthoritativeVerificationProvider()
    fields = {
        "registrationNumber": {"normalizedValue": "SYNTH-REG-2022-001", "confidence": 0.95},
        "candidateName": {"normalizedValue": "Hemanth M.P.", "confidence": 0.95},
        "dob": {"normalizedValue": "2000-05-15", "confidence": 0.75},
    }
    record = provider.verify_document_credential("UG_MARKSHEET", fields, candidate_name="Hemanth M.P.")
    assert record.status == "SIMULATION_UNAVAILABLE"
    assert "0.80" in record.message
    assert "date of birth" in record.message.lower()


# ==============================================================================
# 8. End-to-End API Routes, Security and Privacy
# ==============================================================================

def test_api_verify_and_verification_endpoints():
    client = TestClient(app)
    applicant = register_applicant(client)

    pdf_bytes = create_synthetic_pdf([
        "SECONDARY SCHOOL EXAMINATION",
        "Candidate's Name: Hemanth M.P.",
        "Roll No: 1234567",
        "Date of Birth: 15/05/2000",
        "Total Marks: 432 / 500",
        "Percentage: 86.4%",
    ])

    # 1. Upload
    up_res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("10th.pdf", pdf_bytes, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    assert up_res.status_code == 201
    doc_id = up_res.json()["documentId"]

    # 2. Process
    proc_res = client.post(
        f"/api/v1/documents/{doc_id}/process",
        headers=applicant["headers"],
    )
    assert proc_res.status_code == 200

    # 3. Explicit Verify Endpoint (Applicant Owner)
    verif_res = client.post(
        f"/api/v1/documents/{doc_id}/verify",
        headers=applicant["headers"],
    )
    assert verif_res.status_code == 200
    v_data = verif_res.json()
    assert v_data["documentId"] == doc_id
    assert v_data["validationStatus"] == "VALIDATED"
    assert v_data["fieldResults"]["candidateName"]["status"] == "MATCH"

    # 4. Get Verification Details Endpoint
    get_v_res = client.get(
        f"/api/v1/documents/{doc_id}/verification",
        headers=applicant["headers"],
    )
    assert get_v_res.status_code == 200
    v_detail = get_v_res.json()
    assert v_detail["documentId"] == doc_id
    assert v_detail["validationStatus"] == "VALIDATED"
    assert v_detail["extractionSummary"] is not None

    # 5. Authoritative Verify Endpoint
    auth_res = client.post(
        f"/api/v1/documents/{doc_id}/authoritative-verify",
        headers=applicant["headers"],
    )
    assert auth_res.status_code == 200
    auth_data = auth_res.json()
    assert auth_data["isSimulated"] is True
    # Crucial check: lifecycle status is NEVER set to VERIFIED from simulated match!
    db = get_db()
    stored = db["documents"].find_one({"documentId": doc_id})
    assert stored["status"] != "VERIFIED"


def test_api_verify_unprocessed_document_returns_400():
    client = TestClient(app)
    applicant = register_applicant(client)

    pdf_bytes = create_synthetic_pdf(["Some Content"])
    up_res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("10th.pdf", pdf_bytes, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    doc_id = up_res.json()["documentId"]

    # Try verifying before processing
    verif_res = client.post(
        f"/api/v1/documents/{doc_id}/verify",
        headers=applicant["headers"],
    )
    assert verif_res.status_code == 400
    assert "must complete OCR processing" in verif_res.json()["detail"]


def test_api_cross_applicant_denial_and_privacy():
    client = TestClient(app)
    applicant1 = register_applicant(client, "app1@example.com", "Applicant One")
    applicant2 = register_applicant(client, "app2@example.com", "Applicant Two")

    pdf_bytes = create_synthetic_pdf(["Applicant One Marksheet", "Percentage: 90%"])
    up_res = client.post(
        "/api/v1/documents/upload",
        headers=applicant1["headers"],
        files={"file": ("10th.pdf", pdf_bytes, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    doc_id = up_res.json()["documentId"]

    # Process by owner
    client.post(f"/api/v1/documents/{doc_id}/process", headers=applicant1["headers"])

    # Applicant 2 cannot verify or read verification details of Applicant 1
    verify_denied = client.post(
        f"/api/v1/documents/{doc_id}/verify",
        headers=applicant2["headers"],
    )
    assert verify_denied.status_code == 403

    get_denied = client.get(
        f"/api/v1/documents/{doc_id}/verification",
        headers=applicant2["headers"],
    )
    assert get_denied.status_code == 403

    # Generic listing does not leak verification PII
    list_res = client.get("/api/v1/documents", headers=applicant1["headers"])
    assert list_res.status_code == 200
    for item in list_res.json():
        assert "validationResult" not in item
        assert "processingResult" not in item
        assert "authoritativeVerification" not in item


# ==============================================================================
# 9. Increment 14 Correction Pass: Specific Regression Tests
# ==============================================================================

def test_user_vs_application_name_conflict_forces_manual_review():
    """
    Area 2: If the extracted document matches the canonical Application record,
    but the User account name conflicts with the Application record,
    the final validation result must be MANUAL_REVIEW, never VALIDATED.
    """
    doc = {
        "documentId": "doc-test-uconflict-name",
        "documentType": "10TH_MARKSHEET",
        "processingResult": {
            "fields": {
                "candidateName": {"normalizedValue": "Hemanth M.P.", "confidence": 0.95},
                "percentage": {"normalizedValue": 86.5, "confidence": 0.95},
            }
        },
    }
    app_data = {
        "fullName": "Hemanth M.P.",
        "dob": "2000-05-15",
        "tenthPercentage": 86.5,
    }
    user_with_conflicting_name = {
        "fullName": "Completely Different Person",
        "dob": "2000-05-15",
    }
    result = validate_document_content(None, doc, app_data, user_with_conflicting_name)
    assert result.validationStatus == "MANUAL_REVIEW"
    assert result.validationStatus != "VALIDATED"
    assert "userApplicationNameConsistency" in result.fieldResults
    assert result.fieldResults["userApplicationNameConsistency"].status == "MANUAL_REVIEW"
    assert any("differ" in r.lower() or "conflict" in r.lower() for r in result.reasons)


def test_user_vs_application_dob_conflict_forces_manual_review():
    """
    Area 2: If the extracted document matches the canonical Application record,
    but the User account DOB conflicts with the Application record,
    the final validation result must be MANUAL_REVIEW, never VALIDATED.
    """
    doc = {
        "documentId": "doc-test-uconflict-dob",
        "documentType": "10TH_MARKSHEET",
        "processingResult": {
            "fields": {
                "candidateName": {"normalizedValue": "Hemanth M.P.", "confidence": 0.95},
                "percentage": {"normalizedValue": 86.5, "confidence": 0.95},
                "dob": {"rawValue": "15/05/2000", "confidence": 0.95},
            }
        },
    }
    app_data = {
        "fullName": "Hemanth M.P.",
        "dob": "2000-05-15",
        "tenthPercentage": 86.5,
    }
    user_with_conflicting_dob = {
        "fullName": "Hemanth M.P.",
        "dob": "1995-01-01",
    }
    result = validate_document_content(None, doc, app_data, user_with_conflicting_dob)
    assert result.validationStatus == "MANUAL_REVIEW"
    assert result.validationStatus != "VALIDATED"
    assert "userApplicationDobConsistency" in result.fieldResults
    assert result.fieldResults["userApplicationDobConsistency"].status == "MANUAL_REVIEW"


def test_course_degree_level_and_qualification_distinctions():
    """
    Area 3: Different degree levels with a shared subject must not match.
    Subject similarity alone must never establish degree equivalence.
    """
    # 1. B.Sc. Computer Science vs M.Sc. Computer Science must MISMATCH despite shared subject
    status, msg = compare_course("B.Sc. Computer Science", "M.Sc. Computer Science")
    assert status == "MISMATCH"
    assert "level" in msg.lower() or "mismatch" in msg.lower()

    # 2. BCA vs B.Sc. Computer Science must MISMATCH
    status, msg = compare_course("BCA", "B.Sc. Computer Science")
    assert status == "MISMATCH"

    # 3. B.Tech vs BCA must MISMATCH
    status, msg = compare_course("B.Tech", "BCA")
    assert status == "MISMATCH"

    # 4. Recognized exact aliases: Bachelor of Computer Applications vs BCA matches
    status, msg = compare_course("Bachelor of Computer Applications", "BCA")
    assert status == "MATCH"

    status, msg = compare_course("B.C.A.", "Bachelor of Computer Applications")
    assert status == "MATCH"

    # 5. Non-overlapping or unknown qualifications require MANUAL_REVIEW
    status, msg = compare_course("Bachelor of Fine Arts", "BCA")
    assert status in ("MISMATCH", "MANUAL_REVIEW")


def test_board_regional_and_alias_comparisons():
    """
    Area 4: Distinct regional boards do not match on a generic shared alias.
    """
    # 1. CBSE and unambiguous official name match
    status, msg = compare_board("Central Board of Secondary Education", "CBSE")
    assert status == "MATCH"

    # 2. ICSE and unambiguous official name match
    status, msg = compare_board("Indian Certificate of Secondary Education", "ICSE")
    assert status == "MATCH"

    # 3. Tamil Nadu State Board vs Maharashtra State Board must MISMATCH
    status, msg = compare_board("Tamil Nadu State Board", "Maharashtra State Board")
    assert status == "MISMATCH"
    assert "region" in msg.lower() or "mismatch" in msg.lower()

    # 4. Generic State Board vs specific regional board must return MANUAL_REVIEW
    status, msg = compare_board("State Board", "Tamil Nadu State Board")
    assert status == "MANUAL_REVIEW"
    assert "generic" in msg.lower() or "manual review" in msg.lower()

    status, msg = compare_board("Karnataka State Board", "State Board")
    assert status == "MANUAL_REVIEW"

    # 5. National board vs regional board must MISMATCH
    status, msg = compare_board("CBSE", "Tamil Nadu State Board")
    assert status == "MISMATCH"


def test_authoritative_simulation_candidate_identity_matching():
    """
    Area 5: Synthetic authoritative verification candidate identity and compatibility checks.
    """
    provider = SyntheticAuthoritativeVerificationProvider()

    # 1. Registered identifier + matching candidate identity -> SIMULATED_MATCH
    fields_match = {
        "registrationNumber": {"normalizedValue": "SYNTH-REG-2022-001", "confidence": 0.95},
        "candidateName": {"normalizedValue": "Hemanth M.P.", "confidence": 0.95},
        "dob": {"normalizedValue": "2000-05-15", "confidence": 0.95},
    }
    rec_match = provider.verify_document_credential("UG_MARKSHEET", fields_match, candidate_name="Hemanth M.P.")
    assert rec_match.status == "SIMULATED_MATCH"
    assert rec_match.isSimulated is True

    # 2. Registered identifier + conflicting candidate identity -> SIMULATED_MISMATCH
    fields_conflicting_name = {
        "registrationNumber": {"normalizedValue": "SYNTH-REG-2022-001"},
        "candidateName": {"normalizedValue": "Completely Wrong Name"},
    }
    rec_mismatch_name = provider.verify_document_credential("UG_MARKSHEET", fields_conflicting_name, candidate_name="Completely Wrong Name")
    assert rec_mismatch_name.status == "SIMULATED_MISMATCH"

    # 3. Registered identifier + conflicting DOB -> SIMULATED_MISMATCH
    fields_conflicting_dob = {
        "registrationNumber": {"normalizedValue": "SYNTH-REG-2022-001"},
        "candidateName": {"normalizedValue": "Hemanth M.P."},
        "dob": {"rawValue": "01/01/1990"},
    }
    rec_mismatch_dob = provider.verify_document_credential("UG_MARKSHEET", fields_conflicting_dob, candidate_name="Hemanth M.P.")
    assert rec_mismatch_dob.status == "SIMULATED_MISMATCH"

    # 4. Unknown identifier -> SIMULATED_NOT_FOUND
    fields_unknown = {
        "registrationNumber": {"normalizedValue": "UNKNOWN-NONEXISTENT-ID"},
        "candidateName": {"normalizedValue": "Hemanth M.P."},
    }
    rec_not_found = provider.verify_document_credential("UG_MARKSHEET", fields_unknown, candidate_name="Hemanth M.P.")
    assert rec_not_found.status == "SIMULATED_NOT_FOUND"

    # 5. Missing identifier -> SIMULATION_UNAVAILABLE
    rec_no_id = provider.verify_document_credential("UG_MARKSHEET", {})
    assert rec_no_id.status == "SIMULATION_UNAVAILABLE"

    # 6. Provider fault simulation -> SIMULATION_UNAVAILABLE
    provider_fault = SyntheticAuthoritativeVerificationProvider(simulate_provider_fault=True)
    rec_fault = provider_fault.verify_document_credential("UG_MARKSHEET", fields_match)
    assert rec_fault.status == "SIMULATION_UNAVAILABLE"

    # 7. Incompatible document type -> SIMULATION_UNAVAILABLE
    fields_incompat = {
        "registrationNumber": {"normalizedValue": "SYNTH-10TH-12345"},
        "candidateName": {"normalizedValue": "Hemanth M.P."},
    }
    rec_incompat = provider.verify_document_credential("DEGREE_CERTIFICATE", fields_incompat, candidate_name="Hemanth M.P.")
    assert rec_incompat.status == "SIMULATION_UNAVAILABLE"
    assert "incompatible" in rec_incompat.message.lower()


def test_automatic_validation_persists_lifecycle_status_directly_in_db():
    """
    Area 6: Successful automatic validation triggered by document processing
    persists lifecycle status directly into MongoDB.
    """
    client = TestClient(app)
    applicant = register_applicant(client, "auto_persist@example.com", "Hemanth M.P.", "2000-05-15")

    pdf_bytes = create_synthetic_pdf([
        "SECONDARY SCHOOL EXAMINATION",
        "Candidate's Name: Hemanth M.P.",
        "Roll No: 1234567",
        "Date of Birth: 15/05/2000",
        "Total Marks: 432 / 500",
        "Percentage: 86.5%",
    ])

    # 1. Upload
    up_res = client.post(
        "/api/v1/documents/upload",
        headers=applicant["headers"],
        files={"file": ("10th.pdf", pdf_bytes, "application/pdf")},
        data={"documentType": "10TH_MARKSHEET"},
    )
    assert up_res.status_code == 201
    doc_id = up_res.json()["documentId"]

    # 2. Process (triggers OCR and automatic validation synchronously)
    proc_res = client.post(
        f"/api/v1/documents/{doc_id}/process",
        headers=applicant["headers"],
    )
    assert proc_res.status_code == 200

    # 3. DIRECT MONGODB INSPECTION immediately after processing (WITHOUT calling /verify)
    db = get_db()
    stored_doc = db["documents"].find_one({"documentId": doc_id})
    assert stored_doc is not None
    assert stored_doc["status"] == "VALIDATED"
    assert stored_doc["validationStatus"] == "VALIDATED"
    assert stored_doc["validationResult"] is not None
    assert stored_doc["processingStatus"] == "COMPLETED"
    assert stored_doc["processingResult"] is not None


def test_low_confidence_prevents_decisive_false_mismatches():
    """
    Area 7: Low-confidence OCR does not create a decisive false mismatch.
    """
    # 1. Name apparent mismatch with low OCR confidence (0.65) must become MANUAL_REVIEW, not MISMATCH
    doc_low_conf = {
        "documentId": "doc-low-conf-name",
        "documentType": "10TH_MARKSHEET",
        "processingResult": {
            "fields": {
                "candidateName": {"normalizedValue": "Priya Singh", "confidence": 0.65},
                "percentage": {"normalizedValue": 86.5, "confidence": 0.90},
            }
        },
    }
    app_data = {"fullName": "Hemanth M.P.", "tenthPercentage": 86.5}
    res = validate_document_content(None, doc_low_conf, app_data, None)
    # Name status must be MANUAL_REVIEW, not MISMATCH!
    assert res.fieldResults["candidateName"].status == "MANUAL_REVIEW"
    assert res.validationStatus == "MANUAL_REVIEW"
    assert res.validationStatus != "MISMATCH"

    # 2. DOB apparent mismatch with low OCR confidence (0.60) must become MANUAL_REVIEW
    doc_low_conf_dob = {
        "documentId": "doc-low-conf-dob",
        "documentType": "10TH_MARKSHEET",
        "processingResult": {
            "fields": {
                "candidateName": {"normalizedValue": "Hemanth M.P.", "confidence": 0.90},
                "percentage": {"normalizedValue": 86.5, "confidence": 0.90},
                "dob": {"rawValue": "01/01/1990", "confidence": 0.60},
            }
        },
    }
    res_dob = validate_document_content(None, doc_low_conf_dob, app_data, None)
    assert res_dob.fieldResults["dob"].status == "MANUAL_REVIEW"
    assert res_dob.validationStatus != "MISMATCH"

    # 3. Academic board and course with low confidence (<0.80) downgrade to MANUAL_REVIEW
    status, msg = compare_board("Tamil Nadu State Board", "Maharashtra State Board", confidence=0.70)
    assert status == "MANUAL_REVIEW"

    status, msg = compare_course("B.Tech", "BCA", confidence=0.75)
    assert status == "MANUAL_REVIEW"


def test_validation_execution_failure_persists_error_and_preserves_ocr(monkeypatch):
    """
    Regression Test 1: Content validation execution failure in process_document().
    Deliberately causes automatic content validation to raise an exception after
    successful OCR results have been persisted.
    Verifies stored MongoDB document immediately afterward:
    - validationStatus is ERROR.
    - Lifecycle status is MANUAL_REVIEW.
    - The original successful processingResult is unchanged.
    - processingStatus remains COMPLETED.
    - The OCR processing confidence and other existing OCR data remain intact.
    """
    client = TestClient(app)
    applicant = register_applicant(client, "val_failure@example.com", "Hemanth M.P.", "2000-05-15")

    pdf_bytes = create_synthetic_pdf([
        "SECONDARY SCHOOL EXAMINATION",
        "Candidate's Name: Hemanth M.P.",
        "Roll No: 1234567",
        "Date of Birth: 15/05/2000",
        "Total Marks: 432 / 500",
        "Percentage: 86.5%",
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

    # 2. Monkeypatch validate_document_content in app.services.document to raise an unexpected runtime error
    def mock_val_crash(*args, **kwargs):
        raise RuntimeError("Simulated content-validation execution crash")

    monkeypatch.setattr("app.services.document.validate_document_content", mock_val_crash)

    # 3. Process document (runs OCR successfully, persists OCR, then triggers validation which crashes)
    proc_res = client.post(
        f"/api/v1/documents/{doc_id}/process",
        headers=applicant["headers"],
    )
    assert proc_res.status_code == 200
    proc_json = proc_res.json()
    assert proc_json["processingState"] == "COMPLETED"
    assert proc_json["overallConfidence"] >= 0.70

    # 4. Directly inspect stored MongoDB document immediately afterward (without calling /verify)
    db = get_db()
    stored_doc = db["documents"].find_one({"documentId": doc_id})
    assert stored_doc is not None

    # Verification requirements:
    # - validationStatus is ERROR
    assert stored_doc["validationStatus"] == "ERROR"
    # - Lifecycle status is MANUAL_REVIEW
    assert stored_doc["status"] == "MANUAL_REVIEW"
    # - processingStatus remains COMPLETED
    assert stored_doc["processingStatus"] == "COMPLETED"
    # - The original successful processingResult is unchanged and matches OCR output
    assert stored_doc["processingResult"] is not None
    assert stored_doc["processingResult"]["processingState"] == "COMPLETED"
    assert stored_doc["processingResult"]["textExtracted"] is True
    assert stored_doc["processingResult"]["fields"]["candidateName"]["normalizedValue"] == "Hemanth M.P."
    assert stored_doc["processingResult"]["fields"]["percentage"]["normalizedValue"] == 86.5
    # - The OCR processing confidence and other existing OCR data remain intact
    assert stored_doc["processingConfidence"] is not None
    assert stored_doc["processingConfidence"] == proc_json["overallConfidence"]
    assert stored_doc["documentType"] == "10TH_MARKSHEET"
    # - validationResult records the error details safely
    assert stored_doc["validationResult"] is not None
    assert stored_doc["validationResult"]["validationStatus"] == "ERROR"
    assert "errorSummary" in stored_doc["validationResult"]


def test_cross_document_low_confidence_apparent_mismatch_becomes_manual_review():
    """
    Regression Test 4a: Cross-document confidence threshold (0.80).
    A low-confidence apparent cross-document mismatch becomes MANUAL_REVIEW,
    rather than a decisive mismatch based solely on uncertain OCR.
    """
    # Case 1: UG_MARKSHEET vs DEGREE_CERTIFICATE registration numbers differ,
    # but UG_MARKSHEET registration number has confidence 0.65 (< 0.80).
    current_doc = {
        "documentId": "ug-marksheet-doc",
        "documentType": "UG_MARKSHEET",
        "processingResult": {
            "processingState": "COMPLETED",
            "fields": {
                "candidateName": {"normalizedValue": "Hemanth M.P.", "confidence": 0.95},
                "registrationNumber": {"normalizedValue": "2022MCA041", "confidence": 0.65},
                "cgpa": {"normalizedValue": 8.45, "confidence": 0.95},
                "institution": {"normalizedValue": "B.S. Abdur Rahman Crescent Institute", "confidence": 0.95},
                "passingYear": {"normalizedValue": 2022, "confidence": 0.95},
            },
        },
    }
    sibling_doc = {
        "documentId": "degree-cert-doc",
        "documentType": "DEGREE_CERTIFICATE",
        "processingStatus": "COMPLETED",
        "processingResult": {
            "fields": {
                "candidateName": {"normalizedValue": "Hemanth M.P.", "confidence": 0.95},
                "registrationNumber": {"normalizedValue": "2022MCA099", "confidence": 0.92},
                "degree": {"normalizedValue": "BCA", "confidence": 0.95},
                "institution": {"normalizedValue": "B.S. Abdur Rahman Crescent Institute", "confidence": 0.95},
                "passingYear": {"normalizedValue": 2022, "confidence": 0.95},
            },
        },
    }
    canonical_app = {
        "fullName": "Hemanth M.P.",
        "dob": "2000-05-15",
        "ugDegree": "BCA",
        "university": "B.S. Abdur Rahman Crescent Institute",
        "graduationYear": 2022,
        "cgpa": 8.45,
    }

    # Exercise actual verification engine with cross-document path
    val_res = validate_document_content(
        db=None,
        document=current_doc,
        application=canonical_app,
        user=None,
        sibling_documents=[sibling_doc],
    )

    # Locate the cross-document registration number check
    reg_checks = [c for c in val_res.crossDocumentResults if "Registration Number Consistency" in c.checkName]
    assert len(reg_checks) == 1
    assert reg_checks[0].status == "MANUAL_REVIEW"
    assert reg_checks[0].status != "MISMATCH"
    assert "below 0.80 threshold" in reg_checks[0].message

    # Overall validationStatus must be MANUAL_REVIEW, NOT MISMATCH
    assert val_res.validationStatus == "MANUAL_REVIEW"
    assert val_res.validationStatus != "MISMATCH"

    # Case 2: Cross-document candidate name consistency between 10TH_MARKSHEET and GOVERNMENT_ID
    # Apparent name difference but one document has confidence 0.72 (< 0.80)
    doc_10th = {
        "documentId": "doc-10th-name",
        "documentType": "10TH_MARKSHEET",
        "processingResult": {
            "processingState": "COMPLETED",
            "fields": {
                "candidateName": {"normalizedValue": "Hemanth M.P.", "confidence": 0.72},
                "percentage": {"normalizedValue": 86.5, "confidence": 0.92},
            },
        },
    }
    doc_govt = {
        "documentId": "doc-govt-name",
        "documentType": "GOVERNMENT_ID",
        "processingStatus": "COMPLETED",
        "processingResult": {
            "fields": {
                "candidateName": {"normalizedValue": "Hemant Kumar", "confidence": 0.95},
            },
        },
    }
    cross_checks = run_cross_document_checks(None, doc_10th, [doc_govt])
    name_checks = [c for c in cross_checks if "Name Consistency" in c.checkName]
    assert len(name_checks) == 1
    assert name_checks[0].status == "MANUAL_REVIEW"
    assert name_checks[0].status != "MISMATCH"


def test_reliable_hard_conflict_remains_decisive_when_different_field_has_low_confidence():
    """
    Regression Test 4b: A sufficiently reliable, genuinely conflicting field remains
    decisive when a different field has low confidence.
    Low-confidence fields downgrade individual items to MANUAL_REVIEW, but DO NOT
    suppress or override a genuine, reliable MISMATCH on another field.
    """
    # Document with:
    # - percentage: 55.0% with high confidence (0.95) -> Genuine hard conflict with application's 86.5%
    # - dob: confidence 0.60 (< 0.80) -> Evaluates to MANUAL_REVIEW due to low confidence
    # - candidateName: matching with 0.95 confidence
    doc_mixed = {
        "documentId": "doc-mixed-conflicts",
        "documentType": "10TH_MARKSHEET",
        "processingResult": {
            "processingState": "COMPLETED",
            "fields": {
                "candidateName": {"normalizedValue": "Hemanth M.P.", "confidence": 0.95},
                "dob": {"rawValue": "15/05/2000", "confidence": 0.60},
                "percentage": {"normalizedValue": 55.0, "confidence": 0.95},
            },
        },
    }
    canonical_app = {
        "fullName": "Hemanth M.P.",
        "dob": "2000-05-15",
        "tenthBoard": "CBSE",
        "tenthPercentage": 86.5,
    }

    val_res = validate_document_content(
        db=None,
        document=doc_mixed,
        application=canonical_app,
        user=None,
        sibling_documents=[],
    )

    # Percentage field is a hard conflict
    assert val_res.fieldResults["percentage"].status == "MISMATCH"
    # DOB field has low confidence and is MANUAL_REVIEW
    assert val_res.fieldResults["dob"].status == "MANUAL_REVIEW"
    # Decisive overall status MUST remain MISMATCH (not masked by the MANUAL_REVIEW item)
    assert val_res.validationStatus == "MISMATCH"


def test_missing_confidence_handled_conservatively_as_zero():
    """
    Regression Test 4c: Missing confidence is handled conservatively according
    to the actual extracted-field contract (defaults to 0.0 < 0.80).
    """
    # 1. Field with completely missing 'confidence' key
    field_no_conf = {"normalizedValue": "CBSE"}
    from app.services.verification.engine import get_field_confidence
    assert get_field_confidence(field_no_conf) == 0.0

    # 2. Field with confidence: None
    field_none_conf = {"normalizedValue": "CBSE", "confidence": None}
    assert get_field_confidence(field_none_conf) == 0.0

    # 3. Field with invalid non-numeric confidence
    field_invalid_conf = {"normalizedValue": "CBSE", "confidence": "unknown"}
    assert get_field_confidence(field_invalid_conf) == 0.0

    # 4. Sibling cross-document check with missing confidence treats min_conf as 0.0 (< 0.80)
    from app.services.verification.cross_document import get_field_conf
    assert get_field_conf(None) == 0.0
    assert get_field_conf({}) == 0.0
    assert get_field_conf({"normalizedValue": "123"}) == 0.0
    assert get_field_conf({"confidence": None}) == 0.0

    # Apparent mismatch in cross-document passing year with missing confidence
    doc_a = {
        "documentType": "UG_MARKSHEET",
        "processingResult": {
            "fields": {
                "passingYear": {"normalizedValue": 2021},  # No confidence key
            }
        }
    }
    doc_b = {
        "documentType": "DEGREE_CERTIFICATE",
        "processingStatus": "COMPLETED",
        "processingResult": {
            "fields": {
                "passingYear": {"normalizedValue": 2022, "confidence": 0.95},
            }
        }
    }
    cross_res = run_cross_document_checks(None, doc_a, [doc_b])
    yr_checks = [c for c in cross_res if "Passing Year" in c.checkName]
    assert len(yr_checks) == 1
    # Because doc_a had missing confidence (0.0 < 0.80), passing year comparison
    # is downgraded to MANUAL_REVIEW, never false decisive MISMATCH
    assert yr_checks[0].status == "MANUAL_REVIEW"


def test_low_confidence_apparent_matches_are_not_automatically_accepted():
    """
    Regression Test: Proves that low-confidence (<0.80) apparent matches are NOT
    automatically accepted as MATCH or VALIDATED.
    Exercises the actual validate_document_content() engine path for:
    1. Candidate name matches Application name, but confidence is low (<0.80).
    2. DOB matches Application DOB, but confidence is low (<0.80).
    3. Academic fields (percentage, CGPA, board, course) match Application, but confidence is low (<0.80).
    For each case, asserts the relevant field result is MANUAL_REVIEW (not MATCH),
    and the overall validation result is MANUAL_REVIEW (not VALIDATED).
    Ensures all unrelated mandatory fields are fully satisfied so missing fields
    do not obscure the assertion.
    """
    # 1. Candidate name matches Application fullName, but OCR confidence is low (0.75 < 0.80)
    doc_name_match_low_conf = {
        "documentId": "doc-name-match-low-conf",
        "documentType": "10TH_MARKSHEET",
        "processingResult": {
            "processingState": "COMPLETED",
            "fields": {
                "candidateName": {"normalizedValue": "Hemanth M.P.", "confidence": 0.75},
                "percentage": {"normalizedValue": 86.5, "confidence": 0.95},
            },
        },
    }
    app_data = {
        "fullName": "Hemanth M.P.",
        "dob": "2000-05-15",
        "tenthPercentage": 86.5,
        "tenthBoard": "CBSE",
    }
    res_name = validate_document_content(None, doc_name_match_low_conf, app_data, None)
    # The candidateName field must NOT be automatically accepted as MATCH!
    assert res_name.fieldResults["candidateName"].status == "MANUAL_REVIEW"
    assert res_name.fieldResults["candidateName"].status != "MATCH"
    assert "below 0.80 threshold" in res_name.fieldResults["candidateName"].message
    # High-confidence percentage is MATCH
    assert res_name.fieldResults["percentage"].status == "MATCH"
    # Mandatory fields are complete
    assert res_name.missingMandatoryFields == []
    # Overall validation must be MANUAL_REVIEW, not VALIDATED
    assert res_name.validationStatus == "MANUAL_REVIEW"
    assert res_name.validationStatus != "VALIDATED"

    # 2. DOB matches Application dob, but OCR confidence is low (0.70 < 0.80)
    doc_dob_match_low_conf = {
        "documentId": "doc-dob-match-low-conf",
        "documentType": "10TH_MARKSHEET",
        "processingResult": {
            "processingState": "COMPLETED",
            "fields": {
                "candidateName": {"normalizedValue": "Hemanth M.P.", "confidence": 0.95},
                "dob": {"rawValue": "15/05/2000", "confidence": 0.70},
                "percentage": {"normalizedValue": 86.5, "confidence": 0.95},
            },
        },
    }
    res_dob = validate_document_content(None, doc_dob_match_low_conf, app_data, None)
    # The dob field must NOT be automatically accepted as MATCH!
    assert res_dob.fieldResults["dob"].status == "MANUAL_REVIEW"
    assert res_dob.fieldResults["dob"].status != "MATCH"
    assert "below 0.80 threshold" in res_dob.fieldResults["dob"].message
    # Other fields are MATCH
    assert res_dob.fieldResults["candidateName"].status == "MATCH"
    assert res_dob.fieldResults["percentage"].status == "MATCH"
    assert res_dob.missingMandatoryFields == []
    # Overall validation must be MANUAL_REVIEW, not VALIDATED
    assert res_dob.validationStatus == "MANUAL_REVIEW"
    assert res_dob.validationStatus != "VALIDATED"

    # 3a. Academic field (percentage) matches Application tenthPercentage, but confidence is low (0.72 < 0.80)
    doc_pct_match_low_conf = {
        "documentId": "doc-pct-match-low-conf",
        "documentType": "10TH_MARKSHEET",
        "processingResult": {
            "processingState": "COMPLETED",
            "fields": {
                "candidateName": {"normalizedValue": "Hemanth M.P.", "confidence": 0.95},
                "percentage": {"normalizedValue": 86.5, "confidence": 0.72},
            },
        },
    }
    res_pct = validate_document_content(None, doc_pct_match_low_conf, app_data, None)
    # Percentage field must NOT be automatically accepted as MATCH!
    assert res_pct.fieldResults["percentage"].status == "MANUAL_REVIEW"
    assert res_pct.fieldResults["percentage"].status != "MATCH"
    assert "below decisive threshold 0.8" in res_pct.fieldResults["percentage"].message
    assert res_pct.fieldResults["candidateName"].status == "MATCH"
    assert res_pct.missingMandatoryFields == []
    assert res_pct.validationStatus == "MANUAL_REVIEW"
    assert res_pct.validationStatus != "VALIDATED"

    # 3b. Academic field (CGPA) matches Application cgpa in UG_MARKSHEET, but confidence is low (0.65 < 0.80)
    ug_app_data = {
        "fullName": "Hemanth M.P.",
        "cgpa": 8.45,
        "ugDegree": "BCA",
        "university": "B.S. Abdur Rahman Crescent Institute",
        "graduationYear": 2022,
    }
    doc_cgpa_match_low_conf = {
        "documentId": "doc-cgpa-match-low-conf",
        "documentType": "UG_MARKSHEET",
        "processingResult": {
            "processingState": "COMPLETED",
            "fields": {
                "candidateName": {"normalizedValue": "Hemanth M.P.", "confidence": 0.95},
                "cgpa": {"normalizedValue": 8.45, "confidence": 0.65},
                "course": {"normalizedValue": "BCA", "confidence": 0.95},
                "institution": {"normalizedValue": "B.S. Abdur Rahman Crescent Institute", "confidence": 0.95},
                "passingYear": {"normalizedValue": 2022, "confidence": 0.95},
            },
        },
    }
    res_cgpa = validate_document_content(None, doc_cgpa_match_low_conf, ug_app_data, None)
    # CGPA field must NOT be automatically accepted as MATCH!
    assert res_cgpa.fieldResults["cgpa"].status == "MANUAL_REVIEW"
    assert res_cgpa.fieldResults["cgpa"].status != "MATCH"
    assert "below decisive threshold 0.8" in res_cgpa.fieldResults["cgpa"].message
    assert res_cgpa.fieldResults["candidateName"].status == "MATCH"
    assert res_cgpa.missingMandatoryFields == []
    assert res_cgpa.validationStatus == "MANUAL_REVIEW"
    assert res_cgpa.validationStatus != "VALIDATED"

    # 3c. Academic field (board / course) apparent matches with low confidence (<0.80)
    doc_board_match_low_conf = {
        "documentId": "doc-board-match-low-conf",
        "documentType": "10TH_MARKSHEET",
        "processingResult": {
            "processingState": "COMPLETED",
            "fields": {
                "candidateName": {"normalizedValue": "Hemanth M.P.", "confidence": 0.95},
                "percentage": {"normalizedValue": 86.5, "confidence": 0.95},
                "institution": {"normalizedValue": "CBSE", "confidence": 0.68},
            },
        },
    }
    res_board = validate_document_content(None, doc_board_match_low_conf, app_data, None)
    assert res_board.fieldResults["board"].status == "MANUAL_REVIEW"
    assert res_board.fieldResults["board"].status != "MATCH"
    assert "below decisive threshold 0.8" in res_board.fieldResults["board"].message
    assert res_board.validationStatus == "MANUAL_REVIEW"

    doc_course_match_low_conf = {
        "documentId": "doc-course-match-low-conf",
        "documentType": "UG_MARKSHEET",
        "processingResult": {
            "processingState": "COMPLETED",
            "fields": {
                "candidateName": {"normalizedValue": "Hemanth M.P.", "confidence": 0.95},
                "cgpa": {"normalizedValue": 8.45, "confidence": 0.95},
                "course": {"normalizedValue": "BCA", "confidence": 0.70},
            },
        },
    }
    res_course = validate_document_content(None, doc_course_match_low_conf, ug_app_data, None)
    assert res_course.fieldResults["course"].status == "MANUAL_REVIEW"
    assert res_course.fieldResults["course"].status != "MATCH"
    assert "below decisive threshold 0.8" in res_course.fieldResults["course"].message
    assert res_course.validationStatus == "MANUAL_REVIEW"
