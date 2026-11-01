from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExceptionType(str, Enum):
    NAME_MISMATCH = "NAME_MISMATCH"
    DOB_MISMATCH = "DOB_MISMATCH"
    MISSING_DOCUMENT = "MISSING_DOCUMENT"
    UNREADABLE_DOCUMENT = "UNREADABLE_DOCUMENT"
    VERIFICATION_UNAVAILABLE = "VERIFICATION_UNAVAILABLE"
    ACADEMIC_MISMATCH = "ACADEMIC_MISMATCH"
    DUPLICATE_DOCUMENT = "DUPLICATE_DOCUMENT"
    INVALID_FILE = "INVALID_FILE"
    ELIGIBILITY_CONFLICT = "ELIGIBILITY_CONFLICT"


class ExceptionSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ExceptionStatus(str, Enum):
    OPEN = "OPEN"
    MONITORING = "MONITORING"
    RESOLVED = "RESOLVED"


class ExceptionSource(str, Enum):
    DOCUMENT_VERIFICATION = "DOCUMENT_VERIFICATION"
    OCR_PROCESSING = "OCR_PROCESSING"
    ELIGIBILITY_ENGINE = "ELIGIBILITY_ENGINE"
    ORCHESTRATOR = "ORCHESTRATOR"
    ADMIN = "ADMIN"
    SYSTEM = "SYSTEM"


class AuditEvent(BaseModel):
    action: str
    actor: Any
    timestamp: str
    details: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")


class ExceptionCreate(BaseModel):
    applicationId: str
    type: ExceptionType
    description: str
    severity: Optional[ExceptionSeverity] = None
    source: ExceptionSource = ExceptionSource.SYSTEM
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")


class ExceptionResolveRequest(BaseModel):
    resolutionReason: str = Field(
        ...,
        min_length=5,
        description="Meaningful, non-empty justification for resolving the exception",
    )
    action: Optional[str] = None

    @field_validator("resolutionReason")
    @classmethod
    def validate_resolution_reason(cls, v: str) -> str:
        stripped = (v or "").strip()
        if len(stripped) < 5:
            raise ValueError("Resolution reason must contain at least 5 non-whitespace characters.")
        return stripped

    model_config = ConfigDict(extra="ignore")


class ExceptionResponse(BaseModel):
    exceptionId: str
    applicationId: str
    applicantId: Optional[str] = None
    applicantName: Optional[str] = None
    userId: Optional[str] = None
    type: str
    description: str
    severity: str
    status: str
    source: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    dedupeKey: Optional[str] = None
    createdAt: str
    updatedAt: str
    resolvedAt: Optional[str] = None
    resolvedBy: Optional[Any] = None
    resolutionReason: Optional[str] = None
    auditEvents: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class ExceptionListResponse(BaseModel):
    items: list[ExceptionResponse]
    total: int
    limit: int
    skip: int

    model_config = ConfigDict(extra="ignore")

