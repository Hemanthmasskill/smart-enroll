from typing import Any
from pydantic import BaseModel, ConfigDict, Field


VALIDATION_OUTCOMES = [
    "VALIDATED",
    "MISMATCH",
    "MANUAL_REVIEW",
    "ERROR",
]

DOCUMENT_VALIDATION_STATUSES = [
    "NOT_RUN",
    "VALIDATED",
    "MISMATCH",
    "MANUAL_REVIEW",
    "ERROR",
]

FIELD_VALIDATION_STATUSES = [
    "MATCH",
    "MISMATCH",
    "MANUAL_REVIEW",
    "NOT_EXTRACTED",
    "NOT_APPLICABLE",
]

CROSS_DOCUMENT_STATUSES = [
    "MATCH",
    "MISMATCH",
    "MANUAL_REVIEW",
    "SKIPPED",
    "NOT_APPLICABLE",
]

AUTHORITATIVE_STATUSES = [
    "SIMULATED_MATCH",
    "SIMULATED_MISMATCH",
    "SIMULATED_NOT_FOUND",
    "SIMULATION_UNAVAILABLE",
]


class FieldValidationResult(BaseModel):
    fieldName: str
    status: str
    extractedValue: Any | None = None
    authoritativeValue: Any | None = None
    confidence: float | None = None
    message: str | None = None

    model_config = ConfigDict(extra="ignore")


class CrossDocumentCheckResult(BaseModel):
    checkName: str
    targetDocumentType: str | None = None
    status: str
    message: str | None = None
    details: dict[str, Any] | None = None

    model_config = ConfigDict(extra="ignore")


class DocumentValidationResult(BaseModel):
    documentId: str
    documentType: str
    validationStatus: str
    fieldResults: dict[str, FieldValidationResult] = Field(default_factory=dict)
    crossDocumentResults: list[CrossDocumentCheckResult] = Field(default_factory=list)
    missingMandatoryFields: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    validatedAt: str | None = None
    errorSummary: str | None = None

    model_config = ConfigDict(extra="ignore")


class AuthoritativeVerificationRecord(BaseModel):
    provider: str = "SyntheticDigiLockerProvider"
    status: str
    lookupIdentifier: str | None = None
    lookupField: str | None = None
    isSimulated: bool = True
    disclaimer: str = (
        "Simulated record for testing/evaluation. Not connected to live DigiLocker/government APIs."
    )
    verifiedAt: str | None = None
    recordData: dict[str, Any] | None = None
    message: str | None = None

    model_config = ConfigDict(extra="ignore")


class DocumentVerificationDetailsResponse(BaseModel):
    documentId: str
    documentType: str
    lifecycleStatus: str
    processingStatus: str | None = None
    processingConfidence: float | None = None
    validationStatus: str = "NOT_RUN"
    validationResult: DocumentValidationResult | None = None
    authoritativeVerification: AuthoritativeVerificationRecord | None = None
    extractionSummary: dict[str, Any] | None = None

    model_config = ConfigDict(extra="ignore")
