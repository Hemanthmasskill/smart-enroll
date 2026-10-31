from datetime import datetime, timezone
import logging
from typing import Any
import uuid

from fastapi import HTTPException, status
from pymongo.database import Database

from app.schemas.agent import (
    ALLOWED_APPLICATION_STATUSES,
    AuditEventRecord,
    ToolExecutionResult,
    ToolName,
    ToolStatus,
    WorkflowStage,
)
from app.services.application import get_application_by_id
from app.services.document import (
    get_document_processing_result,
    process_document,
    verify_document,
)

logger = logging.getLogger(__name__)

# Canonical 6 required document types established in Increment 12
REQUIRED_DOCUMENT_TYPES = [
    "10TH_MARKSHEET",
    "12TH_MARKSHEET",
    "UG_MARKSHEET",
    "DEGREE_CERTIFICATE",
    "TRANSFER_CERTIFICATE",
    "GOVERNMENT_ID",
]

# PROVISIONAL SCAFFOLDING FOR INCREMENT 15:
# The following hardcoded rules are strictly provisional scaffolding for the Increment 15 agent
# orchestration layer to test tool contracts. These are NOT authoritative admission policy.
# Authoritative programme requirements and deterministic academic thresholds will be formally
# persisted and evaluated by the Increment 16 Eligibility Engine.
CANONICAL_PROGRAMME_RULES: dict[str, dict[str, Any]] = {
    "mca": {
        "programmeId": "mca",
        "name": "MCA",
        "fullName": "Master of Computer Applications",
        "minimumQualification": "Bachelor's Degree",
        "minimumPercentage": "50%",
        "mathematicsRequirement": "Required at 10+2 or Graduation level",
        "requiredDocuments": "All 6 programme-required documents",
        "entranceRequirement": "Not Applicable",
    },
    "mba": {
        "programmeId": "mba",
        "name": "MBA",
        "fullName": "Master of Business Administration",
        "minimumQualification": "Bachelor's Degree (any discipline)",
        "minimumPercentage": "50%",
        "mathematicsRequirement": "Not Required",
        "requiredDocuments": "All 6 programme-required documents",
        "entranceRequirement": "Not Applicable",
    },
    "msc-cs": {
        "programmeId": "msc-cs",
        "name": "M.Sc Computer Science",
        "fullName": "Master of Science in Computer Science",
        "minimumQualification": "Bachelor's Degree",
        "minimumPercentage": "55%",
        "mathematicsRequirement": "Required at Graduation level",
        "requiredDocuments": "All 6 programme-required documents",
        "entranceRequirement": "Not Applicable",
    },
    "mtech-cs": {
        "programmeId": "mtech-cs",
        "name": "M.Tech Computer Science",
        "fullName": "Master of Technology in Computer Science",
        "minimumQualification": "Bachelor's Degree in Engineering/Technology",
        "minimumPercentage": "60%",
        "mathematicsRequirement": "Required at Graduation level",
        "requiredDocuments": "All 6 programme-required documents",
        "entranceRequirement": "Not Applicable",
    },
}


# =====================================================================
# Tool 1: get_application
# =====================================================================
def tool_get_application(
    db: Database,
    current_user: dict,
    application_id: str,
    **kwargs: Any,
) -> ToolExecutionResult:
    """Retrieve application record enforcing applicant ownership or admin access."""
    try:
        app = get_application_by_id(db, current_user, application_id)
        # ApplicationResponse or dict
        data = app.model_dump() if hasattr(app, "model_dump") else app
        return ToolExecutionResult(
            tool=ToolName.GET_APPLICATION.value,
            status=ToolStatus.COMPLETED.value,
            data=data,
            message=f"Application {application_id} retrieved successfully.",
        )
    except HTTPException as e:
        return ToolExecutionResult(
            tool=ToolName.GET_APPLICATION.value,
            status=ToolStatus.FAILED.value,
            message=e.detail,
        )


# =====================================================================
# Tool 2: get_program_requirements
# =====================================================================
def tool_get_program_requirements(
    db: Database,
    current_user: dict,
    programme_id: str,
    **kwargs: Any,
) -> ToolExecutionResult:
    """Retrieve configured, deterministic admission requirements for a programme."""
    pid = programme_id.strip().lower()
    rules = CANONICAL_PROGRAMME_RULES.get(pid)
    if not rules:
        # Check if database has custom seeded program
        db_program = db["programs"].find_one({"programmeId": pid}, {"_id": 0})
        if db_program:
            rules = db_program

    if not rules:
        return ToolExecutionResult(
            tool=ToolName.GET_PROGRAM_REQUIREMENTS.value,
            status=ToolStatus.FAILED.value,
            message=f"Programme '{programme_id}' not found. Supported programmes: {', '.join(sorted(CANONICAL_PROGRAMME_RULES.keys()))}",
        )

    return ToolExecutionResult(
        tool=ToolName.GET_PROGRAM_REQUIREMENTS.value,
        status=ToolStatus.COMPLETED.value,
        data=rules,
        message=f"Admission requirements retrieved for programme '{pid}'.",
    )


# =====================================================================
# Tool 3: check_document_completeness
# =====================================================================
def tool_check_document_completeness(
    db: Database,
    current_user: dict,
    application_id: str,
    **kwargs: Any,
) -> ToolExecutionResult:
    """
    Inspect the 6 logical document slots for an application and identify missing documents.
    Enforces applicant ownership or admin role.
    """
    try:
        app = get_application_by_id(db, current_user, application_id)
    except HTTPException as e:
        return ToolExecutionResult(
            tool=ToolName.CHECK_DOCUMENT_COMPLETENESS.value,
            status=ToolStatus.FAILED.value,
            message=e.detail,
        )

    app_id = app.applicationId if hasattr(app, "applicationId") else app.get("applicationId")

    # Find all uploaded documents for this application
    docs = list(db["documents"].find({"applicationId": app_id}))

    submitted_types = set()
    for d in docs:
        dtype = d.get("documentType")
        dstatus = d.get("status")
        # Count document as submitted if status is not NOT_UPLOADED and file exists
        has_file = bool(d.get("originalFileName") or d.get("fileName") or d.get("storedFileName"))
        if dtype and dstatus != "NOT_UPLOADED" and has_file:
            submitted_types.add(dtype)

    missing_types = [dt for dt in REQUIRED_DOCUMENT_TYPES if dt not in submitted_types]

    completeness_data = {
        "applicationId": app_id,
        "totalRequired": len(REQUIRED_DOCUMENT_TYPES),
        "totalSubmitted": len(submitted_types),
        "totalMissing": len(missing_types),
        "submittedDocumentTypes": sorted(list(submitted_types)),
        "missingDocumentTypes": missing_types,
        "isComplete": len(missing_types) == 0,
    }

    return ToolExecutionResult(
        tool=ToolName.CHECK_DOCUMENT_COMPLETENESS.value,
        status=ToolStatus.COMPLETED.value,
        data=completeness_data,
        message=f"{len(submitted_types)} of {len(REQUIRED_DOCUMENT_TYPES)} required documents submitted.",
    )


# =====================================================================
# Tool 4: process_document
# =====================================================================
def tool_process_document(
    db: Database,
    current_user: dict,
    document_id: str,
    run_id: str | None = None,
    **kwargs: Any,
) -> ToolExecutionResult:
    """Run OCR extraction and document classification. Enforces applicant ownership and fencing."""
    try:
        result = process_document(db, current_user, document_id, run_id=run_id)
        data = result.model_dump() if hasattr(result, "model_dump") else result
        return ToolExecutionResult(
            tool=ToolName.PROCESS_DOCUMENT.value,
            status=ToolStatus.COMPLETED.value,
            data=data,
            message=f"Document {document_id} processed with state '{data.get('processingState')}'.",
        )
    except HTTPException as e:
        return ToolExecutionResult(
            tool=ToolName.PROCESS_DOCUMENT.value,
            status=ToolStatus.FAILED.value,
            message=e.detail,
        )


# =====================================================================
# Tool 5: extract_document_data
# =====================================================================
def tool_extract_document_data(
    db: Database,
    current_user: dict,
    document_id: str,
    **kwargs: Any,
) -> ToolExecutionResult:
    """Retrieve persisted structured OCR field extraction and confidence."""
    try:
        result = get_document_processing_result(db, current_user, document_id)
        data = result.model_dump() if hasattr(result, "model_dump") else result
        return ToolExecutionResult(
            tool=ToolName.EXTRACT_DOCUMENT_DATA.value,
            status=ToolStatus.COMPLETED.value,
            data=data,
            message=f"Extracted fields retrieved for document {document_id}.",
        )
    except HTTPException as e:
        return ToolExecutionResult(
            tool=ToolName.EXTRACT_DOCUMENT_DATA.value,
            status=ToolStatus.FAILED.value,
            message=e.detail,
        )


# =====================================================================
# Tool 6: verify_document
# =====================================================================
def tool_verify_document(
    db: Database,
    current_user: dict,
    document_id: str,
    run_id: str | None = None,
    **kwargs: Any,
) -> ToolExecutionResult:
    """Execute Layer 2 deterministic content validation against application record."""
    try:
        result = verify_document(db, current_user, document_id, run_id=run_id)
        data = result.model_dump() if hasattr(result, "model_dump") else result
        return ToolExecutionResult(
            tool=ToolName.VERIFY_DOCUMENT.value,
            status=ToolStatus.COMPLETED.value,
            data=data,
            message=f"Validation completed for document {document_id} with status '{data.get('validationStatus')}'.",
        )
    except HTTPException as e:
        return ToolExecutionResult(
            tool=ToolName.VERIFY_DOCUMENT.value,
            status=ToolStatus.FAILED.value,
            message=e.detail,
        )


# =====================================================================
# Tool 7: compare_applicant_details
# =====================================================================
def tool_compare_applicant_details(
    db: Database,
    current_user: dict,
    document_id: str,
    application_id: str | None = None,
    **kwargs: Any,
) -> ToolExecutionResult:
    """
    Compare document extracted fields directly against application identity and academic details.
    Reuses Layer 2 validation engine.
    """
    try:
        result = verify_document(db, current_user, document_id)
        data = result.model_dump() if hasattr(result, "model_dump") else result
        return ToolExecutionResult(
            tool=ToolName.COMPARE_APPLICANT_DETAILS.value,
            status=ToolStatus.COMPLETED.value,
            data={
                "documentId": document_id,
                "validationStatus": data.get("validationStatus"),
                "fieldResults": data.get("fieldResults", {}),
                "reasons": data.get("reasons", []),
            },
            message="Applicant details compared against document extractions.",
        )
    except HTTPException as e:
        return ToolExecutionResult(
            tool=ToolName.COMPARE_APPLICANT_DETAILS.value,
            status=ToolStatus.FAILED.value,
            message=e.detail,
        )


# =====================================================================
# Tool 8: check_eligibility (Integration Dependency: Increment 16)
# =====================================================================
def tool_check_eligibility(
    db: Database,
    current_user: dict,
    application_id: str,
    **kwargs: Any,
) -> ToolExecutionResult:
    """
    Contract interface for deterministic eligibility evaluation.
    Explicitly documents dependency on Increment 16 without fabricating results.
    """
    return ToolExecutionResult(
        tool=ToolName.CHECK_ELIGIBILITY.value,
        status=ToolStatus.DEPENDENCY_PENDING.value,
        data={
            "applicationId": application_id,
            "status": "DEPENDENCY_PENDING",
            "evaluator": "DeterministicEligibilityEngine",
        },
        message="Deterministic eligibility evaluation service is pending backend implementation in Increment 16.",
        dependency="Increment 16: Eligibility Engine",
    )


# =====================================================================
# Tool 9: create_exception (Integration Dependency: Increment 17)
# =====================================================================
def tool_create_exception(
    db: Database,
    current_user: dict,
    application_id: str,
    exception_type: str,
    description: str,
    severity: str = "MEDIUM",
    **kwargs: Any,
) -> ToolExecutionResult:
    """
    Contract interface for recording an admission workflow exception.
    Explicitly documents dependency on Increment 17 without fabricating results.
    """
    return ToolExecutionResult(
        tool=ToolName.CREATE_EXCEPTION.value,
        status=ToolStatus.DEPENDENCY_PENDING.value,
        data={
            "applicationId": application_id,
            "exceptionType": exception_type,
            "severity": severity.upper(),
            "description": description,
        },
        message="Exception management lifecycle service is pending backend implementation in Increment 17.",
        dependency="Increment 17: Exception Management",
    )


# =====================================================================
# Tool 10: request_missing_document (Integration Dependency: Increments 17 & 18)
# =====================================================================
def tool_request_missing_document(
    db: Database,
    current_user: dict,
    application_id: str,
    document_type: str,
    **kwargs: Any,
) -> ToolExecutionResult:
    """
    Contract interface for flagging missing required documents and dispatching upload prompts.
    Explicitly documents dependency on Increments 17 & 18.
    """
    return ToolExecutionResult(
        tool=ToolName.REQUEST_MISSING_DOCUMENT.value,
        status=ToolStatus.DEPENDENCY_PENDING.value,
        data={
            "applicationId": application_id,
            "documentType": document_type,
        },
        message="Missing document request workflow is pending backend integration in Increments 17 and 18.",
        dependency="Increment 17: Exception Management / Increment 18: Notifications",
    )


# Explicit transition graph enforcing valid application lifecycle progression
ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "DRAFT": {"SUBMITTED"},
    "SUBMITTED": {"PROCESSING", "WAITING_FOR_DOCUMENTS"},
    "PROCESSING": {"WAITING_FOR_DOCUMENTS", "VERIFICATION_IN_PROGRESS", "EXCEPTION", "ELIGIBILITY_CHECK"},
    "WAITING_FOR_DOCUMENTS": {"PROCESSING", "VERIFICATION_IN_PROGRESS", "EXCEPTION"},
    "VERIFICATION_IN_PROGRESS": {"WAITING_FOR_DOCUMENTS", "EXCEPTION", "ELIGIBILITY_CHECK"},
    "EXCEPTION": {"PROCESSING", "VERIFICATION_IN_PROGRESS", "ELIGIBILITY_CHECK", "INELIGIBLE"},
    "ELIGIBILITY_CHECK": {"ELIGIBLE", "INELIGIBLE", "EXCEPTION"},
    "ELIGIBLE": {"PROCESSING_COMPLETE"},
    "INELIGIBLE": {"PROCESSING_COMPLETE"},
    "PROCESSING_COMPLETE": set(),  # Terminal state
}


# =====================================================================
# Tool 11: update_application_status
# =====================================================================
def tool_update_application_status(
    db: Database,
    current_user: dict,
    application_id: str,
    new_status: str,
    run_id: str | None = None,
    **kwargs: Any,
) -> ToolExecutionResult:
    """
    Update application workflow status with strict lifecycle transition graph validation.
    Enforces server-side authorization boundaries:
    - Applicants are strictly forbidden from modifying workflow status (own or others).
    - Requires administrative or trusted internal orchestrator role ('admin', 'system', 'orchestrator').
    - Terminal states (ELIGIBLE, INELIGIBLE) require deterministic eligibility results (Increment 16).
    - PROCESSING_COMPLETE requires verified workflow-completion evidence.
    Failed transitions leave persisted application state unchanged.
    """
    status_clean = new_status.strip().upper()
    if status_clean not in ALLOWED_APPLICATION_STATUSES:
        return ToolExecutionResult(
            tool=ToolName.UPDATE_APPLICATION_STATUS.value,
            status=ToolStatus.FAILED.value,
            message=f"Invalid application status '{new_status}'. Allowed statuses: {', '.join(sorted(ALLOWED_APPLICATION_STATUSES))}",
        )

    # 1. Enforce strict role boundary: applicants can never update workflow status
    user_role = current_user.get("role")
    if user_role == "applicant":
        user_id = str(current_user.get("_id") or current_user.get("id"))
        app = db["applications"].find_one({"applicationId": application_id})
        if not app:
            return ToolExecutionResult(
                tool=ToolName.UPDATE_APPLICATION_STATUS.value,
                status=ToolStatus.FAILED.value,
                message=f"Application '{application_id}' not found.",
            )
        if app.get("userId") != user_id:
            return ToolExecutionResult(
                tool=ToolName.UPDATE_APPLICATION_STATUS.value,
                status=ToolStatus.FAILED.value,
                message="Not authorized to access or modify this application.",
            )
        return ToolExecutionResult(
            tool=ToolName.UPDATE_APPLICATION_STATUS.value,
            status=ToolStatus.FAILED.value,
            message="Applicants are not permitted to update application workflow status.",
        )

    if user_role not in ("admin", "system", "orchestrator"):
        return ToolExecutionResult(
            tool=ToolName.UPDATE_APPLICATION_STATUS.value,
            status=ToolStatus.FAILED.value,
            message="Unauthorized: administrative or internal orchestrator authorization required.",
        )

    # 2. Retrieve application record
    app = db["applications"].find_one({"applicationId": application_id})
    if not app:
        return ToolExecutionResult(
            tool=ToolName.UPDATE_APPLICATION_STATUS.value,
            status=ToolStatus.FAILED.value,
            message=f"Application '{application_id}' not found.",
        )

    app_id = app.get("applicationId", application_id)
    current_status = app.get("status", "DRAFT")

    # 3. Enforce explicit transition graph
    allowed_transitions = ALLOWED_STATUS_TRANSITIONS.get(current_status, set())
    if status_clean not in allowed_transitions:
        return ToolExecutionResult(
            tool=ToolName.UPDATE_APPLICATION_STATUS.value,
            status=ToolStatus.FAILED.value,
            data={
                "applicationId": app_id,
                "currentStatus": current_status,
                "targetStatus": status_clean,
            },
            message=f"Invalid status transition from '{current_status}' to '{status_clean}'.",
        )

    # 4. Enforce document-verification evidence for ELIGIBILITY_CHECK
    if status_clean == "ELIGIBILITY_CHECK":
        docs = list(db["documents"].find({"applicationId": app_id}))

        # 4a. All six required document types must exist
        existing_types = {d.get("documentType") for d in docs if d.get("documentType")}
        missing_types = [t for t in REQUIRED_DOCUMENT_TYPES if t not in existing_types]
        if missing_types:
            return ToolExecutionResult(
                tool=ToolName.UPDATE_APPLICATION_STATUS.value,
                status=ToolStatus.FAILED.value,
                data={
                    "applicationId": app_id,
                    "currentStatus": current_status,
                    "targetStatus": status_clean,
                    "missingDocumentTypes": missing_types,
                },
                message=f"Cannot transition to 'ELIGIBILITY_CHECK': missing {len(missing_types)} required document type(s): {', '.join(sorted(missing_types))}.",
            )

        # 4b. No MISMATCH, MANUAL_REVIEW, FAILED or REJECTED state in status, validationStatus, or processingStatus
        disallowed_states = {"MISMATCH", "MANUAL_REVIEW", "FAILED", "REJECTED", "ERROR"}
        flagged_or_failed = [
            d for d in docs
            if d.get("status") in disallowed_states
            or d.get("validationStatus") in disallowed_states
            or d.get("processingStatus") in disallowed_states
        ]
        if flagged_or_failed:
            return ToolExecutionResult(
                tool=ToolName.UPDATE_APPLICATION_STATUS.value,
                status=ToolStatus.FAILED.value,
                data={
                    "applicationId": app_id,
                    "currentStatus": current_status,
                    "targetStatus": status_clean,
                },
                message="Cannot transition to 'ELIGIBILITY_CHECK': document verification detected data conflicts, manual review flags, or failed states.",
            )

        # 4c. Each document must have a processingStatus field present and equal to 'COMPLETED'
        missing_or_incomplete_processing = [
            d for d in docs
            if d.get("processingStatus") != "COMPLETED"
        ]
        if missing_or_incomplete_processing:
            return ToolExecutionResult(
                tool=ToolName.UPDATE_APPLICATION_STATUS.value,
                status=ToolStatus.FAILED.value,
                data={
                    "applicationId": app_id,
                    "currentStatus": current_status,
                    "targetStatus": status_clean,
                },
                message="Cannot transition to 'ELIGIBILITY_CHECK': every required document must have a 'processingStatus' field present and equal to 'COMPLETED'.",
            )

        # 4d. Each document must have validationStatus == 'VALIDATED'
        unvalidated = [
            d for d in docs
            if d.get("validationStatus") != "VALIDATED"
        ]
        if unvalidated:
            return ToolExecutionResult(
                tool=ToolName.UPDATE_APPLICATION_STATUS.value,
                status=ToolStatus.FAILED.value,
                data={
                    "applicationId": app_id,
                    "currentStatus": current_status,
                    "targetStatus": status_clean,
                },
                message="Cannot transition to 'ELIGIBILITY_CHECK': not all uploaded documents have verified validation evidence.",
            )

    # 5. Enforce deterministic eligibility gate for terminal eligibility states
    if status_clean in ("ELIGIBLE", "INELIGIBLE"):
        eligibility_result = app.get("eligibilityResult")
        if not eligibility_result or not isinstance(eligibility_result, dict) or eligibility_result.get("status") != status_clean:
            return ToolExecutionResult(
                tool=ToolName.UPDATE_APPLICATION_STATUS.value,
                status=ToolStatus.DEPENDENCY_PENDING.value,
                data={
                    "applicationId": app_id,
                    "currentStatus": current_status,
                    "targetStatus": status_clean,
                },
                message=f"Transition to '{status_clean}' requires deterministic eligibility evaluation from Increment 16.",
                dependency="Increment 16: Eligibility Engine",
            )

    # 5. Enforce workflow-completion evidence for PROCESSING_COMPLETE
    if status_clean == "PROCESSING_COMPLETE":
        completion_evidence = app.get("eligibilityResult") or app.get("completionEvidence")
        if not completion_evidence or not isinstance(completion_evidence, dict):
            return ToolExecutionResult(
                tool=ToolName.UPDATE_APPLICATION_STATUS.value,
                status=ToolStatus.FAILED.value,
                data={
                    "applicationId": app_id,
                    "currentStatus": current_status,
                    "targetStatus": status_clean,
                },
                message="Cannot transition to 'PROCESSING_COMPLETE': required workflow-completion evidence is missing.",
            )

    # 6. Apply state transition atomically with active run fencing
    now = datetime.now(timezone.utc).isoformat()
    filter_doc: dict[str, Any] = {"applicationId": app_id}
    if run_id:
        filter_doc["activeRunId"] = run_id
        filter_doc["supersededRunIds"] = {"$ne": run_id}

    updated = db["applications"].find_one_and_update(
        filter_doc,
        {"$set": {"status": status_clean, "updatedAt": now}},
        return_document=True,
        projection={"_id": 0},
    )

    if not updated:
        if run_id:
            current_app = db["applications"].find_one({"applicationId": app_id})
            if current_app and (current_app.get("activeRunId") != run_id or run_id in current_app.get("supersededRunIds", [])):
                return ToolExecutionResult(
                    tool=ToolName.UPDATE_APPLICATION_STATUS.value,
                    status=ToolStatus.FAILED.value,
                    message=f"Execution ownership lost for run '{run_id}'. Application status update rejected.",
                )
        return ToolExecutionResult(
            tool=ToolName.UPDATE_APPLICATION_STATUS.value,
            status=ToolStatus.FAILED.value,
            message=f"Failed to update status for application {app_id}.",
        )

    return ToolExecutionResult(
        tool=ToolName.UPDATE_APPLICATION_STATUS.value,
        status=ToolStatus.COMPLETED.value,
        data={
            "applicationId": app_id,
            "previousStatus": current_status,
            "newStatus": status_clean,
        },
        message=f"Application {app_id} status updated from {current_status} to {status_clean}.",
    )


# =====================================================================
# Tool 12: send_notification (Integration Dependency: Increment 18)
# =====================================================================
def tool_send_notification(
    db: Database,
    current_user: dict,
    user_id: str,
    title: str,
    description: str,
    applicant_id: str | None = None,
    **kwargs: Any,
) -> ToolExecutionResult:
    """
    Contract interface for dispatching notifications to applicants.
    Explicitly documents dependency on Increment 18 without fabricating results.
    """
    return ToolExecutionResult(
        tool=ToolName.SEND_NOTIFICATION.value,
        status=ToolStatus.DEPENDENCY_PENDING.value,
        data={
            "userId": user_id,
            "applicantId": applicant_id,
            "title": title,
            "description": description,
        },
        message="Notification dispatch service is pending backend implementation in Increment 18.",
        dependency="Increment 18: Notifications",
    )


# =====================================================================
# Tool 13: record_audit_event (Persistent MongoDB agent_activity)
# =====================================================================
def tool_record_audit_event(
    db: Database,
    current_user: dict,
    application_id: str,
    stage: str,
    tool: str,
    action: str,
    result: str,
    status: str = "COMPLETED",
    applicant_name: str | None = None,
    **kwargs: Any,
) -> ToolExecutionResult:
    """
    Persist structured, observable audit trail record to MongoDB's agent_activity collection.
    Conforms to frontend AgentActivity format.
    Strictly forbids private reasoning or chain-of-thought logging.
    """
    stage_clean = stage.strip().upper()
    valid_stages = {s.value for s in WorkflowStage}
    if stage_clean not in valid_stages:
        stage_clean = WorkflowStage.ACT.value

    # Determine applicant name if not supplied
    if not applicant_name:
        app = db["applications"].find_one({"applicationId": application_id})
        if app:
            applicant_name = app.get("fullName") or app.get("applicantName", "Applicant")
        else:
            applicant_name = current_user.get("full_name") or "Applicant"

    # Human-readable timestamp formatted for frontend table display
    now_dt = datetime.now(timezone.utc)
    formatted_ts = now_dt.strftime("%d %b %Y, %I:%M:%S %p")
    event_id = f"act-{uuid.uuid4().hex[:10]}"

    audit_doc = {
        "id": event_id,
        "timestamp": formatted_ts,
        "applicationId": application_id,
        "applicantName": applicant_name,
        "stage": stage_clean,
        "tool": tool,
        "action": action,
        "result": result,
        "status": status.upper(),
        "createdAt": now_dt.isoformat(),
    }

    db["agent_activity"].insert_one(audit_doc)
    audit_doc.pop("_id", None)

    return ToolExecutionResult(
        tool=ToolName.RECORD_AUDIT_EVENT.value,
        status=ToolStatus.COMPLETED.value,
        data=audit_doc,
        message=f"Audit event {event_id} persisted to agent_activity.",
    )


# =====================================================================
# Audit Log Querying & Tool Dispatcher
# =====================================================================
# NOTE (Future Integration Consideration - Increment 16/17):
# Sensible compound indexes for the `agent_activity` collection (e.g. on `(applicationId, createdAt)`
# and `(stage, createdAt)`) should be added when indexing migrations are consolidated, to optimize
# audit query performance without premature database refactoring in Increment 15.
def list_agent_activity(
    db: Database,
    current_user: dict,
    application_id: str | None = None,
    stage: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """
    Retrieve structured audit log events from agent_activity collection.
    Admins can query across all applications.
    Applicants can ONLY query audit records belonging to their own application.
    """
    role = current_user.get("role")
    if role not in ("admin", "applicant"):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: insufficient role permissions to view agent activity.",
        )

    user_id = str(current_user["_id"])

    query: dict[str, Any] = {}

    if role == "applicant":
        # Resolve applicant's own application
        app = db["applications"].find_one({"userId": user_id})
        if not app:
            if application_id:
                raise HTTPException(
                    status_code=403,
                    detail="Not authorized to access agent activity for another application.",
                )
            return []
        own_app_id = app.get("applicationId")
        if application_id and application_id != own_app_id:
            raise HTTPException(
                status_code=403,
                detail="Not authorized to access agent activity for another application.",
            )
        query["applicationId"] = own_app_id
    elif application_id:
        query["applicationId"] = application_id

    if stage and stage != "ALL":
        query["stage"] = stage.strip().upper()

    if status and status != "ALL":
        query["status"] = status.strip().upper()

    cursor = db["agent_activity"].find(query, {"_id": 0}).sort("createdAt", -1).limit(limit)
    return list(cursor)


# Unified Tool Dispatcher Registry
TOOL_REGISTRY = {
    ToolName.GET_APPLICATION.value: tool_get_application,
    ToolName.GET_PROGRAM_REQUIREMENTS.value: tool_get_program_requirements,
    ToolName.CHECK_DOCUMENT_COMPLETENESS.value: tool_check_document_completeness,
    ToolName.PROCESS_DOCUMENT.value: tool_process_document,
    ToolName.EXTRACT_DOCUMENT_DATA.value: tool_extract_document_data,
    ToolName.VERIFY_DOCUMENT.value: tool_verify_document,
    ToolName.COMPARE_APPLICANT_DETAILS.value: tool_compare_applicant_details,
    ToolName.CHECK_ELIGIBILITY.value: tool_check_eligibility,
    ToolName.CREATE_EXCEPTION.value: tool_create_exception,
    ToolName.REQUEST_MISSING_DOCUMENT.value: tool_request_missing_document,
    ToolName.UPDATE_APPLICATION_STATUS.value: tool_update_application_status,
    ToolName.SEND_NOTIFICATION.value: tool_send_notification,
    ToolName.RECORD_AUDIT_EVENT.value: tool_record_audit_event,
}


def execute_tool(
    tool_name: str,
    parameters: dict[str, Any],
    current_user: dict,
    db: Database,
    run_id: str | None = None,
) -> ToolExecutionResult:
    """
    Execute a registered tool within security and boundary constraints.
    Rejects unregistered tools.
    Catches and logs unexpected internal exceptions while returning sanitized, client-safe error messages.
    """
    clean_name = tool_name.strip().lower()
    handler = TOOL_REGISTRY.get(clean_name)
    if not handler:
        return ToolExecutionResult(
            tool=clean_name,
            status=ToolStatus.FAILED.value,
            message=f"Tool '{clean_name}' is not registered. Available tools: {', '.join(sorted(TOOL_REGISTRY.keys()))}",
        )

    call_params = dict(parameters)
    # Strip caller-provided internal keys to prevent injection
    call_params.pop("db", None)
    call_params.pop("current_user", None)
    call_params.pop("run_id", None)
    if run_id:
        call_params["run_id"] = run_id

    try:
        return handler(db=db, current_user=current_user, **call_params)
    except TypeError as e:
        logger.error(f"Parameter mismatch for tool '{clean_name}': {e}")
        return ToolExecutionResult(
            tool=clean_name,
            status=ToolStatus.FAILED.value,
            message=f"Invalid parameters provided for tool '{clean_name}'.",
        )
    except Exception as e:
        logger.exception(f"Unexpected internal error executing tool '{clean_name}': {e}")
        return ToolExecutionResult(
            tool=clean_name,
            status=ToolStatus.FAILED.value,
            message=f"An unexpected internal error occurred while executing tool '{clean_name}'.",
        )
