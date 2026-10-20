from datetime import datetime, timezone
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class WorkflowStage(str, Enum):
    OBSERVE = "OBSERVE"
    PLAN = "PLAN"
    ACT = "ACT"
    VERIFY = "VERIFY"
    RE_PLAN = "RE-PLAN"


class ToolStatus(str, Enum):
    COMPLETED = "COMPLETED"
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    PAUSED = "PAUSED"
    FLAGGED = "FLAGGED"
    FAILED = "FAILED"
    DEPENDENCY_PENDING = "DEPENDENCY_PENDING"


class ToolName(str, Enum):
    GET_APPLICATION = "get_application"
    GET_PROGRAM_REQUIREMENTS = "get_program_requirements"
    CHECK_DOCUMENT_COMPLETENESS = "check_document_completeness"
    PROCESS_DOCUMENT = "process_document"
    EXTRACT_DOCUMENT_DATA = "extract_document_data"
    VERIFY_DOCUMENT = "verify_document"
    COMPARE_APPLICANT_DETAILS = "compare_applicant_details"
    CHECK_ELIGIBILITY = "check_eligibility"
    CREATE_EXCEPTION = "create_exception"
    REQUEST_MISSING_DOCUMENT = "request_missing_document"
    UPDATE_APPLICATION_STATUS = "update_application_status"
    SEND_NOTIFICATION = "send_notification"
    RECORD_AUDIT_EVENT = "record_audit_event"


# 10 canonical admission workflow states
ALLOWED_APPLICATION_STATUSES = {
    "DRAFT",
    "SUBMITTED",
    "PROCESSING",
    "WAITING_FOR_DOCUMENTS",
    "VERIFICATION_IN_PROGRESS",
    "EXCEPTION",
    "ELIGIBILITY_CHECK",
    "ELIGIBLE",
    "INELIGIBLE",
    "PROCESSING_COMPLETE",
}


class AuditEventRecord(BaseModel):
    """
    Observable audit trail entry persisted in the agent_activity collection.
    Strictly records observable stage, tool, action, and deterministic result.
    Does NOT store private reasoning or model chain-of-thought.
    """
    id: str = Field(..., description="Unique event identifier, e.g. log-001 or act-uuid")
    timestamp: str = Field(..., description="Formatted timestamp string for frontend rendering")
    applicationId: str = Field(..., description="Associated application identifier, e.g. SE20260001")
    applicantName: str = Field(..., description="Applicant display name")
    stage: str = Field(..., description="OBSERVE, PLAN, ACT, VERIFY, or RE-PLAN")
    tool: str = Field(..., description="Canonical tool name invoked")
    action: str = Field(..., description="High-level description of the observable action")
    result: str = Field(..., description="Deterministic outcome summary")
    status: str = Field(..., description="Execution status, e.g. COMPLETED, PENDING, FLAGGED, etc.")
    createdAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    model_config = ConfigDict(extra="ignore")


class ToolExecutionRequest(BaseModel):
    tool: ToolName
    parameters: dict[str, Any] = Field(default_factory=dict)
    applicationId: str | None = None

    model_config = ConfigDict(extra="ignore")


class ToolExecutionResult(BaseModel):
    """
    Standard envelope returned by all registered agent tools.
    """
    tool: str
    status: str
    data: Any | None = None
    message: str | None = None
    dependency: str | None = None
    executedAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    model_config = ConfigDict(extra="ignore")


class AgentActivityQuery(BaseModel):
    applicationId: str | None = None
    stage: str | None = None
    status: str | None = None
    limit: int = 100

    model_config = ConfigDict(extra="ignore")


class OrchestrationOutcome(str, Enum):
    COMPLETED = "COMPLETED"
    WAITING_FOR_APPLICANT = "WAITING_FOR_APPLICANT"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    DEPENDENCY_PENDING = "DEPENDENCY_PENDING"
    FAILED = "FAILED"
    ALREADY_RUNNING = "ALREADY_RUNNING"


class OrchestrationRunStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"
    RECOVERING = "RECOVERING"


class OrchestrationStepRecord(BaseModel):
    stepIndex: int
    stage: str
    tool: str | None = None
    action: str
    resultSummary: str
    status: str
    executedAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    model_config = ConfigDict(extra="ignore")


class OrchestrationRunResponse(BaseModel):
    runId: str = Field(..., description="Unique run identifier, e.g. run-uuid")
    applicationId: str
    status: OrchestrationRunStatus = Field(
        default=OrchestrationRunStatus.COMPLETED,
        description="Execution lifecycle status (RUNNING, COMPLETED, FAILED, ABORTED)",
    )
    outcome: OrchestrationOutcome = Field(
        ...,
        description="Business workflow outcome (COMPLETED, WAITING_FOR_APPLICANT, MANUAL_REVIEW_REQUIRED, DEPENDENCY_PENDING, FAILED, ALREADY_RUNNING)",
    )
    currentApplicationStatus: str
    stepsCompleted: int
    summary: str
    failureReason: str | None = None
    pendingDependency: str | None = None
    startedAt: str
    completedAt: str | None = None
    steps: list[OrchestrationStepRecord] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")
