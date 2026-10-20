import io
from fastapi.testclient import TestClient
from PIL import Image
import pymupdf
import pytest

from app.agents.tools import (
    CANONICAL_PROGRAMME_RULES,
    REQUIRED_DOCUMENT_TYPES,
    TOOL_REGISTRY,
    execute_tool,
    list_agent_activity,
    tool_check_document_completeness,
    tool_check_eligibility,
    tool_compare_applicant_details,
    tool_create_exception,
    tool_extract_document_data,
    tool_get_application,
    tool_get_program_requirements,
    tool_process_document,
    tool_record_audit_event,
    tool_request_missing_document,
    tool_send_notification,
    tool_update_application_status,
    tool_verify_document,
)
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.schemas.agent import ToolName, ToolStatus, WorkflowStage


def create_sample_pdf_bytes(text_lines: list[str]) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 50
    for line in text_lines:
        page.insert_text((50, y), line, fontsize=12)
        y += 20
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.fixture
def api_client():
    return TestClient(app)


@pytest.fixture
def clean_db():
    db = get_db()
    assert settings.DATABASE_NAME == "smartenroll_test"
    db["users"].delete_many({})
    db["applications"].delete_many({})
    db["documents"].delete_many({})
    db["agent_activity"].delete_many({})
    yield db


@pytest.fixture
def applicant_auth(api_client, clean_db):
    reg = api_client.post(
        "/api/v1/auth/register",
        json={
            "fullName": "Hemanth M.P.",
            "email": "hemanth@example.com",
            "mobile": "9876543210",
            "dob": "2000-05-15",
            "password": "SecurePassword123!",
        },
    )
    assert reg.status_code == 201
    applicant_data = reg.json()
    token = applicant_data["token"]
    user_doc = clean_db["users"].find_one({"email": "hemanth@example.com"})

    app_res = api_client.post(
        "/api/v1/applications",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "programmeId": "mca",
            "fullName": "Hemanth M.P.",
            "dob": "2000-05-15",
            "gender": "Male",
            "nationality": "Indian",
            "email": "hemanth@example.com",
            "mobile": "9876543210",
            "address": "123 Crescent Road",
            "city": "Chennai",
            "state": "Tamil Nadu",
            "pinCode": "600048",
            "tenthBoard": "State Board",
            "tenthPercentage": "86.5",
            "twelfthBoard": "State Board",
            "twelfthPercentage": "88.0",
            "ugDegree": "BCA",
            "university": "B.S. Abdur Rahman Crescent Institute",
            "graduationYear": 2022,
            "cgpa": "8.5",
        },
    )
    assert app_res.status_code == 201
    application_data = app_res.json()

    return {
        "token": token,
        "user": user_doc,
        "application": application_data,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest.fixture
def admin_auth(api_client, clean_db):
    from app.core.security import get_password_hash

    admin_doc = {
        "full_name": "Admission Administrator",
        "email": "admin@smartenroll.edu",
        "hashed_password": get_password_hash("AdminSecurePassword123!"),
        "role": "admin",
        "applicant_id": None,
    }
    res = clean_db["users"].insert_one(admin_doc)
    admin_doc["_id"] = res.inserted_id

    login_res = api_client.post(
        "/api/v1/auth/login",
        json={
            "email": "admin@smartenroll.edu",
            "password": "AdminSecurePassword123!",
            "role": "admin",
        },
    )
    assert login_res.status_code == 200
    token = login_res.json()["token"]
    return {
        "token": token,
        "user": admin_doc,
        "headers": {"Authorization": f"Bearer {token}"},
    }


# =====================================================================
# Tests: Tool 1 - get_application
# =====================================================================
def test_tool_get_application_applicant_ownership_and_admin(applicant_auth, admin_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]

    # 1. Applicant retrieves own application
    res_applicant = tool_get_application(clean_db, applicant_auth["user"], app_id)
    assert res_applicant.status == ToolStatus.COMPLETED.value
    assert res_applicant.data["applicationId"] == app_id

    # 2. Admin retrieves application
    res_admin = tool_get_application(clean_db, admin_auth["user"], app_id)
    assert res_admin.status == ToolStatus.COMPLETED.value
    assert res_admin.data["applicationId"] == app_id

    # 3. Another applicant cannot retrieve it
    other_user = {"_id": "other_user_id", "role": "applicant", "applicant_id": "APL-9999"}
    res_forbidden = tool_get_application(clean_db, other_user, app_id)
    assert res_forbidden.status == ToolStatus.FAILED.value


# =====================================================================
# Tests: Tool 2 - get_program_requirements
# =====================================================================
def test_tool_get_program_requirements(clean_db, applicant_auth):
    # Valid programmes
    for pid in ["mca", "mba", "msc-cs", "mtech-cs"]:
        res = tool_get_program_requirements(clean_db, applicant_auth["user"], pid)
        assert res.status == ToolStatus.COMPLETED.value
        assert res.data["programmeId"] == pid
        assert "minimumPercentage" in res.data

    # Invalid programme
    res_invalid = tool_get_program_requirements(clean_db, applicant_auth["user"], "invalid-program")
    assert res_invalid.status == ToolStatus.FAILED.value
    assert "not found" in res_invalid.message


# =====================================================================
# Tests: Tool 3 - check_document_completeness
# =====================================================================
def test_tool_check_document_completeness(api_client, applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]

    # Initially 0 documents uploaded
    res_empty = tool_check_document_completeness(clean_db, applicant_auth["user"], app_id)
    assert res_empty.status == ToolStatus.COMPLETED.value
    assert res_empty.data["totalRequired"] == 6
    assert res_empty.data["totalSubmitted"] == 0
    assert res_empty.data["totalMissing"] == 6
    assert res_empty.data["isComplete"] is False

    # Upload 10th marksheet
    pdf_bytes = create_sample_pdf_bytes(["Secondary School Certificate", "Name: Hemanth M.P."])
    up_res = api_client.post(
        "/api/v1/documents/upload",
        headers=applicant_auth["headers"],
        data={"documentType": "10TH_MARKSHEET", "applicationId": app_id},
        files={"file": ("10th.pdf", pdf_bytes, "application/pdf")},
    )
    assert up_res.status_code == 201

    res_one = tool_check_document_completeness(clean_db, applicant_auth["user"], app_id)
    assert res_one.status == ToolStatus.COMPLETED.value
    assert res_one.data["totalSubmitted"] == 1
    assert res_one.data["totalMissing"] == 5
    assert "10TH_MARKSHEET" in res_one.data["submittedDocumentTypes"]
    assert res_one.data["isComplete"] is False


# =====================================================================
# Tests: Tool 4, 5, 6, 7 - Document OCR & Verification Wrappers
# =====================================================================
def test_tool_process_and_verify_document_wrappers(api_client, applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]
    pdf_bytes = create_sample_pdf_bytes([
        "Secondary School Certificate 10th Marksheet",
        "Candidate Name: Hemanth M.P.",
        "Date of Birth: 15/05/2000",
        "Roll No: 12345",
        "Marks: 432 / 500",
        "Percentage: 86.4%",
        "State Board of Secondary Education",
    ])

    up_res = api_client.post(
        "/api/v1/documents/upload",
        headers=applicant_auth["headers"],
        data={"documentType": "10TH_MARKSHEET", "applicationId": app_id},
        files={"file": ("10th_marksheet.pdf", pdf_bytes, "application/pdf")},
    )
    assert up_res.status_code == 201
    doc_id = up_res.json()["documentId"]

    # Tool 4: process_document
    res_proc = tool_process_document(clean_db, applicant_auth["user"], doc_id)
    assert res_proc.status == ToolStatus.COMPLETED.value
    assert res_proc.data["processingState"] == "COMPLETED"

    # Tool 5: extract_document_data
    res_extract = tool_extract_document_data(clean_db, applicant_auth["user"], doc_id)
    assert res_extract.status == ToolStatus.COMPLETED.value
    assert res_extract.data["fields"] is not None

    # Tool 6: verify_document
    res_verify = tool_verify_document(clean_db, applicant_auth["user"], doc_id)
    assert res_verify.status == ToolStatus.COMPLETED.value
    assert res_verify.data["validationStatus"] in ("VALIDATED", "MANUAL_REVIEW")

    # Tool 7: compare_applicant_details
    res_compare = tool_compare_applicant_details(clean_db, applicant_auth["user"], doc_id, app_id)
    assert res_compare.status == ToolStatus.COMPLETED.value
    assert "fieldResults" in res_compare.data


# =====================================================================
# Tests: Tools with Explicit Integration Dependencies (Increments 16-18)
# =====================================================================
def test_dependency_pending_tools_do_not_fabricate_results(applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]
    user = applicant_auth["user"]

    # Tool 8: check_eligibility -> depends on Increment 16
    res_elig = tool_check_eligibility(clean_db, user, app_id)
    assert res_elig.status == ToolStatus.DEPENDENCY_PENDING.value
    assert res_elig.dependency == "Increment 16: Eligibility Engine"
    assert "Increment 16" in res_elig.message

    # Tool 9: create_exception -> depends on Increment 17
    res_exc = tool_create_exception(clean_db, user, app_id, "MISSING_DOCUMENT", "Missing Transfer Certificate")
    assert res_exc.status == ToolStatus.DEPENDENCY_PENDING.value
    assert res_exc.dependency == "Increment 17: Exception Management"
    assert "Increment 17" in res_exc.message

    # Tool 10: request_missing_document -> depends on Increments 17 & 18
    res_req = tool_request_missing_document(clean_db, user, app_id, "TRANSFER_CERTIFICATE")
    assert res_req.status == ToolStatus.DEPENDENCY_PENDING.value
    assert "Increment 17" in res_req.dependency or "Increment 18" in res_req.dependency

    # Tool 12: send_notification -> depends on Increment 18
    res_notif = tool_send_notification(clean_db, user, str(user["_id"]), "Alert", "Test alert")
    assert res_notif.status == ToolStatus.DEPENDENCY_PENDING.value
    assert res_notif.dependency == "Increment 18: Notifications"


# =====================================================================
# Tests: Tool 11 - update_application_status
# =====================================================================
def test_tool_update_application_status(admin_auth, applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]

    # Initial state is DRAFT. Advance to SUBMITTED first, then to PROCESSING
    res_sub = tool_update_application_status(clean_db, admin_auth["user"], app_id, "SUBMITTED")
    assert res_sub.status == ToolStatus.COMPLETED.value
    assert res_sub.data["newStatus"] == "SUBMITTED"

    # Update to valid PROCESSING status
    res = tool_update_application_status(clean_db, admin_auth["user"], app_id, "PROCESSING")
    assert res.status == ToolStatus.COMPLETED.value
    assert res.data["newStatus"] == "PROCESSING"

    # Verify directly in MongoDB
    app_doc = clean_db["applications"].find_one({"applicationId": app_id})
    assert app_doc["status"] == "PROCESSING"

    # Reject invalid status
    res_invalid = tool_update_application_status(clean_db, admin_auth["user"], app_id, "NOT_A_REAL_STATUS")
    assert res_invalid.status == ToolStatus.FAILED.value
    assert "Invalid application status" in res_invalid.message


# =====================================================================
# Tests: Tool 13 - record_audit_event & Persistent Audit Logging
# =====================================================================
def test_tool_record_audit_event_and_querying(applicant_auth, admin_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]

    # Record 3 events
    ev1 = tool_record_audit_event(
        clean_db,
        admin_auth["user"],
        application_id=app_id,
        stage="OBSERVE",
        tool="get_application",
        action="Application received",
        result=f"Application {app_id} loaded",
        status="COMPLETED",
    )
    assert ev1.status == ToolStatus.COMPLETED.value
    assert ev1.data["id"].startswith("act-")

    tool_record_audit_event(
        clean_db,
        admin_auth["user"],
        application_id=app_id,
        stage="ACT",
        tool="check_document_completeness",
        action="Checked required documents",
        result="4 of 6 required documents present",
        status="COMPLETED",
    )

    tool_record_audit_event(
        clean_db,
        admin_auth["user"],
        application_id=app_id,
        stage="RE-PLAN",
        tool="request_missing_document",
        action="Missing document detected",
        result="Transfer Certificate requested",
        status="PENDING",
    )

    # 1. Admin lists all activity
    admin_logs = list_agent_activity(clean_db, admin_auth["user"])
    assert len(admin_logs) == 3

    # 2. Filter by stage
    act_logs = list_agent_activity(clean_db, admin_auth["user"], stage="ACT")
    assert len(act_logs) == 1
    assert act_logs[0]["tool"] == "check_document_completeness"

    # 3. Applicant lists their own activity
    applicant_logs = list_agent_activity(clean_db, applicant_auth["user"])
    assert len(applicant_logs) == 3

    # 4. Applicant cannot list activity for another application
    with pytest.raises(Exception):
        list_agent_activity(clean_db, applicant_auth["user"], application_id="SE99999999")


# =====================================================================
# Tests: Unified Tool Dispatcher execute_tool
# =====================================================================
def test_unified_tool_dispatcher(applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]

    # Success call through dispatcher
    res = execute_tool(
        tool_name="get_program_requirements",
        parameters={"programme_id": "mca"},
        current_user=applicant_auth["user"],
        db=clean_db,
    )
    assert res.status == ToolStatus.COMPLETED.value
    assert res.data["programmeId"] == "mca"

    # Unregistered tool call
    res_unreg = execute_tool(
        tool_name="non_existent_tool",
        parameters={},
        current_user=applicant_auth["user"],
        db=clean_db,
    )
    assert res_unreg.status == ToolStatus.FAILED.value
    assert "is not registered" in res_unreg.message

    # Parameter mismatch
    res_param_err = execute_tool(
        tool_name="get_program_requirements",
        parameters={"invalid_param": 123},
        current_user=applicant_auth["user"],
        db=clean_db,
    )
    assert res_param_err.status == ToolStatus.FAILED.value
    assert "Invalid parameters provided" in res_param_err.message


# =====================================================================
# Regression Tests (Task 15.1 Security Corrections)
# =====================================================================

# 1. Applicant attempts to update their own application status and is rejected.
def test_applicant_cannot_update_own_status(applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]
    initial_app = clean_db["applications"].find_one({"applicationId": app_id})
    assert initial_app["status"] == "DRAFT"

    res = tool_update_application_status(clean_db, applicant_auth["user"], app_id, "SUBMITTED")
    assert res.status == ToolStatus.FAILED.value
    assert "not permitted" in res.message.lower()

    # Database state must remain unchanged
    after_app = clean_db["applications"].find_one({"applicationId": app_id})
    assert after_app["status"] == "DRAFT"


# 2. Cross-applicant status modification is rejected.
def test_cross_applicant_status_modification_rejected(api_client, applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]

    # Register second applicant
    reg2 = api_client.post(
        "/api/v1/auth/register",
        json={
            "fullName": "Second Applicant",
            "email": "second@smartenroll.edu",
            "mobile": "9876543299",
            "dob": "2001-01-01",
            "password": "Password123!",
        },
    )
    assert reg2.status_code == 201
    second_user = clean_db["users"].find_one({"email": "second@smartenroll.edu"})

    # Second applicant attempts to modify first applicant's application status
    res = tool_update_application_status(clean_db, second_user, app_id, "SUBMITTED")
    assert res.status == ToolStatus.FAILED.value
    assert "not authorized" in res.message.lower() or "not permitted" in res.message.lower()

    # Database state must remain unchanged
    after_app = clean_db["applications"].find_one({"applicationId": app_id})
    assert after_app["status"] == "DRAFT"


# 3. Invalid state transitions are rejected without changing database state.
def test_invalid_state_transitions_rejected_without_db_change(admin_auth, applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]

    # DRAFT -> PROCESSING is an invalid forward jump
    res_jump = tool_update_application_status(clean_db, admin_auth["user"], app_id, "PROCESSING")
    assert res_jump.status == ToolStatus.FAILED.value
    assert "Invalid status transition" in res_jump.message
    assert clean_db["applications"].find_one({"applicationId": app_id})["status"] == "DRAFT"

    # Valid transition to SUBMITTED
    res_sub = tool_update_application_status(clean_db, admin_auth["user"], app_id, "SUBMITTED")
    assert res_sub.status == ToolStatus.COMPLETED.value
    assert clean_db["applications"].find_one({"applicationId": app_id})["status"] == "SUBMITTED"

    # SUBMITTED -> DRAFT is an invalid backward transition
    res_back = tool_update_application_status(clean_db, admin_auth["user"], app_id, "DRAFT")
    assert res_back.status == ToolStatus.FAILED.value
    assert "Invalid status transition" in res_back.message
    assert clean_db["applications"].find_one({"applicationId": app_id})["status"] == "SUBMITTED"


# 4. A direct transition from DRAFT or SUBMITTED to PROCESSING_COMPLETE is rejected.
def test_direct_transition_draft_or_submitted_to_processing_complete_rejected(admin_auth, applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]

    # In DRAFT state: direct jump to PROCESSING_COMPLETE rejected
    res_draft = tool_update_application_status(clean_db, admin_auth["user"], app_id, "PROCESSING_COMPLETE")
    assert res_draft.status == ToolStatus.FAILED.value
    assert "Invalid status transition" in res_draft.message
    assert clean_db["applications"].find_one({"applicationId": app_id})["status"] == "DRAFT"

    # Advance to SUBMITTED
    tool_update_application_status(clean_db, admin_auth["user"], app_id, "SUBMITTED")
    assert clean_db["applications"].find_one({"applicationId": app_id})["status"] == "SUBMITTED"

    # In SUBMITTED state: direct jump to PROCESSING_COMPLETE rejected
    res_sub = tool_update_application_status(clean_db, admin_auth["user"], app_id, "PROCESSING_COMPLETE")
    assert res_sub.status == ToolStatus.FAILED.value
    assert "Invalid status transition" in res_sub.message
    assert clean_db["applications"].find_one({"applicationId": app_id})["status"] == "SUBMITTED"


# 5. ELIGIBLE or INELIGIBLE cannot be set without an appropriate deterministic eligibility result.
def test_eligible_or_ineligible_requires_deterministic_result(admin_auth, applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]

    # Progress application to ELIGIBILITY_CHECK
    for stage in ["SUBMITTED", "PROCESSING", "VERIFICATION_IN_PROGRESS", "ELIGIBILITY_CHECK"]:
        res = tool_update_application_status(clean_db, admin_auth["user"], app_id, stage)
        assert res.status == ToolStatus.COMPLETED.value

    # Application is in ELIGIBILITY_CHECK with no deterministic eligibilityResult in MongoDB
    # 5a. Attempt transition to ELIGIBLE
    res_el = tool_update_application_status(clean_db, admin_auth["user"], app_id, "ELIGIBLE")
    assert res_el.status == ToolStatus.DEPENDENCY_PENDING.value
    assert res_el.dependency == "Increment 16: Eligibility Engine"
    assert "Increment 16" in res_el.message
    assert clean_db["applications"].find_one({"applicationId": app_id})["status"] == "ELIGIBILITY_CHECK"

    # 5b. Attempt transition to INELIGIBLE
    res_inel = tool_update_application_status(clean_db, admin_auth["user"], app_id, "INELIGIBLE")
    assert res_inel.status == ToolStatus.DEPENDENCY_PENDING.value
    assert res_inel.dependency == "Increment 16: Eligibility Engine"
    assert "Increment 16" in res_inel.message
    assert clean_db["applications"].find_one({"applicationId": app_id})["status"] == "ELIGIBILITY_CHECK"


# 6. PROCESSING_COMPLETE cannot be set without required workflow-completion evidence.
def test_processing_complete_requires_workflow_completion_evidence(admin_auth, applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]

    # Application in ELIGIBLE state without completion evidence
    clean_db["applications"].update_one(
        {"applicationId": app_id},
        {"$set": {"status": "ELIGIBLE"}, "$unset": {"eligibilityResult": "", "completionEvidence": ""}},
    )

    # 6a. Attempt transition to PROCESSING_COMPLETE without evidence -> rejected
    res_missing = tool_update_application_status(clean_db, admin_auth["user"], app_id, "PROCESSING_COMPLETE")
    assert res_missing.status == ToolStatus.FAILED.value
    assert "workflow-completion evidence is missing" in res_missing.message
    assert clean_db["applications"].find_one({"applicationId": app_id})["status"] == "ELIGIBLE"

    # 6b. Supply deterministic workflow completion evidence
    clean_db["applications"].update_one(
        {"applicationId": app_id},
        {"$set": {"eligibilityResult": {"status": "ELIGIBLE", "isFinal": True}}},
    )

    # 6c. Transition to PROCESSING_COMPLETE with evidence -> succeeds
    res_success = tool_update_application_status(clean_db, admin_auth["user"], app_id, "PROCESSING_COMPLETE")
    assert res_success.status == ToolStatus.COMPLETED.value
    assert clean_db["applications"].find_one({"applicationId": app_id})["status"] == "PROCESSING_COMPLETE"


# 7. The public POST /api/v1/agents/tools/execute route is no longer available.
def test_public_tool_execution_endpoint_not_available(api_client, admin_auth, applicant_auth):
    # Admin attempt
    res_admin = api_client.post(
        "/api/v1/agents/tools/execute",
        headers=admin_auth["headers"],
        json={"tool": "get_program_requirements", "parameters": {"programme_id": "mba"}},
    )
    assert res_admin.status_code in (404, 405)

    # Applicant attempt
    res_app = api_client.post(
        "/api/v1/agents/tools/execute",
        headers=applicant_auth["headers"],
        json={"tool": "get_program_requirements", "parameters": {"programme_id": "mba"}},
    )
    assert res_app.status_code in (404, 405)

    # Unauthenticated attempt
    res_unauth = api_client.post(
        "/api/v1/agents/tools/execute",
        json={"tool": "get_program_requirements", "parameters": {"programme_id": "mba"}},
    )
    assert res_unauth.status_code in (404, 405)


# 8. Unauthenticated access to /api/v1/admin/agent-activity returns HTTP 401.
def test_unauthenticated_agent_activity_returns_401(api_client):
    res_admin_alias = api_client.get("/api/v1/admin/agent-activity")
    assert res_admin_alias.status_code == 401

    res_activity = api_client.get("/api/v1/agents/activity")
    assert res_activity.status_code == 401

    res_app_activity = api_client.get("/api/v1/agents/activity/SE20260001")
    assert res_app_activity.status_code == 401


# 9. An unexpected dispatcher exception is logged internally but not disclosed in the returned error.
def test_unexpected_dispatcher_exception_sanitized(admin_auth, clean_db, monkeypatch):
    from app.agents import tools

    def mock_leaking_tool(*args, **kwargs):
        raise RuntimeError("FATAL: MongoDB auth failed on mongodb://admin:super_secret_pw@192.168.1.100:27017/smartenroll")

    monkeypatch.setitem(tools.TOOL_REGISTRY, "get_application", mock_leaking_tool)

    res = execute_tool(
        tool_name="get_application",
        parameters={"application_id": "SE20260001"},
        current_user=admin_auth["user"],
        db=clean_db,
    )
    assert res.status == ToolStatus.FAILED.value
    assert "super_secret_pw" not in res.message
    assert "192.168.1.100" not in res.message
    assert "mongodb://" not in res.message
    assert "FATAL" not in res.message
    assert "An unexpected internal error occurred" in res.message


# 10. Existing authorized audit-log queries continue to work.
def test_authorized_audit_log_queries(api_client, applicant_auth, admin_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]

    # Record sample audit events
    tool_record_audit_event(
        clean_db,
        admin_auth["user"],
        application_id=app_id,
        stage="OBSERVE",
        tool="get_application",
        action="Application loaded",
        result="Success",
        status="COMPLETED",
    )
    tool_record_audit_event(
        clean_db,
        admin_auth["user"],
        application_id=app_id,
        stage="ACT",
        tool="check_document_completeness",
        action="Checking documents",
        result="All 6 documents verified",
        status="COMPLETED",
    )

    # Admin queries /api/v1/admin/agent-activity
    res_admin = api_client.get("/api/v1/admin/agent-activity", headers=admin_auth["headers"])
    assert res_admin.status_code == 200
    assert len(res_admin.json()) >= 2

    # Admin filters by stage
    res_filtered = api_client.get(
        "/api/v1/admin/agent-activity",
        headers=admin_auth["headers"],
        params={"stage": "OBSERVE"},
    )
    assert res_filtered.status_code == 200
    assert all(item["stage"] == "OBSERVE" for item in res_filtered.json())

    # Applicant accesses their own activity
    res_applicant = api_client.get("/api/v1/agents/activity", headers=applicant_auth["headers"])
    assert res_applicant.status_code == 200
    assert len(res_applicant.json()) >= 2
    assert all(item["applicationId"] == app_id for item in res_applicant.json())

    # Applicant cannot query another applicant's activity
    res_forbidden = api_client.get(
        "/api/v1/agents/activity/SE99999999",
        headers=applicant_auth["headers"],
    )
    assert res_forbidden.status_code == 403
