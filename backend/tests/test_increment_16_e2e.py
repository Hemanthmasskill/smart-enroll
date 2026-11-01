from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from app.agents.llm_planner import ApplicationObservation, LLMPlanProposal, LLMPlanningStrategy
from app.agents.orchestrator import AgentOrchestrator
from app.agents.tools import tool_check_eligibility, tool_update_application_status
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.schemas.agent import OrchestrationOutcome, ToolName, ToolStatus
from app.services.eligibility.service import run_eligibility_evaluation
from app.services.programme_rules import seed_programme_rules
from tests.test_agent_orchestration import create_sample_pdf_bytes, upload_all_six_documents


@pytest.fixture(autouse=True)
def disable_llm_provider_for_orchestration_tests(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "disabled")


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
    db["agent_activity"].delete_many({})
    db["orchestration_runs"].delete_many({})
    db["eligibility_evaluations"].delete_many({})
    db["programme_rules"].delete_many({})
    seed_programme_rules(db)
    yield db


def setup_applicant_with_application(client, email="hemanth.inc16@example.com", prog_id="mca", cgpa=8.5):
    reg = client.post(
        f"{settings.API_V1_STR}/auth/register",
        json={
            "fullName": "Hemanth M.P.",
            "email": email,
            "mobile": "9876543210",
            "dob": "2000-05-15",
            "password": "Password123!",
        },
    )
    assert reg.status_code == 201
    auth_data = reg.json()

    create_res = client.post(
        f"{settings.API_V1_STR}/applications",
        headers={"Authorization": f"Bearer {auth_data['token']}"},
        json={
            "programmeId": prog_id,
            "fullName": "Hemanth M.P.",
            "dob": "2000-05-15",
            "gender": "Male",
            "nationality": "Indian",
            "address": "456 Knowledge Park",
            "tenthPercentage": 86.4,
            "twelfthPercentage": 88.0,
            "ugDegree": "BCA",
            "cgpa": cgpa,
            "university": "Crescent",
            "graduationYear": 2022,
        },
    )
    assert create_res.status_code == 201
    app_data = create_res.json()

    db = get_db()
    user_doc = db["users"].find_one({"email": email})
    admin_user = {"role": "admin", "id": "admin-system", "sub": "admin-system"}

    return {
        "client": client,
        "token": auth_data["token"],
        "headers": {"Authorization": f"Bearer {auth_data['token']}"},
        "app_id": app_data["applicationId"],
        "user": user_doc,
        "admin_user": admin_user,
    }


# =============================================================================
# D9 Stale Protection Tests
# =============================================================================
def test_eligibility_stale_protection_document_tampering_rejected(client, clean_db):
    """
    Apply D9: The ELIGIBLE or INELIGIBLE transition is accepted only if inputHash
    equals a fresh hash of the current application and documents.
    If a document is modified after evaluation, the transition must be rejected.
    """
    ctx = setup_applicant_with_application(client, email="stale.test@example.com")
    app_id = ctx["app_id"]
    upload_all_six_documents(client, ctx, app_id, include_math=True)

    # Populate valid extracted fields on documents to pass gates & evaluate as ELIGIBLE
    clean_db["documents"].update_many(
        {"applicationId": app_id},
        {"$set": {"status": "VALIDATED", "processingStatus": "COMPLETED", "validationStatus": "VALIDATED", "extractedFields": {}}},
    )
    clean_db["documents"].update_one(
        {"applicationId": app_id, "documentType": "UG_MARKSHEET"},
        {"$set": {"extractedFields": {"percentage": {"normalizedValue": 80.0}, "course": {"normalizedValue": "BCA"}}}},
    )
    clean_db["documents"].update_one(
        {"applicationId": app_id, "documentType": "12TH_MARKSHEET"},
        {"$set": {"extractedFields": {"mathematics": {"normalizedValue": True, "matchedLine": "Mathematics 95"}}}},
    )
    clean_db["documents"].update_one(
        {"applicationId": app_id, "documentType": "DEGREE_CERTIFICATE"},
        {"$set": {"extractedFields": {"course": {"normalizedValue": "Bachelor of Computer Applications"}}}},
    )

    # Transition to ELIGIBILITY_CHECK
    for stage in ["SUBMITTED", "PROCESSING", "VERIFICATION_IN_PROGRESS", "ELIGIBILITY_CHECK"]:
        res = tool_update_application_status(clean_db, ctx["admin_user"], app_id, stage)
        assert res.status == ToolStatus.COMPLETED.value

    # Run deterministic eligibility evaluation
    eval_res = run_eligibility_evaluation(clean_db, ctx["admin_user"], app_id)
    assert eval_res.status == "ELIGIBLE"

    # Status update to ELIGIBLE succeeds with fresh matching hash
    res_eligible = tool_update_application_status(clean_db, ctx["admin_user"], app_id, "ELIGIBLE")
    assert res_eligible.status == ToolStatus.COMPLETED.value

    # Reset status back to ELIGIBILITY_CHECK for stale test
    clean_db["applications"].update_one(
        {"applicationId": app_id},
        {"$set": {"status": "ELIGIBILITY_CHECK"}},
    )

    # Tamper with UG_MARKSHEET document data
    clean_db["documents"].update_one(
        {"applicationId": app_id, "documentType": "UG_MARKSHEET"},
        {"$set": {"extractedFields.percentage.normalizedValue": 42.0}},
    )

    # Attempt transition to ELIGIBLE: must be rejected with stale evaluation error (D9)
    res_stale = tool_update_application_status(clean_db, ctx["admin_user"], app_id, "ELIGIBLE")
    assert res_stale.status == ToolStatus.FAILED.value
    assert "stale" in res_stale.message.lower()


# =============================================================================
# Orchestrator End-to-End Tests
# =============================================================================
def test_orchestrator_end_to_end_eligible_case_reaches_processing_complete(client, clean_db):
    """
    An eligible applicant with all 6 valid documents, BCA qualification, 80%+ percentage,
    and 12th math evidence progresses end-to-end to PROCESSING_COMPLETE.
    """
    ctx = setup_applicant_with_application(client, email="e2e.eligible@example.com", prog_id="mca")
    app_id = ctx["app_id"]
    upload_all_six_documents(client, ctx, app_id, include_math=True)

    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})

    orchestrator = AgentOrchestrator(db=clean_db)
    res = orchestrator.run(app_id, ctx["user"])

    assert res.outcome == OrchestrationOutcome.COMPLETED
    assert res.currentApplicationStatus == "PROCESSING_COMPLETE"

    app_after = clean_db["applications"].find_one({"applicationId": app_id})
    assert app_after["status"] == "PROCESSING_COMPLETE"
    assert app_after["eligibilityResult"]["status"] == "ELIGIBLE"
    assert clean_db["eligibility_evaluations"].count_documents({"applicationId": app_id}) >= 1


def test_orchestrator_end_to_end_ineligible_case_routes_to_exception(client, clean_db):
    """
    An ineligible applicant (percentage 41.8% < 50% min for MCA) is evaluated deterministically as
    INELIGIBLE and workflow routes to EXCEPTION state with MANUAL_REVIEW_REQUIRED for admin confirmation.
    """
    ctx = setup_applicant_with_application(client, email="e2e.ineligible@example.com", prog_id="mca", cgpa=4.4)
    app_id = ctx["app_id"]

    # Upload documents with low CGPA (4.4 x 9.5 = 41.8% < 50%) and matching candidate details
    docs_to_upload = [
        ("10TH_MARKSHEET", ["Secondary School Certificate", "Candidate Name: Hemanth M.P.", "Date of Birth: 15/05/2000", "Marks: 432 / 500", "Percentage: 86.4%", "State Board of Secondary Education"]),
        ("12TH_MARKSHEET", ["Higher Secondary Certificate", "Candidate Name: Hemanth M.P.", "Date of Birth: 15/05/2000", "Marks: 440 / 500", "Percentage: 88.0%", "Mathematics: 95 / 100", "State Board of Higher Secondary"]),
        ("UG_MARKSHEET", ["Bachelor of Computer Applications Marksheet", "Candidate Name: Hemanth M.P.", "Date of Birth: 15/05/2000", "CGPA: 4.4 / 10", "Graduation Year: 2022", "University: Crescent"]),
        ("DEGREE_CERTIFICATE", ["B.S. Abdur Rahman Crescent Institute of Science and Technology", "Degree of Bachelor of Computer Applications", "Candidate Name: Hemanth M.P.", "Conferred: 2022"]),
        ("TRANSFER_CERTIFICATE", ["Transfer Certificate", "Student Name: Hemanth M.P.", "Date of Birth: 15/05/2000", "Conduct: Good"]),
        ("GOVERNMENT_ID", ["Government of India Identity Card", "Name: Hemanth M.P.", "DOB: 15/05/2000", "Gender: Male"]),
    ]
    for doc_type, lines in docs_to_upload:
        pdf_bytes = create_sample_pdf_bytes(lines)
        extra = {"documentType": doc_type, "applicationId": app_id}
        if doc_type == "DEGREE_CERTIFICATE":
            extra["documentVariant"] = "ORIGINAL_DEGREE_CERTIFICATE"
        up_res = client.post(
            "/api/v1/documents/upload",
            headers=ctx["headers"],
            data=extra,
            files={"file": (f"{doc_type.lower()}.pdf", pdf_bytes, "application/pdf")},
        )
        assert up_res.status_code == 201

    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})

    orchestrator = AgentOrchestrator(db=clean_db)
    res = orchestrator.run(app_id, ctx["user"])

    print(f"\nDEBUG NEEDS_REVIEW: res.outcome={res.outcome}, status={res.currentApplicationStatus}, summary={res.summary}")
    import json
    app_after = clean_db["applications"].find_one({"applicationId": app_id})
    print(f"ELIG_RESULT: {json.dumps(app_after.get('eligibilityResult'), indent=2)}")
    for d in clean_db["documents"].find({"applicationId": app_id}):
        print(f"DOC: type={d.get('documentType')}, math={d.get('extractedFields', {}).get('mathematics')}, text={d.get('ocrText')}")
    for act in clean_db["agent_activity"].find({"applicationId": app_id}):
        print(f"ACT: stage={act.get('stage')}, action={act.get('action')}, result={act.get('result')}")

    assert res.outcome == OrchestrationOutcome.MANUAL_REVIEW_REQUIRED
    assert res.currentApplicationStatus == "EXCEPTION"

    app_after = clean_db["applications"].find_one({"applicationId": app_id})
    assert app_after["status"] == "EXCEPTION"
    assert app_after["eligibilityResult"]["status"] == "INELIGIBLE"
    assert "statusReason" in app_after
    assert "INELIGIBLE" in app_after["statusReason"]


def test_orchestrator_end_to_end_needs_review_case_routes_to_exception(client, clean_db):
    """
    An applicant whose documents do not include mathematics OCR evidence yields NEEDS_REVIEW
    and routes to EXCEPTION state with MANUAL_REVIEW_REQUIRED.
    """
    ctx = setup_applicant_with_application(client, email="e2e.review@example.com", prog_id="mca")
    app_id = ctx["app_id"]
    # Upload all six documents without mathematics evidence
    upload_all_six_documents(client, ctx, app_id, include_math=False)

    clean_db["applications"].update_one({"applicationId": app_id}, {"$set": {"status": "SUBMITTED"}})

    orchestrator = AgentOrchestrator(db=clean_db)
    res = orchestrator.run(app_id, ctx["user"])

    assert res.outcome == OrchestrationOutcome.MANUAL_REVIEW_REQUIRED
    assert res.currentApplicationStatus == "EXCEPTION"

    app_after = clean_db["applications"].find_one({"applicationId": app_id})
    assert app_after["status"] == "EXCEPTION"
    assert app_after["eligibilityResult"]["status"] == "NEEDS_REVIEW"


# =============================================================================
# LLM Contract Guardrail Tests
# =============================================================================
def test_llm_planner_rejects_skipping_check_eligibility_and_direct_eligible():
    """
    Verify model guardrails in LLMPlanningStrategy:
    Model cannot propose ELIGIBLE directly without deterministic evaluation result.
    """
    obs = ApplicationObservation(
        application_id="app-llm-gate",
        applicant_id="user-1",
        user_id="user-1",
        applicant_name="Hemanth M.P.",
        programme_id="mca",
        current_status="ELIGIBILITY_CHECK",
        uploaded_documents=[{"documentId": "doc-1", "documentType": "10TH_MARKSHEET", "validationStatus": "VALIDATED"}],
        unprocessed_documents=[],
        failed_documents=[],
        mismatched_documents=[],
        manual_review_documents=[],
        validated_documents=[{"documentId": "doc-1", "documentType": "10TH_MARKSHEET", "validationStatus": "VALIDATED"}],
        is_document_complete=True,
        missing_document_types=[],
        eligibility_result=None,
    )

    strategy = LLMPlanningStrategy(provider=None, db=None, fallback_enabled=False)

    # 1. Proposal attempting to jump directly to ELIGIBLE
    proposal_eligible = LLMPlanProposal(
        action_type="TOOL_CALL",
        tool="update_application_status",
        parameters={"application_id": "app-llm-gate", "new_status": "ELIGIBLE"},
        rationale="Declaring applicant eligible directly.",
    )
    with pytest.raises(ValueError) as exc_info:
        strategy._validate_and_build_action(proposal_eligible, obs)
    assert "Forbidden transition" in str(exc_info.value)

    # 2. Proposal attempting to jump directly to PROCESSING_COMPLETE without result
    proposal_complete = LLMPlanProposal(
        action_type="TOOL_CALL",
        tool="update_application_status",
        parameters={"application_id": "app-llm-gate", "new_status": "PROCESSING_COMPLETE"},
        rationale="Declaring processing complete without result.",
    )
    with pytest.raises(ValueError) as exc_complete:
        strategy._validate_and_build_action(proposal_complete, obs)
    assert "Forbidden transition" in str(exc_complete.value)
