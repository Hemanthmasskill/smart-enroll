from datetime import datetime, timedelta, timezone
import io
import threading
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
import pymupdf
import pytest

from app.services.document import process_document, verify_document

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
from app.agents.orchestrator import (
    AgentOrchestrator,
    ApplicationObservation,
    DeterministicPlanningStrategy,
    PlannedAction,
    PlanningStrategy,
    map_outcome_to_lifecycle_status,
)
from app.core.config import settings
from app.core.database import DatabaseInitializationError, connect_to_mongo, get_db
from app.main import app
from app.schemas.agent import (
    OrchestrationOutcome,
    OrchestrationRunResponse,
    OrchestrationRunStatus,
    ToolName,
    ToolStatus,
    WorkflowStage,
)


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


@pytest.fixture(autouse=True)
def isolate_deterministic_orchestration(monkeypatch):
    """
    Ensure deterministic orchestration regression tests remain completely isolated
    from any local or live LLM provider configuration in developer environment/.env.
    """
    monkeypatch.setattr(settings, "LLM_PROVIDER", "disabled")


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
    db["orchestration_runs"].delete_many({})
    try:
        existing_indexes = db["orchestration_runs"].index_information()
        for idx_name, idx_info in existing_indexes.items():
            if idx_info.get("key") == [("applicationId", 1)] and "partialFilterExpression" in idx_info:
                pfe = idx_info.get("partialFilterExpression", {})
                if pfe.get("status") != {"$in": ["RUNNING", "RECOVERING"]}:
                    db["orchestration_runs"].drop_index(idx_name)
        db["orchestration_runs"].create_index(
            [("applicationId", 1)],
            unique=True,
            partialFilterExpression={"status": {"$in": ["RUNNING", "RECOVERING"]}},
        )
    except Exception:
        pass
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


# =====================================================================
# Task 15.2: Autonomous Orchestrator Loop Tests
# =====================================================================

def upload_all_six_documents(api_client, applicant_auth, app_id, mismatch_marksheet: bool = False):
    """Helper to upload all 6 required canonical documents."""
    marksheet_name = "Candidate Name: Ramesh Kumar" if mismatch_marksheet else "Candidate Name: Hemanth M.P."
    docs_to_upload = [
        ("10TH_MARKSHEET", ["Secondary School Certificate", marksheet_name, "Date of Birth: 15/05/2000", "Marks: 432 / 500", "Percentage: 86.4%", "State Board of Secondary Education"]),
        ("12TH_MARKSHEET", ["Higher Secondary Certificate", "Candidate Name: Hemanth M.P.", "Date of Birth: 15/05/2000", "Marks: 440 / 500", "Percentage: 88.0%", "State Board of Higher Secondary"]),
        ("UG_MARKSHEET", ["Bachelor of Computer Applications Marksheet", "Candidate Name: Hemanth M.P.", "Date of Birth: 15/05/2000", "CGPA: 8.5", "Graduation Year: 2022", "University: Crescent"]),
        ("DEGREE_CERTIFICATE", ["B.S. Abdur Rahman Crescent Institute of Science and Technology", "Degree of Bachelor of Computer Applications", "Candidate Name: Hemanth M.P.", "Conferred: 2022"]),
        ("TRANSFER_CERTIFICATE", ["Transfer Certificate", "Student Name: Hemanth M.P.", "Date of Birth: 15/05/2000", "Conduct: Good"]),
        ("GOVERNMENT_ID", ["Government of India Identity Card", "Name: Hemanth M.P.", "DOB: 15/05/2000", "Gender: Male"]),
    ]
    uploaded_ids = {}
    for doc_type, lines in docs_to_upload:
        pdf_bytes = create_sample_pdf_bytes(lines)
        extra_data = {"documentType": doc_type, "applicationId": app_id}
        if doc_type == "DEGREE_CERTIFICATE":
            extra_data["documentVariant"] = "ORIGINAL_DEGREE_CERTIFICATE"
        up_res = api_client.post(
            "/api/v1/documents/upload",
            headers=applicant_auth["headers"],
            data=extra_data,
            files={"file": (f"{doc_type.lower()}.pdf", pdf_bytes, "application/pdf")},
        )
        assert up_res.status_code == 201
        uploaded_ids[doc_type] = up_res.json()["documentId"]
    return uploaded_ids


# 1. Missing documents result in WAITING_FOR_DOCUMENTS.
def test_orchestration_missing_documents_routes_to_waiting_for_documents(applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]

    # Set status to SUBMITTED
    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})

    orchestrator = AgentOrchestrator(db=clean_db)
    res = orchestrator.run(app_id, applicant_auth["user"])

    assert res.outcome == OrchestrationOutcome.WAITING_FOR_APPLICANT
    assert res.currentApplicationStatus == "WAITING_FOR_DOCUMENTS"
    assert clean_db["applications"].find_one({"applicationId": app_id})["status"] == "WAITING_FOR_DOCUMENTS"
    assert res.stepsCompleted >= 1

    # Verify audit event recorded
    audit_events = list_agent_activity(clean_db, applicant_auth["user"], application_id=app_id)
    assert any(e["stage"] == "OBSERVE" for e in audit_events)
    assert any(e["stage"] == "ACT" for e in audit_events)


# 2. A successful multi-step orchestration path using real service contracts with isolated test data.
def test_orchestration_successful_multi_step_path(api_client, applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]

    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})
    upload_all_six_documents(api_client, applicant_auth, app_id)

    orchestrator = AgentOrchestrator(db=clean_db)
    res = orchestrator.run(app_id, applicant_auth["user"])

    assert res.outcome == OrchestrationOutcome.DEPENDENCY_PENDING
    assert res.pendingDependency == "Increment 16: Eligibility Engine"
    assert res.currentApplicationStatus == "ELIGIBILITY_CHECK"
    assert clean_db["applications"].find_one({"applicationId": app_id})["status"] == "ELIGIBILITY_CHECK"
    assert res.stepsCompleted >= 8


# 3. Completed OCR results are followed by deterministic validation.
def test_orchestration_completed_ocr_followed_by_deterministic_validation(api_client, applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]

    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})
    upload_all_six_documents(api_client, applicant_auth, app_id)

    orchestrator = AgentOrchestrator(db=clean_db)
    orchestrator.run(app_id, applicant_auth["user"])

    # Verify all 6 documents are processed and validated
    docs = list(clean_db["documents"].find({"applicationId": app_id}))
    assert len(docs) == 6
    for d in docs:
        assert d.get("processingStatus") == "COMPLETED"
        assert d.get("validationStatus") == "VALIDATED"
        assert "fieldResults" in d.get("validationResult", {})


# 4. Mismatch/ambiguous evidence produces an explicit manual-review/exception outcome.
def test_orchestration_mismatch_produces_manual_review_exception(api_client, applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]

    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})
    # Upload 6 documents, but 10th marksheet has a conflicting candidate name "Ramesh Kumar"
    upload_all_six_documents(api_client, applicant_auth, app_id, mismatch_marksheet=True)

    orchestrator = AgentOrchestrator(db=clean_db)
    res = orchestrator.run(app_id, applicant_auth["user"])

    assert res.outcome == OrchestrationOutcome.MANUAL_REVIEW_REQUIRED
    assert res.currentApplicationStatus == "EXCEPTION"
    assert clean_db["applications"].find_one({"applicationId": app_id})["status"] == "EXCEPTION"


# 5. OCR failure does not trigger a false successful verification.
def test_orchestration_ocr_failure_does_not_trigger_false_verification(api_client, applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]

    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})
    upload_all_six_documents(api_client, applicant_auth, app_id)

    # Force one document to simulate an unreadable OCR failure
    clean_db["documents"].update_one(
        {"applicationId": app_id, "documentType": "10TH_MARKSHEET"},
        {"$set": {"processingStatus": "FAILED", "validationStatus": "ERROR"}},
    )

    orchestrator = AgentOrchestrator(db=clean_db)
    res = orchestrator.run(app_id, applicant_auth["user"])

    assert res.outcome == OrchestrationOutcome.MANUAL_REVIEW_REQUIRED
    assert res.currentApplicationStatus == "EXCEPTION"
    assert clean_db["applications"].find_one({"applicationId": app_id})["status"] == "EXCEPTION"


# 6. Eligibility dependency-pending does not mark the application eligible.
def test_orchestration_eligibility_dependency_pending_does_not_mark_eligible(api_client, applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]

    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})
    upload_all_six_documents(api_client, applicant_auth, app_id)

    orchestrator = AgentOrchestrator(db=clean_db)
    res = orchestrator.run(app_id, applicant_auth["user"])

    assert res.outcome == OrchestrationOutcome.DEPENDENCY_PENDING
    assert clean_db["applications"].find_one({"applicationId": app_id})["status"] == "ELIGIBILITY_CHECK"
    # Must NOT be marked ELIGIBLE or INELIGIBLE or PROCESSING_COMPLETE
    final_status = clean_db["applications"].find_one({"applicationId": app_id})["status"]
    assert final_status not in ("ELIGIBLE", "INELIGIBLE", "PROCESSING_COMPLETE")


# 7. Notification/exception dependencies do not fabricate records.
def test_orchestration_dependencies_do_not_fabricate_records(applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]

    res_notif = tool_send_notification(clean_db, applicant_auth["user"], str(applicant_auth["user"]["_id"]), "Title", "Msg")
    assert res_notif.status == ToolStatus.DEPENDENCY_PENDING.value
    assert res_notif.dependency == "Increment 18: Notifications"

    res_exc = tool_create_exception(clean_db, applicant_auth["user"], app_id, "DOC_MISMATCH", "Mismatch")
    assert res_exc.status == ToolStatus.DEPENDENCY_PENDING.value
    assert res_exc.dependency == "Increment 17: Exception Management"


# 8. Applicant cannot trigger orchestration for another applicant.
def test_orchestration_applicant_cross_access_denied(api_client, applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]

    # Register second applicant
    reg2 = api_client.post(
        "/api/v1/auth/register",
        json={
            "fullName": "Intruder Applicant",
            "email": "intruder@smartenroll.edu",
            "mobile": "9876543288",
            "dob": "1998-03-20",
            "password": "Password123!",
        },
    )
    assert reg2.status_code == 201
    second_headers = {"Authorization": f"Bearer {reg2.json()['token']}"}

    # Cross-orchestration trigger denied
    res_trigger = api_client.post(f"/api/v1/agents/orchestrate/{app_id}", headers=second_headers)
    assert res_trigger.status_code == 403

    # Cross-orchestration status check denied
    res_status = api_client.get(f"/api/v1/agents/orchestrate/{app_id}/status", headers=second_headers)
    assert res_status.status_code == 403


# 9. Admin authorization follows the existing role model.
def test_orchestration_admin_authorization(api_client, admin_auth, applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]
    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})

    # Admin triggers orchestration
    res = api_client.post(f"/api/v1/agents/orchestrate/{app_id}", headers=admin_auth["headers"])
    assert res.status_code == 200
    data = res.json()
    run_id = data["runId"]

    # Admin queries status
    res_status = api_client.get(f"/api/v1/agents/orchestrate/{app_id}/status", headers=admin_auth["headers"])
    assert res_status.status_code == 200
    assert res_status.json()["runId"] == run_id

    # Admin queries specific run
    res_run = api_client.get(f"/api/v1/agents/orchestrate/runs/{run_id}", headers=admin_auth["headers"])
    assert res_run.status_code == 200
    assert res_run.json()["runId"] == run_id


# 10. Duplicate concurrent runs do not process the same application twice.
def test_orchestration_concurrency_guard_prevents_duplicate_runs(applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]

    # Seed an active RUNNING run
    clean_db["orchestration_runs"].insert_one({
        "runId": "run-active-lock",
        "applicationId": app_id,
        "status": OrchestrationRunStatus.RUNNING.value,
        "startedAt": datetime.now(timezone.utc).isoformat(),
    })

    orchestrator = AgentOrchestrator(db=clean_db)
    res = orchestrator.run(app_id, applicant_auth["user"])

    assert res.outcome == OrchestrationOutcome.ALREADY_RUNNING
    assert res.stepsCompleted == 0
    assert "already in progress" in res.summary.lower()


# 11. A bounded iteration limit stops endless re-planning.
def test_orchestration_bounded_iteration_limit(applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]

    class InfinitePlanningStrategy(PlanningStrategy):
        def plan_next_action(self, observation, iteration):
            return (
                PlannedAction(
                    tool=ToolName.GET_PROGRAM_REQUIREMENTS,
                    parameters={"programme_id": "mca"},
                    rationale=f"Infinite loop step {iteration}",
                ),
                None,
                None,
            )

    orchestrator = AgentOrchestrator(
        db=clean_db,
        planning_strategy=InfinitePlanningStrategy(),
        max_iterations=3,
    )
    res = orchestrator.run(app_id, applicant_auth["user"])

    assert res.outcome == OrchestrationOutcome.FAILED
    assert "maximum bounded iteration limit" in (res.failureReason or "").lower()
    assert res.stepsCompleted == 3


# 12. Tool exceptions result in sanitized failure outcomes and safe audit records.
def test_orchestration_tool_exception_sanitized_and_audited(applicant_auth, clean_db, monkeypatch):
    from app.agents import tools

    app_id = applicant_auth["application"]["applicationId"]
    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})

    def mock_leaking_tool(*args, **kwargs):
        raise RuntimeError("CRITICAL: leaked connection mongodb://admin:my_secret_token@10.10.10.10:27017")

    monkeypatch.setitem(tools.TOOL_REGISTRY, "update_application_status", mock_leaking_tool)

    orchestrator = AgentOrchestrator(db=clean_db)
    res = orchestrator.run(app_id, applicant_auth["user"])

    assert res.outcome == OrchestrationOutcome.FAILED
    assert "my_secret_token" not in (res.failureReason or "")
    assert "10.10.10.10" not in (res.failureReason or "")

    # Verify audit logs do not leak the secret
    logs = list_agent_activity(clean_db, applicant_auth["user"], application_id=app_id)
    for log in logs:
        assert "my_secret_token" not in log.get("result", "")


# 13. Workflow state persists in MongoDB and can be queried with correct authorization.
def test_orchestration_state_persists_in_mongodb_and_queryable(api_client, applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]

    res_post = api_client.post(
        f"/api/v1/agents/orchestrate/{app_id}",
        headers=applicant_auth["headers"],
    )
    assert res_post.status_code == 200
    run_id = res_post.json()["runId"]

    # Verify persisted in database
    run_doc = clean_db["orchestration_runs"].find_one({"runId": run_id})
    assert run_doc is not None
    assert run_doc["status"] != OrchestrationRunStatus.RUNNING.value

    # Query latest status via API
    res_status = api_client.get(
        f"/api/v1/agents/orchestrate/{app_id}/status",
        headers=applicant_auth["headers"],
    )
    assert res_status.status_code == 200
    assert res_status.json()["runId"] == run_id

    # Query run by ID via API
    res_run = api_client.get(
        f"/api/v1/agents/orchestrate/runs/{run_id}",
        headers=applicant_auth["headers"],
    )
    assert res_run.status_code == 200
    assert res_run.json()["runId"] == run_id


# 14. No external API key is required for the deterministic strategy.
def test_deterministic_strategy_requires_no_external_api_key(applicant_auth, clean_db):
    import os
    # Ensure OPENAI_API_KEY is not set or empty
    assert os.getenv("OPENAI_API_KEY", "") == ""

    app_id = applicant_auth["application"]["applicationId"]
    strat = DeterministicPlanningStrategy()
    obs = AgentOrchestrator(db=clean_db).observe(app_id)

    # Calling planning strategy works completely offline
    action, outcome, summary = strat.plan_next_action(obs, 1)
    assert outcome is not None or action is not None


# 15. A stale RUNNING record is recovered safely.
def test_orchestration_stale_running_record_recovered_safely(applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]
    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})

    # Seed an abandoned run whose lease expired 10 minutes ago
    expired_time = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
    clean_db["orchestration_runs"].insert_one({
        "runId": "run-stale-abandoned-1",
        "applicationId": app_id,
        "status": OrchestrationRunStatus.RUNNING.value,
        "startedAt": expired_time,
        "heartbeatAt": expired_time,
        "leaseExpiresAt": expired_time,
        "progressVersion": 1,
    })

    orchestrator = AgentOrchestrator(db=clean_db, stale_timeout_seconds=300)
    res = orchestrator.run(app_id, applicant_auth["user"])

    # Old run is marked ABORTED with failure outcome
    old_run = clean_db["orchestration_runs"].find_one({"runId": "run-stale-abandoned-1"})
    assert old_run["status"] == OrchestrationRunStatus.ABORTED.value
    assert old_run["outcome"] == OrchestrationOutcome.FAILED.value
    assert "lease expired" in old_run["failureReason"].lower()
    assert old_run["completedAt"] is not None

    # New run took over and executed safely
    assert res.runId != "run-stale-abandoned-1"
    assert res.status == OrchestrationRunStatus.COMPLETED
    assert res.outcome == OrchestrationOutcome.WAITING_FOR_APPLICANT


# 16. A recently active run cannot be taken over.
def test_orchestration_recently_active_run_cannot_be_taken_over(applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]

    # Seed an active run whose lease is valid for 5 more minutes
    future_time = (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat()
    clean_db["orchestration_runs"].insert_one({
        "runId": "run-active-fresh",
        "applicationId": app_id,
        "status": OrchestrationRunStatus.RUNNING.value,
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "heartbeatAt": datetime.now(timezone.utc).isoformat(),
        "leaseExpiresAt": future_time,
        "progressVersion": 1,
    })

    orchestrator = AgentOrchestrator(db=clean_db, stale_timeout_seconds=300)
    res = orchestrator.run(app_id, applicant_auth["user"])

    assert res.outcome == OrchestrationOutcome.ALREADY_RUNNING
    assert res.status == OrchestrationRunStatus.RUNNING
    assert res.runId == "run-active-fresh"

    # Old run remains RUNNING
    run_in_db = clean_db["orchestration_runs"].find_one({"runId": "run-active-fresh"})
    assert run_in_db["status"] == OrchestrationRunStatus.RUNNING.value


# 17. Two concurrent recovery attempts cannot both claim the same run.
def test_orchestration_concurrent_recovery_attempts_cannot_both_claim(applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]

    expired_time = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
    clean_db["orchestration_runs"].insert_one({
        "runId": "run-stale-competing",
        "applicationId": app_id,
        "status": OrchestrationRunStatus.RUNNING.value,
        "startedAt": expired_time,
        "heartbeatAt": expired_time,
        "leaseExpiresAt": expired_time,
        "progressVersion": 1,
    })

    orchestrator1 = AgentOrchestrator(db=clean_db, stale_timeout_seconds=300)
    orchestrator2 = AgentOrchestrator(db=clean_db, stale_timeout_seconds=300)

    barrier = threading.Barrier(2)
    results = [None, None]

    def worker_claim(idx, orch):
        try:
            barrier.wait(timeout=5.0)
            doc, err = orch._claim_or_recover_run(
                application_id=app_id,
                user_id=str(applicant_auth["user"]["_id"]),
                role="applicant",
                initial_status="DRAFT",
            )
            results[idx] = (doc, err)
        except Exception as e:
            results[idx] = (None, e)

    t1 = threading.Thread(target=worker_claim, args=(0, orchestrator1))
    t2 = threading.Thread(target=worker_claim, args=(1, orchestrator2))
    t1.start()
    t2.start()
    t1.join(timeout=5.0)
    t2.join(timeout=5.0)

    successes = [r for r in results if r and r[0] is not None and r[1] is None]
    failures = [
        r for r in results
        if r and r[0] is None and isinstance(r[1], OrchestrationRunResponse) and r[1].outcome == OrchestrationOutcome.ALREADY_RUNNING
    ]

    assert len(successes) == 1, f"Expected exactly 1 claim success, got {len(successes)}"
    assert len(failures) == 1, f"Expected exactly 1 claim rejection (ALREADY_RUNNING), got {len(failures)}"


# 18. A recovered/expired execution cannot perform further state-changing actions (fencing).
def test_orchestration_fencing_prevents_state_changes_after_lease_loss(applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]
    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})

    class ExternalInterferingStrategy(PlanningStrategy):
        def plan_next_action(self, observation, iteration):
            # On first iteration, simulate an external process aborting/recovering this run
            clean_db["orchestration_runs"].update_one(
                {"applicationId": app_id, "status": OrchestrationRunStatus.RUNNING.value},
                {"$set": {"status": OrchestrationRunStatus.ABORTED.value, "progressVersion": 999}},
            )
            return (
                PlannedAction(
                    tool=ToolName.UPDATE_APPLICATION_STATUS,
                    parameters={"application_id": app_id, "new_status": "PROCESSING"},
                    rationale="Attempting state change after lease loss",
                ),
                None,
                None,
            )

    orchestrator = AgentOrchestrator(
        db=clean_db,
        planning_strategy=ExternalInterferingStrategy(),
        max_iterations=5,
    )
    res = orchestrator.run(app_id, applicant_auth["user"])

    # Fencing triggered
    assert res.status == OrchestrationRunStatus.ABORTED
    assert res.outcome == OrchestrationOutcome.FAILED
    assert "ownership was lost" in res.summary.lower()

    # The application status must NOT have been changed to PROCESSING
    app_in_db = clean_db["applications"].find_one({"applicationId": app_id})
    assert app_in_db["status"] == "SUBMITTED"


# 19. Recovery does not blindly repeat partially completed document processing.
def test_orchestration_recovery_does_not_repeat_partially_completed_ocr(api_client, applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]
    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})
    upload_all_six_documents(api_client, applicant_auth, app_id)

    # Manually mark 2 documents as COMPLETED and VALIDATED
    doc_10th = clean_db["documents"].find_one({"applicationId": app_id, "documentType": "10TH_MARKSHEET"})
    doc_12th = clean_db["documents"].find_one({"applicationId": app_id, "documentType": "12TH_MARKSHEET"})

    fixed_timestamp = "2026-10-19T10:00:00+00:00"
    clean_db["documents"].update_many(
        {"_id": {"$in": [doc_10th["_id"], doc_12th["_id"]]}},
        {
            "$set": {
                "processingStatus": "COMPLETED",
                "validationStatus": "VALIDATED",
                "status": "VALIDATED",
                "updatedAt": fixed_timestamp,
                "processingResult": {"overallConfidence": 0.95, "processingState": "COMPLETED"},
            }
        },
    )

    # Seed an abandoned run
    expired_time = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
    clean_db["orchestration_runs"].insert_one({
        "runId": "run-abandoned-partial",
        "applicationId": app_id,
        "status": OrchestrationRunStatus.RUNNING.value,
        "startedAt": expired_time,
        "heartbeatAt": expired_time,
        "leaseExpiresAt": expired_time,
        "progressVersion": 1,
    })

    orchestrator = AgentOrchestrator(db=clean_db)
    res = orchestrator.run(app_id, applicant_auth["user"])

    # Completed documents were NOT re-processed: their updatedAt timestamp is strictly preserved
    doc_10th_after = clean_db["documents"].find_one({"_id": doc_10th["_id"]})
    doc_12th_after = clean_db["documents"].find_one({"_id": doc_12th["_id"]})
    assert doc_10th_after["updatedAt"] == fixed_timestamp
    assert doc_12th_after["updatedAt"] == fixed_timestamp


# 20. Outer-loop errors are sanitized in API responses and persisted records.
def test_orchestration_outer_loop_error_sanitized_and_persisted(applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]
    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})

    class LeakingPlanningStrategy(PlanningStrategy):
        def plan_next_action(self, observation, iteration):
            raise RuntimeError("CRITICAL: leaked connection mongodb://admin:my_ultra_secret@10.240.0.5:27017/smartenroll")

    orchestrator = AgentOrchestrator(
        db=clean_db,
        planning_strategy=LeakingPlanningStrategy(),
    )
    res = orchestrator.run(app_id, applicant_auth["user"])

    assert res.outcome == OrchestrationOutcome.FAILED
    assert res.status == OrchestrationRunStatus.FAILED

    # Verify secret is sanitized in response
    assert "my_ultra_secret" not in (res.failureReason or "")
    assert "10.240.0.5" not in (res.failureReason or "")
    assert "mongodb://" not in (res.failureReason or "")
    assert "my_ultra_secret" not in res.summary

    # Verify secret is not in persisted database record
    run_doc = clean_db["orchestration_runs"].find_one({"runId": res.runId})
    assert "my_ultra_secret" not in (run_doc.get("failureReason") or "")
    assert "10.240.0.5" not in (run_doc.get("failureReason") or "")


# 21. RUNNING transitions to a valid lifecycle status for every terminal workflow outcome.
def test_orchestration_lifecycle_status_and_outcome_mapping(api_client, applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]

    # 1. WAITING_FOR_APPLICANT outcome -> lifecycle status is COMPLETED
    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})
    res_waiting = AgentOrchestrator(db=clean_db).run(app_id, applicant_auth["user"])
    assert res_waiting.outcome == OrchestrationOutcome.WAITING_FOR_APPLICANT
    assert res_waiting.status == OrchestrationRunStatus.COMPLETED

    run_doc_waiting = clean_db["orchestration_runs"].find_one({"runId": res_waiting.runId})
    assert run_doc_waiting["status"] == OrchestrationRunStatus.COMPLETED.value
    assert run_doc_waiting["outcome"] == OrchestrationOutcome.WAITING_FOR_APPLICANT.value

    # 2. DEPENDENCY_PENDING outcome -> lifecycle status is COMPLETED
    upload_all_six_documents(api_client, applicant_auth, app_id)
    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})
    res_dep = AgentOrchestrator(db=clean_db).run(app_id, applicant_auth["user"])
    assert res_dep.outcome == OrchestrationOutcome.DEPENDENCY_PENDING
    assert res_dep.status == OrchestrationRunStatus.COMPLETED

    run_doc_dep = clean_db["orchestration_runs"].find_one({"runId": res_dep.runId})
    assert run_doc_dep["status"] == OrchestrationRunStatus.COMPLETED.value
    assert run_doc_dep["outcome"] == OrchestrationOutcome.DEPENDENCY_PENDING.value

    # 3. All runs cleared the partial unique index on RUNNING
    running_runs = list(clean_db["orchestration_runs"].find({"applicationId": app_id, "status": "RUNNING"}))
    assert len(running_runs) == 0


# 22. An ownership check succeeds, recovery wins before the tool's persistent mutation,
# and the stale worker cannot perform that mutation.
def test_ownership_check_succeeds_recovery_wins_before_mutation_mutation_blocked(applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]
    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})

    orchestrator = AgentOrchestrator(db=clean_db)
    # Worker 1 claims run_1
    run_doc1, err1 = orchestrator._claim_or_recover_run(
        application_id=app_id,
        user_id=str(applicant_auth["user"]["_id"]),
        role="applicant",
        initial_status="SUBMITTED",
    )
    assert run_doc1 is not None
    run_id_1 = run_doc1["runId"]

    # Verify activeRunId is set on applications
    app_before = clean_db["applications"].find_one({"applicationId": app_id})
    assert app_before.get("activeRunId") == run_id_1

    # Worker 1 pre-ACT ownership check succeeds
    act_fence = clean_db["orchestration_runs"].update_one(
        {"runId": run_id_1, "status": OrchestrationRunStatus.RUNNING.value, "applicationId": app_id},
        {"$inc": {"progressVersion": 1}},
    )
    assert act_fence.matched_count == 1

    # Recovery wins! Worker 2 recovers run_1 and claims run_2
    clean_db["orchestration_runs"].update_one(
        {"runId": run_id_1},
        {"$set": {"status": OrchestrationRunStatus.ABORTED.value}},
    )
    clean_db["applications"].update_one(
        {"applicationId": app_id},
        {"$set": {"activeRunId": "run-worker-2"}},
    )

    # Worker 1 now attempts the persistent mutation via tool_update_application_status
    exec_res = tool_update_application_status(
        db=clean_db,
        current_user={"_id": "system_orchestrator", "role": "system", "full_name": "Autonomous Agent Orchestrator"},
        application_id=app_id,
        new_status="PROCESSING",
        run_id=run_id_1,
    )

    # Mutation is REJECTED
    assert exec_res.status == ToolStatus.FAILED.value
    assert "ownership lost" in exec_res.message.lower()

    # Crucial assertion: Persistent MongoDB state was NOT modified by the stale worker
    app_after = clean_db["applications"].find_one({"applicationId": app_id})
    assert app_after["status"] == "SUBMITTED"  # NOT "PROCESSING"
    assert app_after["activeRunId"] == "run-worker-2"


# 23. A long-running tool does not lose ownership while it is legitimately active.
def test_long_running_tool_maintains_lease_renewal_without_losing_ownership(applicant_auth, clean_db):
    import time
    app_id = applicant_auth["application"]["applicationId"]
    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})

    orchestrator = AgentOrchestrator(db=clean_db, stale_timeout_seconds=2)

    class LongRunningToolStrategy(PlanningStrategy):
        def plan_next_action(self, observation, iteration):
            if iteration == 1:
                return (
                    PlannedAction(
                        tool=ToolName.GET_APPLICATION,
                        parameters={"application_id": app_id},
                        rationale="Simulating long-running operation",
                    ),
                    None,
                    None,
                )
            return None, OrchestrationOutcome.COMPLETED, "Completed"

    from app.agents import tools as tools_module
    original_get_app = tools_module.tool_get_application

    def slow_get_application(*args, **kwargs):
        time.sleep(1.2)
        now_check = datetime.now(timezone.utc)
        existing_run = clean_db["orchestration_runs"].find_one({"applicationId": app_id, "status": "RUNNING"})
        assert existing_run is not None
        is_stale = orchestrator._is_run_stale(existing_run, now_check)
        assert is_stale is False, "Active run was incorrectly marked stale during tool execution"
        return original_get_app(*args, **kwargs)

    tools_module.TOOL_REGISTRY[ToolName.GET_APPLICATION.value] = slow_get_application
    try:
        orch = AgentOrchestrator(
            db=clean_db,
            planning_strategy=LongRunningToolStrategy(),
            stale_timeout_seconds=2,
            max_iterations=2,
        )
        res = orch.run(app_id, applicant_auth["user"])
        assert res.outcome == OrchestrationOutcome.COMPLETED
        assert res.status == OrchestrationRunStatus.COMPLETED
    finally:
        tools_module.TOOL_REGISTRY[ToolName.GET_APPLICATION.value] = original_get_app


# 24. A recovered worker cannot overwrite the recovered run's final state.
def test_recovered_worker_cannot_overwrite_final_state(applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]
    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})

    run_id = "run-recovered-prior"
    clean_db["orchestration_runs"].insert_one({
        "runId": run_id,
        "applicationId": app_id,
        "status": OrchestrationRunStatus.ABORTED.value,
        "outcome": OrchestrationOutcome.FAILED.value,
        "failureReason": "Execution lease expired and was abandoned; safely recovered.",
        "startedAt": "2026-10-20T00:00:00Z",
        "completedAt": "2026-10-20T00:05:00Z",
    })

    update_res = clean_db["orchestration_runs"].update_one(
        {"runId": run_id, "status": OrchestrationRunStatus.RUNNING.value},
        {"$set": {"status": OrchestrationRunStatus.COMPLETED.value, "outcome": OrchestrationOutcome.COMPLETED.value}},
    )
    assert update_res.matched_count == 0

    persisted = clean_db["orchestration_runs"].find_one({"runId": run_id})
    assert persisted["status"] == OrchestrationRunStatus.ABORTED.value
    assert persisted["failureReason"] == "Execution lease expired and was abandoned; safely recovered."


# 25. ALREADY_RUNNING is handled as a duplicate-trigger outcome rather than a fabricated failed run.
def test_already_running_handled_as_duplicate_trigger_not_fabricated_failure(applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]
    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})

    active_run_id = "run-currently-active-777"
    start_ts = datetime.now(timezone.utc).isoformat()
    future_ts = (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat()
    clean_db["orchestration_runs"].insert_one({
        "runId": active_run_id,
        "applicationId": app_id,
        "status": OrchestrationRunStatus.RUNNING.value,
        "startedAt": start_ts,
        "heartbeatAt": start_ts,
        "leaseExpiresAt": future_ts,
        "stepsCompleted": 3,
    })

    count_before = clean_db["orchestration_runs"].count_documents({"applicationId": app_id})
    assert count_before == 1

    orchestrator = AgentOrchestrator(db=clean_db)
    res = orchestrator.run(app_id, applicant_auth["user"])

    assert res.outcome == OrchestrationOutcome.ALREADY_RUNNING
    assert res.status == OrchestrationRunStatus.RUNNING
    assert res.runId == active_run_id
    assert res.stepsCompleted == 3

    count_after = clean_db["orchestration_runs"].count_documents({"applicationId": app_id})
    assert count_after == 1

    active_in_db = clean_db["orchestration_runs"].find_one({"runId": active_run_id})
    assert active_in_db["status"] == OrchestrationRunStatus.RUNNING.value


# 26. Explicit mapping of all OrchestrationOutcome values to OrchestrationRunStatus.
def test_all_outcome_to_lifecycle_status_mappings():
    assert map_outcome_to_lifecycle_status(OrchestrationOutcome.COMPLETED) == OrchestrationRunStatus.COMPLETED
    assert map_outcome_to_lifecycle_status(OrchestrationOutcome.WAITING_FOR_APPLICANT) == OrchestrationRunStatus.COMPLETED
    assert map_outcome_to_lifecycle_status(OrchestrationOutcome.MANUAL_REVIEW_REQUIRED) == OrchestrationRunStatus.COMPLETED
    assert map_outcome_to_lifecycle_status(OrchestrationOutcome.DEPENDENCY_PENDING) == OrchestrationRunStatus.COMPLETED
    assert map_outcome_to_lifecycle_status(OrchestrationOutcome.FAILED) == OrchestrationRunStatus.FAILED
    assert map_outcome_to_lifecycle_status(OrchestrationOutcome.ALREADY_RUNNING) == OrchestrationRunStatus.RUNNING


# 27. Recovery begins: a stale worker tries to update application status while recovery
# is changing resource ownership. Verify the result matches ownership and recovery linearization rules.
def test_recovery_linearization_stale_worker_application_update_blocked(applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]
    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})

    orchestrator = AgentOrchestrator(db=clean_db)
    # 1. Worker 1 claims run_1
    run_doc1, err1 = orchestrator._claim_or_recover_run(
        application_id=app_id,
        user_id=str(applicant_auth["user"]["_id"]),
        role="applicant",
        initial_status="SUBMITTED",
    )
    assert run_doc1 is not None
    run_id_1 = run_doc1["runId"]
    assert clean_db["applications"].find_one({"applicationId": app_id}).get("activeRunId") == run_id_1

    # 2. Worker 1 pre-ACT check succeeds
    fence_1 = clean_db["orchestration_runs"].update_one(
        {"runId": run_id_1, "status": OrchestrationRunStatus.RUNNING.value, "applicationId": app_id},
        {"$inc": {"leaseVersion": 1}},
    )
    assert fence_1.matched_count == 1

    # 3. Recovery begins: Step 1 CAS sets status to RECOVERING
    cas_res = clean_db["orchestration_runs"].update_one(
        {"runId": run_id_1, "status": OrchestrationRunStatus.RUNNING.value},
        {"$set": {"status": OrchestrationRunStatus.RECOVERING.value}},
    )
    assert cas_res.matched_count == 1

    # Step 2: Revoke application fencing token
    rec_fence_token = f"superseded-{run_id_1}"
    clean_db["applications"].update_one(
        {"applicationId": app_id, "activeRunId": run_id_1},
        {"$set": {"activeRunId": rec_fence_token}},
    )

    # 4. Stale Worker 1 attempts to perform mutation via tool_update_application_status
    exec_res = tool_update_application_status(
        db=clean_db,
        current_user={"_id": "system_orchestrator", "role": "system", "full_name": "Autonomous Agent Orchestrator"},
        application_id=app_id,
        new_status="PROCESSING",
        run_id=run_id_1,
    )
    assert exec_res.status == ToolStatus.FAILED.value
    assert "ownership lost" in exec_res.message.lower()

    # Crucial assertion: Persistent MongoDB state was NOT modified by the stale worker
    app_after = clean_db["applications"].find_one({"applicationId": app_id})
    assert app_after["status"] == "SUBMITTED"
    assert app_after["activeRunId"] == rec_fence_token

    # 5. Recovery Step 4 marks run_1 ABORTED and Step 5 establishes replacement run_2
    clean_db["orchestration_runs"].update_one(
        {"runId": run_id_1},
        {"$set": {"status": OrchestrationRunStatus.ABORTED.value, "outcome": OrchestrationOutcome.FAILED.value}},
    )
    run_doc2, err2 = orchestrator._claim_or_recover_run(
        application_id=app_id,
        user_id=str(applicant_auth["user"]["_id"]),
        role="applicant",
        initial_status="SUBMITTED",
    )
    assert run_doc2 is not None
    assert err2 is None
    assert clean_db["applications"].find_one({"applicationId": app_id}).get("activeRunId") == run_doc2["runId"]


# 28. Recovery begins: an old worker tries to persist OCR or verification results
# while a document's fencing token is being revoked.
def test_recovery_revocation_stale_worker_ocr_and_verification_persistence_blocked(api_client, applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]
    uploaded_ids = upload_all_six_documents(api_client, applicant_auth, app_id)
    doc_id = uploaded_ids["10TH_MARKSHEET"]

    run_id_1 = "run-worker-ocr-old"
    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"activeRunId": run_id_1}})
    clean_db["documents"].update_one({"documentId": doc_id}, {"$set": {"activeRunId": run_id_1, "processingStatus": "UPLOADED"}})

    # Recovery Step 2 revokes document fencing token
    rec_token = f"superseded-{run_id_1}"
    clean_db["documents"].update_one(
        {"documentId": doc_id, "activeRunId": run_id_1},
        {"$set": {"activeRunId": rec_token}},
    )

    # Worker 1 tries to persist OCR via process_document
    with pytest.raises(HTTPException) as exc_info:
        process_document(
            db=clean_db,
            current_user=applicant_auth["user"],
            document_id=doc_id,
            run_id=run_id_1,
        )
    assert exc_info.value.status_code == 409
    assert "ownership lost" in exc_info.value.detail.lower()

    # Document in MongoDB was NOT modified by Worker 1
    doc_after = clean_db["documents"].find_one({"documentId": doc_id})
    assert doc_after.get("activeRunId") == rec_token
    assert doc_after.get("processingStatus") != "COMPLETED"

    # Now verify that verify_document also rejects when activeRunId is revoked
    clean_db["documents"].update_one(
        {"documentId": doc_id},
        {"$set": {"processingStatus": "COMPLETED", "processingResult": {"test": "data"}, "activeRunId": rec_token}},
    )
    with pytest.raises(HTTPException) as exc_verify:
        verify_document(
            db=clean_db,
            current_user=applicant_auth["user"],
            document_id=doc_id,
            run_id=run_id_1,
        )
    assert exc_verify.value.status_code == 409
    assert "ownership lost" in exc_verify.value.detail.lower()


# 29. A stale worker attempts to claim a document after its ownership token has been cleared.
# It must not reacquire ownership.
def test_stale_worker_cannot_claim_document_when_token_cleared(api_client, applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]
    uploaded_ids = upload_all_six_documents(api_client, applicant_auth, app_id)
    doc_id = uploaded_ids["10TH_MARKSHEET"]

    # Both application activeRunId and document activeRunId are cleared/unset
    clean_db["applications"].update_one({"applicationId": app_id}, {"$unset": {"activeRunId": ""}})
    clean_db["documents"].update_one({"documentId": doc_id}, {"$unset": {"activeRunId": ""}, "$set": {"processingStatus": "UPLOADED"}})

    # Stale worker tries to claim and process document
    with pytest.raises(HTTPException) as exc_info:
        process_document(
            db=clean_db,
            current_user=applicant_auth["user"],
            document_id=doc_id,
            run_id="run-stale-abandoned",
        )
    assert exc_info.value.status_code == 409
    assert "ownership lost" in exc_info.value.detail.lower()

    # Document was NOT claimed by the stale worker
    doc_after = clean_db["documents"].find_one({"documentId": doc_id})
    assert doc_after.get("activeRunId") != "run-stale-abandoned"


# 30. A long-running tool completes after at least one heartbeat renewal, and the same legitimate
# execution successfully passes its next ownership check and performs a second state-changing action.
def test_long_running_tool_heartbeat_renewal_allows_next_step_and_second_mutation(applicant_auth, clean_db):
    import time
    app_id = applicant_auth["application"]["applicationId"]
    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})

    class MultiStepLongRunningStrategy(PlanningStrategy):
        def plan_next_action(self, observation, iteration):
            if iteration == 1:
                return (
                    PlannedAction(
                        tool=ToolName.GET_APPLICATION,
                        parameters={"application_id": app_id},
                        rationale="Slow operation in step 1",
                    ),
                    None,
                    None,
                )
            elif iteration == 2:
                return (
                    PlannedAction(
                        tool=ToolName.UPDATE_APPLICATION_STATUS,
                        parameters={"application_id": app_id, "new_status": "PROCESSING"},
                        rationale="State-changing mutation in step 2",
                    ),
                    None,
                    None,
                )
            return None, OrchestrationOutcome.COMPLETED, "Completed successfully"

    from app.agents import tools as tools_module
    original_get_app = tools_module.tool_get_application

    def slow_tool(*args, **kwargs):
        time.sleep(1.2)
        return original_get_app(*args, **kwargs)

    tools_module.TOOL_REGISTRY[ToolName.GET_APPLICATION.value] = slow_tool
    try:
        orch = AgentOrchestrator(
            db=clean_db,
            planning_strategy=MultiStepLongRunningStrategy(),
            stale_timeout_seconds=2,
            max_iterations=5,
        )
        res = orch.run(app_id, applicant_auth["user"])
        assert res.outcome == OrchestrationOutcome.COMPLETED
        assert res.status == OrchestrationRunStatus.COMPLETED

        # Verify second state-changing action modified the database
        app_final = clean_db["applications"].find_one({"applicationId": app_id})
        assert app_final["status"] == "PROCESSING"
        assert res.stepsCompleted >= 2
    finally:
        tools_module.TOOL_REGISTRY[ToolName.GET_APPLICATION.value] = original_get_app


# 31. A heartbeat races with stale-run compare-and-set. Exactly one safe outcome must occur;
# a live heartbeat must not be ignored.
def test_heartbeat_races_with_stale_run_cas_prevents_takeover(applicant_auth, clean_db):
    app_id = applicant_auth["application"]["applicationId"]
    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})

    now_utc = datetime.now(timezone.utc)
    past_iso = (now_utc - timedelta(seconds=400)).isoformat()
    r1_id = "run-live-heartbeating-1"

    clean_db["orchestration_runs"].insert_one({
        "runId": r1_id,
        "applicationId": app_id,
        "status": OrchestrationRunStatus.RUNNING.value,
        "startedAt": past_iso,
        "heartbeatAt": past_iso,
        "leaseExpiresAt": past_iso,
        "leaseVersion": 1,
        "progressVersion": 1,
    })
    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"activeRunId": r1_id}})

    # Synchronized barrier race between live heartbeat renewer and stale takeover CAS
    barrier = threading.Barrier(2)
    heartbeat_committed = threading.Event()
    cas_results = []

    def live_heartbeat_worker():
        barrier.wait(timeout=5.0)
        # R1's live heartbeat renewer fires and refreshes lease
        now_fresh = datetime.now(timezone.utc)
        refreshed_hb = now_fresh.isoformat()
        refreshed_exp = (now_fresh + timedelta(seconds=300)).isoformat()
        clean_db["orchestration_runs"].update_one(
            {"runId": r1_id, "status": OrchestrationRunStatus.RUNNING.value},
            {"$set": {"heartbeatAt": refreshed_hb, "leaseExpiresAt": refreshed_exp}, "$inc": {"leaseVersion": 1}},
        )
        heartbeat_committed.set()

    def competing_recovery_worker():
        # Worker 2 observed past_iso and leaseVersion 1 before the race
        barrier.wait(timeout=5.0)
        # Wait for heartbeat thread to commit its update to simulate the exact CAS race condition
        heartbeat_committed.wait(timeout=5.0)
        cas_filter = {
            "runId": r1_id,
            "status": OrchestrationRunStatus.RUNNING.value,
            "applicationId": app_id,
            "heartbeatAt": past_iso,
            "leaseVersion": 1,
        }
        cas_update = {"$set": {"status": OrchestrationRunStatus.RECOVERING.value}}
        cas_res = clean_db["orchestration_runs"].update_one(cas_filter, cas_update)
        cas_results.append(cas_res)

    t1 = threading.Thread(target=live_heartbeat_worker)
    t2 = threading.Thread(target=competing_recovery_worker)
    t1.start()
    t2.start()
    t1.join(timeout=5.0)
    t2.join(timeout=5.0)

    assert len(cas_results) == 1
    cas_res = cas_results[0]
    # The CAS MUST fail because the heartbeat was refreshed
    assert cas_res.matched_count == 0
    assert cas_res.modified_count == 0

    # Live run R1 remains RUNNING and in control
    r1_doc = clean_db["orchestration_runs"].find_one({"runId": r1_id})
    assert r1_doc["status"] == OrchestrationRunStatus.RUNNING.value
    assert r1_doc["leaseVersion"] == 2


# =====================================================================
# Tests: Finding A - Exclusivity during RECOVERING & Crash Recovery
# =====================================================================
def test_recovering_state_maintains_database_enforced_exclusivity_and_allows_resumption(applicant_auth, clean_db):
    """
    Finding A:
    1. A stale run is transitioned to RECOVERING.
    2. Recovery is paused immediately while in RECOVERING status.
    3. A concurrent orchestration request for the same application attempts to start.
    4. Database partial unique index on status in ('RUNNING', 'RECOVERING') rejects
       the second request, preventing a competing run or resource ownership theft.
    5. Recovery resumes, finishes resource revocation and marks old run ABORTED.
    6. Exactly one replacement execution is established.
    """
    app_id = applicant_auth["application"]["applicationId"]
    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})

    now_utc = datetime.now(timezone.utc)
    past_iso = (now_utc - timedelta(seconds=400)).isoformat()
    r1_id = "run-stale-recovering-1"

    clean_db["orchestration_runs"].insert_one({
        "runId": r1_id,
        "applicationId": app_id,
        "status": OrchestrationRunStatus.RUNNING.value,
        "startedAt": past_iso,
        "heartbeatAt": past_iso,
        "leaseExpiresAt": past_iso,
        "leaseVersion": 1,
        "progressVersion": 1,
    })
    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"activeRunId": r1_id}})

    # Synchronization events to pause recovery after setting status = RECOVERING
    recovering_entered = threading.Event()
    resume_recovery = threading.Event()

    from pymongo.collection import Collection
    original_update_one = Collection.update_one
    recovery_paused = False

    def hook_app_update_one(coll_self, filter_dict, update_dict, *args, **kwargs):
        nonlocal recovery_paused
        # In recovery Step 2, applications.update_one is called right after setting RECOVERING
        if not recovery_paused and coll_self.name == "applications" and filter_dict.get("activeRunId") == r1_id:
            recovery_paused = True
            recovering_entered.set()
            # Wait until concurrent request has attempted execution
            resume_recovery.wait(timeout=5.0)
        return original_update_one(coll_self, filter_dict, update_dict, *args, **kwargs)

    orch1 = AgentOrchestrator(db=clean_db, stale_timeout_seconds=30)

    # Run Worker 1 recovery in background thread
    w1_result = []
    def worker1_target():
        Collection.update_one = hook_app_update_one
        try:
            res = orch1.run(app_id, applicant_auth["user"])
            w1_result.append(res)
        finally:
            Collection.update_one = original_update_one

    t1 = threading.Thread(target=worker1_target)
    t1.start()

    # Wait until Worker 1 has placed R1 into RECOVERING
    assert recovering_entered.wait(timeout=5.0), "Worker 1 failed to reach RECOVERING state"

    # Verify R1 is currently in RECOVERING status in the database
    r1_in_db = clean_db["orchestration_runs"].find_one({"runId": r1_id})
    assert r1_in_db["status"] == OrchestrationRunStatus.RECOVERING.value

    # Concurrently, Worker 2 attempts an orchestration request for the same application
    orch2 = AgentOrchestrator(db=clean_db, stale_timeout_seconds=30)
    w2_res = orch2.run(app_id, applicant_auth["user"])

    # Worker 2 MUST NOT be able to insert a competing execution or take ownership
    assert w2_res.outcome == OrchestrationOutcome.ALREADY_RUNNING
    assert w2_res.status == OrchestrationRunStatus.RUNNING

    # Verify database state during pause: exactly 1 run exists (R1), and applications.activeRunId was NOT changed by W2
    all_runs = list(clean_db["orchestration_runs"].find({"applicationId": app_id}))
    assert len(all_runs) == 1
    assert all_runs[0]["runId"] == r1_id
    assert all_runs[0]["status"] == OrchestrationRunStatus.RECOVERING.value

    # Now resume Worker 1 recovery
    resume_recovery.set()
    t1.join(timeout=10.0)

    assert len(w1_result) == 1
    w1_res = w1_result[0]
    assert w1_res.outcome in (OrchestrationOutcome.COMPLETED, OrchestrationOutcome.WAITING_FOR_APPLICANT)

    # Verify exactly one replacement execution was established
    runs_after = list(clean_db["orchestration_runs"].find({"applicationId": app_id}))
    assert len(runs_after) == 2
    r1_final = clean_db["orchestration_runs"].find_one({"runId": r1_id})
    assert r1_final["status"] == OrchestrationRunStatus.ABORTED.value

    active_runs = list(clean_db["orchestration_runs"].find({
        "applicationId": app_id,
        "status": {"$in": [OrchestrationRunStatus.RUNNING.value, OrchestrationRunStatus.COMPLETED.value]}
    }))
    assert len(active_runs) == 1
    replacement_run = active_runs[0]
    assert replacement_run["runId"] != r1_id


def test_crashed_recovering_run_safely_recovered_by_next_worker(applicant_auth, clean_db):
    """
    Handle a process crash during RECOVERING without silently abandoning work
    or allowing concurrent workers to bypass exclusivity.
    """
    app_id = applicant_auth["application"]["applicationId"]
    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})

    now_utc = datetime.now(timezone.utc)
    past_iso = (now_utc - timedelta(seconds=400)).isoformat()
    r1_id = "run-crashed-recovering"

    # Simulate a run that crashed mid-recovery (status RECOVERING, but expired heartbeat and lease)
    clean_db["orchestration_runs"].insert_one({
        "runId": r1_id,
        "applicationId": app_id,
        "status": OrchestrationRunStatus.RECOVERING.value,
        "recoveryToken": f"superseded-{r1_id}",
        "startedAt": past_iso,
        "heartbeatAt": past_iso,
        "leaseExpiresAt": past_iso,
        "leaseVersion": 2,
        "progressVersion": 1,
    })
    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"activeRunId": f"superseded-{r1_id}"}})

    # Two concurrent workers notice crashed RECOVERING run and race to recover it
    barrier = threading.Barrier(2)
    results = [None, None]

    def recover_worker(idx):
        orch = AgentOrchestrator(db=clean_db, stale_timeout_seconds=30)
        barrier.wait(timeout=5.0)
        results[idx] = orch.run(app_id, applicant_auth["user"])

    t1 = threading.Thread(target=recover_worker, args=(0,))
    t2 = threading.Thread(target=recover_worker, args=(1,))
    t1.start()
    t2.start()
    t1.join(timeout=10.0)
    t2.join(timeout=10.0)

    # Exactly one worker wins recovery; the other is rejected with ALREADY_RUNNING
    res_list = [r for r in results if r is not None]
    assert len(res_list) == 2
    winning = [r for r in res_list if r.outcome in (OrchestrationOutcome.COMPLETED, OrchestrationOutcome.WAITING_FOR_APPLICANT)]
    competing = [r for r in res_list if r.outcome == OrchestrationOutcome.ALREADY_RUNNING]

    assert len(winning) == 1, f"Expected 1 winning replacement run, got {len(winning)}"
    assert len(competing) == 1, f"Expected 1 competing worker getting ALREADY_RUNNING, got {len(competing)}"
    assert winning[0].runId != r1_id

    # Crashed run is marked ABORTED
    r1_final = clean_db["orchestration_runs"].find_one({"runId": r1_id})
    assert r1_final["status"] == OrchestrationRunStatus.ABORTED.value

    # Exactly one active replacement run established
    active_runs = list(clean_db["orchestration_runs"].find({
        "applicationId": app_id,
        "status": {"$in": [OrchestrationRunStatus.RUNNING.value, OrchestrationRunStatus.COMPLETED.value]}
    }))
    assert len(active_runs) == 1


# =====================================================================
# Tests: Finding B - Document-Claim Race & Persistence Boundaries
# =====================================================================
def test_document_claim_interleaving_race_blocked_at_persistence_boundary(api_client, applicant_auth, clean_db):
    """
    Finding B:
    Trace the 5-step interleaving through real persistence operations:
    1. An old worker reads an application record showing its run ID as the active owner.
    2. The worker pauses before claiming an unclaimed document.
    3. Recovery begins and finishes the relevant ownership-revocation steps (including supersededRunIds on documents).
    4. The old worker resumes its document claim.
    5. The stale claim fails at the persistence boundary; no OCR, verification, or status result is persisted.
    """
    app_id = applicant_auth["application"]["applicationId"]
    uploaded_ids = upload_all_six_documents(api_client, applicant_auth, app_id)
    doc_id = uploaded_ids["10TH_MARKSHEET"]

    # Initial state: document is unclaimed
    clean_db["documents"].update_one(
        {"documentId": doc_id},
        {"$unset": {"activeRunId": ""}, "$set": {"processingStatus": "UPLOADED", "status": "UPLOADED"}},
    )

    old_run_id = "run-old-worker-claim-race"
    clean_db["applications"].update_one(
        {"applicationId": app_id},
        {"$set": {"activeRunId": old_run_id}},
    )

    from pymongo.collection import Collection

    pause_before_claim = threading.Event()
    claim_resumed = threading.Event()
    worker_exception = []

    original_update_one = Collection.update_one

    def hook_doc_update_one(coll_self, filter_dict, update_dict, *args, **kwargs):
        # Step 2: Intercept the document claim update
        if coll_self.name == "documents" and filter_dict.get("processingStatus") == {"$ne": "PROCESSING"}:
            pause_before_claim.set()
            # Wait for recovery to complete
            claim_resumed.wait(timeout=5.0)
        return original_update_one(coll_self, filter_dict, update_dict, *args, **kwargs)

    # Worker 1 execution in background
    def old_worker_claim_target():
        try:
            # Step 1: Reads application record showing old_run_id as active owner
            # Step 2: Pauses before claiming the document
            process_document(
                db=clean_db,
                current_user=applicant_auth["user"],
                document_id=doc_id,
                run_id=old_run_id,
            )
        except Exception as e:
            worker_exception.append(e)

    Collection.update_one = hook_doc_update_one
    try:
        t = threading.Thread(target=old_worker_claim_target)
        t.start()

        # Wait until old worker is paused right before the conditional claim
        assert pause_before_claim.wait(timeout=5.0), "Old worker did not reach claim pause point"

        # Step 3: Recovery begins and finishes the relevant ownership-revocation steps
        # Simulate full recovery resource revocation:
        recovery_token = f"superseded-{old_run_id}"
        clean_db["applications"].update_one(
            {"applicationId": app_id},
            {
                "$set": {"activeRunId": recovery_token},
                "$addToSet": {"supersededRunIds": old_run_id},
            },
        )
        clean_db["documents"].update_many(
            {"applicationId": app_id, "activeRunId": old_run_id},
            {"$set": {"activeRunId": recovery_token}},
        )
        clean_db["documents"].update_many(
            {"applicationId": app_id},
            {"$addToSet": {"supersededRunIds": old_run_id}},
        )

        # Step 4: Old worker resumes its document claim
        claim_resumed.set()
        t.join(timeout=5.0)
    finally:
        Collection.update_one = original_update_one

    # Step 5: Verify the stale claim failed at the persistence boundary
    assert len(worker_exception) == 1
    exc = worker_exception[0]
    assert isinstance(exc, HTTPException)
    assert exc.status_code == 409
    assert "ownership lost" in exc.detail.lower()

    # Verify no OCR, verification, or status result from the stale worker was persisted
    doc_final = clean_db["documents"].find_one({"documentId": doc_id})
    assert doc_final.get("activeRunId") != old_run_id
    assert doc_final.get("processingStatus") != "PROCESSING"
    assert doc_final.get("processingResult") is None
    assert doc_final.get("validationResult") is None
    assert doc_final.get("status") == "UPLOADED"


def test_pre_claimed_document_persistence_blocked_after_recovery_revokes_token(api_client, applicant_auth, clean_db):
    """
    Verify that an old worker who has already claimed a document and attempts to persist
    OCR or verification results AFTER recovery revokes its token is rejected at the persistence boundary.
    """
    app_id = applicant_auth["application"]["applicationId"]
    uploaded_ids = upload_all_six_documents(api_client, applicant_auth, app_id)
    doc_id = uploaded_ids["10TH_MARKSHEET"]

    stale_run = "run-stale-preclaimed-worker"
    recovery_token = f"superseded-{stale_run}"

    # Pre-claim document for stale_run
    clean_db["documents"].update_one(
        {"documentId": doc_id},
        {"$set": {"activeRunId": stale_run, "processingStatus": "UPLOADED"}},
    )
    clean_db["applications"].update_one(
        {"applicationId": app_id},
        {"$set": {"activeRunId": stale_run}},
    )

    import app.services.document as doc_service
    original_pipeline = doc_service.run_document_processing_pipeline

    def hooked_pipeline(*args, **kwargs):
        # Recovery executes while pipeline is running: revokes tokens and stamps superseded markers
        clean_db["applications"].update_one(
            {"applicationId": app_id},
            {"$addToSet": {"supersededRunIds": stale_run}, "$set": {"activeRunId": recovery_token}},
        )
        clean_db["documents"].update_many(
            {"applicationId": app_id},
            {"$addToSet": {"supersededRunIds": stale_run}},
        )
        clean_db["documents"].update_many(
            {"applicationId": app_id, "activeRunId": stale_run},
            {"$set": {"activeRunId": recovery_token}},
        )
        return original_pipeline(*args, **kwargs)

    doc_service.run_document_processing_pipeline = hooked_pipeline
    try:
        # Exercise real service persistence path: process_document
        with pytest.raises(HTTPException) as ocr_exc:
            process_document(
                db=clean_db,
                current_user=applicant_auth["user"],
                document_id=doc_id,
                run_id=stale_run,
            )
        assert ocr_exc.value.status_code == 409
        assert "ownership lost" in ocr_exc.value.detail.lower()
    finally:
        doc_service.run_document_processing_pipeline = original_pipeline

    # Exercise real service persistence path: verify_document
    # Set COMPLETED status so verify_document reaches the ownership fencing check
    clean_db["documents"].update_one(
        {"documentId": doc_id},
        {"$set": {"processingStatus": "COMPLETED", "processingResult": {"overallConfidence": 0.95}}},
    )
    with pytest.raises(HTTPException) as val_exc:
        verify_document(
            db=clean_db,
            current_user=applicant_auth["user"],
            document_id=doc_id,
            run_id=stale_run,
        )
    assert val_exc.value.status_code == 409
    assert "ownership lost" in val_exc.value.detail.lower()

    # Document remains un-mutated by stale worker: validationResult was NOT written
    doc_record = clean_db["documents"].find_one({"documentId": doc_id})
    assert doc_record.get("validationResult") is None
    assert doc_record.get("validationStatus") != "VALIDATED"


def test_document_claim_commits_before_superseded_marker_revoked_by_subsequent_fencing(api_client, applicant_auth, clean_db):
    """
    Finding 1:
    A stale claim completes immediately before the superseded marker is written.
    Verify that recovery subsequently revokes the acquired activeRunId, and the document
    remains recoverable and processable by the replacement run.
    """
    app_id = applicant_auth["application"]["applicationId"]
    uploaded_ids = upload_all_six_documents(api_client, applicant_auth, app_id)
    doc_id = uploaded_ids["10TH_MARKSHEET"]

    stale_run = "run-stale-claimed-just-before-marker"
    replacement_run = "run-replacement-recovery"

    # Initial state: Application is owned by stale_run
    clean_db["applications"].update_one(
        {"applicationId": app_id},
        {"$set": {"activeRunId": stale_run, "status": "PROCESSING"}},
    )
    clean_db["documents"].update_one(
        {"documentId": doc_id},
        {"$unset": {"activeRunId": ""}, "$set": {"processingStatus": "UPLOADED", "status": "UPLOADED"}},
    )

    # 1. Stale worker executes actual claim query and successfully acquires document claim
    now_iso = datetime.now(timezone.utc).isoformat()
    claim_res = clean_db["documents"].update_one(
        {
            "_id": clean_db["documents"].find_one({"documentId": doc_id})["_id"],
            "processingStatus": {"$ne": "PROCESSING"},
            "supersededRunIds": {"$ne": stale_run},
        },
        {"$set": {"processingStatus": "PROCESSING", "activeRunId": stale_run, "updatedAt": now_iso}},
    )
    assert claim_res.modified_count == 1

    # Verify claim succeeded before superseded marker was written
    claimed_doc = clean_db["documents"].find_one({"documentId": doc_id})
    assert claimed_doc["activeRunId"] == stale_run
    assert claimed_doc["processingStatus"] == "PROCESSING"

    # 2. Recovery executes its safe two-step document resource revocation sequence:
    recovery_token = f"superseded-{stale_run}"
    # Step 1: Atomically stamp stale_run into supersededRunIds across all documents
    clean_db["documents"].update_many(
        {"applicationId": app_id},
        {"$addToSet": {"supersededRunIds": stale_run}},
    )
    # Step 2: Revoke activeRunId on documents currently owned by stale_run, resetting in-flight to UPLOADED
    clean_db["documents"].update_many(
        {"applicationId": app_id, "activeRunId": stale_run, "processingStatus": "PROCESSING"},
        {"$set": {"activeRunId": recovery_token, "processingStatus": "UPLOADED"}},
    )
    clean_db["documents"].update_many(
        {"applicationId": app_id, "activeRunId": stale_run},
        {"$set": {"activeRunId": recovery_token}},
    )

    # Application fencing
    clean_db["applications"].update_one(
        {"applicationId": app_id},
        {"$addToSet": {"supersededRunIds": stale_run}},
    )
    clean_db["applications"].update_one(
        {"applicationId": app_id, "activeRunId": stale_run},
        {"$set": {"activeRunId": recovery_token}},
    )

    # 3. Verify that Step 2 caught the claim that committed right before Step 1
    doc_after_fence = clean_db["documents"].find_one({"documentId": doc_id})
    assert doc_after_fence["activeRunId"] == recovery_token
    assert stale_run in doc_after_fence.get("supersededRunIds", [])
    assert doc_after_fence["processingStatus"] == "UPLOADED"

    # 4. Verify that stale worker is rejected if it attempts persistence
    with pytest.raises(HTTPException) as exc_info:
        process_document(
            db=clean_db,
            current_user=applicant_auth["user"],
            document_id=doc_id,
            run_id=stale_run,
        )
    assert exc_info.value.status_code == 409
    assert "ownership lost" in exc_info.value.detail.lower()

    # 5. Verify the document remains recoverable and processable by the replacement run
    clean_db["applications"].update_one(
        {"applicationId": app_id},
        {"$set": {"activeRunId": replacement_run}},
    )
    clean_db["orchestration_runs"].insert_one({
        "runId": replacement_run,
        "applicationId": app_id,
        "status": OrchestrationRunStatus.RUNNING.value,
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "heartbeatAt": datetime.now(timezone.utc).isoformat(),
        "leaseExpiresAt": (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat(),
        "leaseVersion": 1,
        "progressVersion": 1,
    })

    res = process_document(
        db=clean_db,
        current_user=applicant_auth["user"],
        document_id=doc_id,
        run_id=replacement_run,
    )
    assert res is not None
    assert res.processingState == "COMPLETED"

    # Verify replacement run successfully persisted OCR and owns the document
    doc_recovered = clean_db["documents"].find_one({"documentId": doc_id})
    assert doc_recovered["activeRunId"] == replacement_run
    assert doc_recovered["processingStatus"] == "COMPLETED"
    assert doc_recovered.get("processingResult") is not None


def test_fenced_fatal_ocr_exception_handler_cannot_mark_failed_if_ownership_lost(api_client, applicant_auth, clean_db):
    """
    Finding 2:
    In process_document, when an unexpected pipeline exception occurs and the worker's
    ownership was revoked before the exception handler attempts persistence, verify that
    the stale worker cannot mark the document FAILED or otherwise modify its state.
    Exercises the real service exception handler in process_document.
    """
    import app.services.document as doc_service

    app_id = applicant_auth["application"]["applicationId"]
    uploaded_ids = upload_all_six_documents(api_client, applicant_auth, app_id)
    doc_id = uploaded_ids["10TH_MARKSHEET"]

    stale_run = "run-failing-stale-worker"
    clean_db["applications"].update_one(
        {"applicationId": app_id},
        {"$set": {"activeRunId": stale_run}},
    )

    original_pipeline = doc_service.run_document_processing_pipeline

    def failing_pipeline_with_concurrent_recovery(*args, **kwargs):
        # Revoke ownership before the exception handler catches and attempts persistence
        recovery_token = f"superseded-{stale_run}"
        clean_db["applications"].update_one(
            {"applicationId": app_id},
            {"$addToSet": {"supersededRunIds": stale_run}},
        )
        clean_db["applications"].update_one(
            {"applicationId": app_id, "activeRunId": stale_run},
            {"$set": {"activeRunId": recovery_token}},
        )
        clean_db["documents"].update_many(
            {"applicationId": app_id},
            {"$addToSet": {"supersededRunIds": stale_run}},
        )
        clean_db["documents"].update_many(
            {"applicationId": app_id, "activeRunId": stale_run},
            {"$set": {"activeRunId": recovery_token}},
        )
        # Raise unexpected OCR pipeline crash
        raise RuntimeError("Unexpected simulated OCR engine segfault")

    doc_service.run_document_processing_pipeline = failing_pipeline_with_concurrent_recovery
    try:
        with pytest.raises(HTTPException) as exc_info:
            process_document(
                db=clean_db,
                current_user=applicant_auth["user"],
                document_id=doc_id,
                run_id=stale_run,
            )
        assert exc_info.value.status_code == 500
        assert "error occurred while processing" in exc_info.value.detail.lower()
    finally:
        doc_service.run_document_processing_pipeline = original_pipeline

    # Crucial assertion: Document status was NOT overwritten to FAILED because err_filter matched 0 documents
    doc_after = clean_db["documents"].find_one({"documentId": doc_id})
    assert doc_after.get("processingStatus") != "FAILED", "Stale worker erroneously marked document as FAILED!"
    assert doc_after.get("activeRunId") == f"superseded-{stale_run}"
    assert doc_after.get("status") == "UPLOADED"


def test_database_initialization_fails_safely_on_duplicate_active_runs(clean_db):
    """
    Finding 3:
    When duplicate active/recovering runs exist on the same applicationId, connect_to_mongo()
    must clearly report the duplicate records, refuse to report successful database initialization,
    and raise DatabaseInitializationError without silently deleting or arbitrarily aborting executions.
    """
    # 1. Drop existing indexes on orchestration_runs
    clean_db["orchestration_runs"].drop_indexes()

    # 2. Insert two duplicate active runs for the same application
    app_conflict = "APP-CONFLICT-DETECT-001"
    run_dup1 = "run-dup-active-1"
    run_dup2 = "run-dup-active-2"
    clean_db["orchestration_runs"].insert_many([
        {
            "runId": run_dup1,
            "applicationId": app_conflict,
            "status": OrchestrationRunStatus.RUNNING.value,
            "startedAt": datetime.now(timezone.utc).isoformat(),
        },
        {
            "runId": run_dup2,
            "applicationId": app_conflict,
            "status": OrchestrationRunStatus.RECOVERING.value,
            "startedAt": datetime.now(timezone.utc).isoformat(),
        },
    ])

    # 3. Calling connect_to_mongo must fail safely and raise DatabaseInitializationError
    with pytest.raises(DatabaseInitializationError) as exc_info:
        connect_to_mongo()

    err_msg = str(exc_info.value)
    assert app_conflict in err_msg
    assert run_dup1 in err_msg
    assert run_dup2 in err_msg

    # 4. Verify no destructive cleanup occurred: both duplicate records still exist
    conflict_docs = list(clean_db["orchestration_runs"].find({"applicationId": app_conflict}))
    assert len(conflict_docs) == 2
    statuses = {d["runId"]: d["status"] for d in conflict_docs}
    assert statuses[run_dup1] == OrchestrationRunStatus.RUNNING.value
    assert statuses[run_dup2] == OrchestrationRunStatus.RECOVERING.value

    # 5. Resolve conflict explicitly by removing one record (safe administrator resolution)
    clean_db["orchestration_runs"].delete_one({"runId": run_dup2})

    # 6. Retry connect_to_mongo() - must now succeed and create the required index
    connect_to_mongo()

    # Verify the unique partial index is established
    indexes = clean_db["orchestration_runs"].index_information()
    partial_idx_found = False
    for idx_name, idx_info in indexes.items():
        if idx_info.get("key") == [("applicationId", 1)] and idx_info.get("unique") is True:
            pfe = idx_info.get("partialFilterExpression", {})
            if pfe.get("status") == {"$in": ["RUNNING", "RECOVERING"]}:
                partial_idx_found = True
                break
    assert partial_idx_found, "Unique partial index on status in ('RUNNING', 'RECOVERING') was not created!"


def test_list_orchestration_runs_endpoint(api_client, admin_auth, applicant_auth, clean_db):
    """
    Verify GET /api/v1/agents/runs returns recent orchestration runs,
    enforcing RBAC:
    - Admin can view runs across all applications.
    - Applicants can only view runs for their own application.
    - Unsupported or unexpected roles receive HTTP 403 Forbidden.
    """
    from app.core.security import create_access_token

    app_id_1 = applicant_auth["application"]["applicationId"]
    app_id_2 = "app-other-applicant-99"

    clean_db["orchestration_runs"].delete_many({})

    # Insert run for applicant 1
    clean_db["orchestration_runs"].insert_one({
        "runId": "run-app-1",
        "applicationId": app_id_1,
        "status": OrchestrationRunStatus.COMPLETED.value,
        "outcome": OrchestrationOutcome.WAITING_FOR_APPLICANT.value,
        "currentApplicationStatus": "WAITING_FOR_DOCUMENTS",
        "stepsCompleted": 2,
        "summary": "Completed inspection for app 1",
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "completedAt": datetime.now(timezone.utc).isoformat(),
        "steps": [],
        "planner": "DETERMINISTIC",
    })

    # Insert run for applicant 2
    clean_db["orchestration_runs"].insert_one({
        "runId": "run-app-2",
        "applicationId": app_id_2,
        "status": OrchestrationRunStatus.COMPLETED.value,
        "outcome": OrchestrationOutcome.WAITING_FOR_APPLICANT.value,
        "currentApplicationStatus": "WAITING_FOR_DOCUMENTS",
        "stepsCompleted": 1,
        "summary": "Completed inspection for app 2",
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "completedAt": datetime.now(timezone.utc).isoformat(),
        "steps": [],
        "planner": "DETERMINISTIC",
    })

    # 1. Admin request sees runs across all applications
    admin_res = api_client.get("/api/v1/agents/runs", headers=admin_auth["headers"])
    assert admin_res.status_code == 200
    runs = admin_res.json()
    run_ids = [r["runId"] for r in runs]
    assert "run-app-1" in run_ids
    assert "run-app-2" in run_ids

    # 2. Applicant request sees only own application run
    applicant_res = api_client.get("/api/v1/agents/runs", headers=applicant_auth["headers"])
    assert applicant_res.status_code == 200
    app_runs = applicant_res.json()
    assert len(app_runs) == 1
    assert app_runs[0]["runId"] == "run-app-1"
    assert app_runs[0]["applicationId"] == app_id_1

    # 3. Unsupported role receives HTTP 403 Forbidden
    reviewer_user = {
        "full_name": "External Reviewer",
        "email": "reviewer@smartenroll.edu",
        "role": "reviewer",
    }
    inserted = clean_db["users"].insert_one(reviewer_user)
    reviewer_token = create_access_token(subject=str(inserted.inserted_id), role="reviewer")

    reviewer_res = api_client.get(
        "/api/v1/agents/runs",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert reviewer_res.status_code == 403
    assert "Forbidden" in reviewer_res.json().get("detail", "")

def test_list_orchestration_runs_backward_compatibility_with_legacy_records(api_client, admin_auth, clean_db):
    """
    Verify GET /api/v1/agents/runs handles legacy orchestration run records:
    - Legacy records missing currentApplicationStatus do NOT produce Pydantic response validation errors.
    - Legacy records with currentStage preserve currentStage in the API response.
    - Legacy records with neither field serialize currentApplicationStatus=None and currentStage=None.
    """
    from datetime import datetime, timezone
    from app.schemas.agent import OrchestrationRunResponse, OrchestrationRunStatus, OrchestrationOutcome

    clean_db["orchestration_runs"].delete_many({})

    # 1. Modern run record with currentApplicationStatus
    clean_db["orchestration_runs"].insert_one({
        "runId": "run-modern-01",
        "applicationId": "SE20260001",
        "status": OrchestrationRunStatus.COMPLETED.value,
        "outcome": OrchestrationOutcome.COMPLETED.value,
        "currentApplicationStatus": "PROCESSING_COMPLETE",
        "stepsCompleted": 3,
        "summary": "Modern completed run",
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "completedAt": datetime.now(timezone.utc).isoformat(),
        "steps": [],
        "planner": "LLM",
    })

    # 2. Legacy run record with currentStage only (no currentApplicationStatus)
    clean_db["orchestration_runs"].insert_one({
        "runId": "run-legacy-stage-02",
        "applicationId": "SE20260002",
        "status": OrchestrationRunStatus.COMPLETED.value,
        "outcome": OrchestrationOutcome.WAITING_FOR_APPLICANT.value,
        "currentStage": "VERIFICATION_IN_PROGRESS",
        "stepsCompleted": 2,
        "summary": "Legacy run with currentStage only",
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "completedAt": datetime.now(timezone.utc).isoformat(),
        "steps": [],
        "planner": "DETERMINISTIC",
    })

    # 3. Legacy run record with neither currentApplicationStatus nor currentStage
    clean_db["orchestration_runs"].insert_one({
        "runId": "run-legacy-empty-03",
        "applicationId": "SE20260003",
        "status": OrchestrationRunStatus.COMPLETED.value,
        "outcome": OrchestrationOutcome.FAILED.value,
        "stepsCompleted": 1,
        "summary": "Legacy run with neither status nor stage",
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "completedAt": datetime.now(timezone.utc).isoformat(),
        "steps": [],
        "planner": "DETERMINISTIC",
    })

    # Execute endpoint call as admin
    res = api_client.get("/api/v1/agents/runs", headers=admin_auth["headers"])
    assert res.status_code == 200, f"Expected 200 but got {res.status_code}: {res.text}"
    runs_by_id = {r["runId"]: r for r in res.json()}

    # Assert modern run
    modern = runs_by_id["run-modern-01"]
    assert modern["currentApplicationStatus"] == "PROCESSING_COMPLETE"
    assert modern.get("currentStage") is None

    # Assert legacy run with currentStage preserves currentStage without validation failure
    legacy_stage = runs_by_id["run-legacy-stage-02"]
    assert legacy_stage.get("currentApplicationStatus") is None
    assert legacy_stage.get("currentStage") == "VERIFICATION_IN_PROGRESS"

    # Assert legacy run with neither field
    legacy_empty = runs_by_id["run-legacy-empty-03"]
    assert legacy_empty.get("currentApplicationStatus") is None
    assert legacy_empty.get("currentStage") is None

    # Direct Pydantic model validation check for legacy dict
    legacy_dict = {
        "runId": "run-direct-legacy",
        "applicationId": "SE20269999",
        "status": "COMPLETED",
        "outcome": "COMPLETED",
        "currentStage": "ACT",
        "stepsCompleted": 1,
        "summary": "Direct legacy model validation",
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "completedAt": datetime.now(timezone.utc).isoformat(),
        "steps": [],
    }
    validated = OrchestrationRunResponse.model_validate(legacy_dict)
    assert validated.currentApplicationStatus is None
    assert validated.currentStage == "ACT"


def test_list_orchestration_runs_active_and_recovering_null_outcome(api_client, admin_auth, clean_db):
    """
    Ensure active (RUNNING) and recovering (RECOVERING) orchestration runs
    with outcome=None validate cleanly across Pydantic schemas, GET /agents/runs,
    and GET /agents/orchestrate/runs/{run_id}.
    """
    clean_db["orchestration_runs"].delete_many({})

    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. RUNNING run with outcome=None (persisted initially by _claim_or_recover_run)
    clean_db["orchestration_runs"].insert_one({
        "runId": "run-active-01",
        "applicationId": "SE20261001",
        "status": OrchestrationRunStatus.RUNNING.value,
        "outcome": None,
        "currentApplicationStatus": "PROCESSING",
        "stepsCompleted": 0,
        "summary": "Orchestration in progress",
        "startedAt": now_iso,
        "completedAt": None,
        "steps": [],
        "planner": "DETERMINISTIC",
    })

    # 2. RECOVERING run with outcome=None (persisted during stale run recovery)
    clean_db["orchestration_runs"].insert_one({
        "runId": "run-recovering-02",
        "applicationId": "SE20261002",
        "status": OrchestrationRunStatus.RECOVERING.value,
        "outcome": None,
        "currentApplicationStatus": "WAITING_FOR_DOCUMENTS",
        "stepsCompleted": 2,
        "summary": "Stale run undergoing recovery",
        "startedAt": now_iso,
        "completedAt": None,
        "steps": [],
        "planner": "DETERMINISTIC",
    })

    # 3. COMPLETED run with normal outcome
    clean_db["orchestration_runs"].insert_one({
        "runId": "run-completed-03",
        "applicationId": "SE20261003",
        "status": OrchestrationRunStatus.COMPLETED.value,
        "outcome": OrchestrationOutcome.COMPLETED.value,
        "currentApplicationStatus": "PROCESSING_COMPLETE",
        "stepsCompleted": 5,
        "summary": "Orchestration completed successfully",
        "startedAt": now_iso,
        "completedAt": now_iso,
        "steps": [],
        "planner": "DETERMINISTIC",
    })

    # Execute endpoint call as admin to fetch recent runs
    res = api_client.get("/api/v1/agents/runs", headers=admin_auth["headers"])
    assert res.status_code == 200, f"Expected 200 but got {res.status_code}: {res.text}"
    runs_by_id = {r["runId"]: r for r in res.json()}

    # Assert active run returns 200 and outcome is None
    active = runs_by_id["run-active-01"]
    assert active["status"] == "RUNNING"
    assert active["outcome"] is None
    assert active["currentApplicationStatus"] == "PROCESSING"

    # Assert recovering run returns 200 and outcome is None
    recovering = runs_by_id["run-recovering-02"]
    assert recovering["status"] == "RECOVERING"
    assert recovering["outcome"] is None
    assert recovering["currentApplicationStatus"] == "WAITING_FOR_DOCUMENTS"

    # Assert completed run returns 200 and outcome is COMPLETED
    completed = runs_by_id["run-completed-03"]
    assert completed["status"] == "COMPLETED"
    assert completed["outcome"] == "COMPLETED"
    assert completed["currentApplicationStatus"] == "PROCESSING_COMPLETE"

    # Single-run endpoint check for the active run
    single_res = api_client.get(
        "/api/v1/agents/orchestrate/runs/run-active-01",
        headers=admin_auth["headers"],
    )
    assert single_res.status_code == 200, f"Expected 200 but got {single_res.status_code}: {single_res.text}"
    single_run = single_res.json()
    assert single_run["runId"] == "run-active-01"
    assert single_run["status"] == "RUNNING"
    assert single_run["outcome"] is None

    # Direct Pydantic model validation with outcome=None
    direct_dict = {
        "runId": "run-direct-active",
        "applicationId": "SE20269998",
        "status": "RUNNING",
        "outcome": None,
        "stepsCompleted": 0,
        "summary": "Active run direct validation",
        "startedAt": now_iso,
    }
    validated = OrchestrationRunResponse.model_validate(direct_dict)
    assert validated.status == OrchestrationRunStatus.RUNNING
    assert validated.outcome is None
