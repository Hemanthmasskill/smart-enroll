from typing import Any
from pydantic import BaseModel, ConfigDict

DOCUMENT_TYPES = [
    "10TH_MARKSHEET",
    "12TH_MARKSHEET",
    "UG_MARKSHEET",
    "DEGREE_CERTIFICATE",
    "TRANSFER_CERTIFICATE",
    "GOVERNMENT_ID",
]

DEGREE_VARIANTS = [
    "ORIGINAL_DEGREE_CERTIFICATE",
    "PROVISIONAL_DEGREE_CERTIFICATE",
    "COURSE_COMPLETION_CERTIFICATE",
]

DOCUMENT_STATUSES = [
    "NOT_UPLOADED",
    "UPLOADED",
    "PROCESSING",
    "VALIDATED",
    "VERIFIED",
    "MISMATCH",
    "REJECTED",
    "UNVERIFIED",
]

FRONTEND_ID_TO_TYPE: dict[str, str] = {
    "doc-10th": "10TH_MARKSHEET",
    "doc-12th": "12TH_MARKSHEET",
    "doc-ug-marksheet": "UG_MARKSHEET",
    "doc-degree": "DEGREE_CERTIFICATE",
    "doc-transfer": "TRANSFER_CERTIFICATE",
    "doc-govt-id": "GOVERNMENT_ID",
}

TYPE_TO_FRONTEND_ID: dict[str, str] = {v: k for k, v in FRONTEND_ID_TO_TYPE.items()}

DOCUMENT_DISPLAY_NAMES: dict[str, str] = {
    "10TH_MARKSHEET": "10th Marksheet",
    "12TH_MARKSHEET": "12th Marksheet",
    "UG_MARKSHEET": "Undergraduate Marksheet",
    "DEGREE_CERTIFICATE": "Degree / Provisional Certificate",
    "TRANSFER_CERTIFICATE": "Transfer Certificate",
    "GOVERNMENT_ID": "Government ID",
}

DEGREE_VARIANT_DISPLAY_NAMES: dict[str, str] = {
    "ORIGINAL_DEGREE_CERTIFICATE": "Original Degree Certificate",
    "PROVISIONAL_DEGREE_CERTIFICATE": "Provisional Degree Certificate",
    "COURSE_COMPLETION_CERTIFICATE": "Course Completion Certificate",
}


def normalize_document_type(raw: str) -> str:
    """Normalize input string to canonical DOCUMENT_TYPES constant."""
    cleaned = raw.strip()
    if cleaned in FRONTEND_ID_TO_TYPE:
        return FRONTEND_ID_TO_TYPE[cleaned]
    upper = cleaned.upper().replace("-", "_")
    if upper in DOCUMENT_TYPES:
        return upper
    # Match against display names
    for dtype, dname in DOCUMENT_DISPLAY_NAMES.items():
        if cleaned.lower() == dname.lower():
            return dtype
    raise ValueError(
        f"Invalid document type '{raw}'. Allowed types: {', '.join(DOCUMENT_TYPES)}"
    )


def normalize_degree_variant(raw: str | None) -> str | None:
    """Normalize input string to canonical DEGREE_VARIANTS constant."""
    if raw is None or raw == "":
        return None
    cleaned = raw.strip()
    upper = cleaned.upper().replace("-", "_").replace(" ", "_")
    if upper in DEGREE_VARIANTS:
        return upper
    for variant, dname in DEGREE_VARIANT_DISPLAY_NAMES.items():
        if cleaned.lower() == dname.lower():
            return variant
    raise ValueError(
        f"Invalid documentVariant '{raw}'. Allowed variants: {', '.join(DEGREE_VARIANTS)}"
    )


class DocumentResponse(BaseModel):
    documentId: str | None = None
    id: str | None = None
    applicationId: str
    userId: str | None = None
    applicantId: str | None = None
    documentType: str
    documentVariant: str | None = None
    name: str
    originalFileName: str | None = None
    fileName: str | None = None
    contentType: str | None = None
    fileSize: int | None = None
    status: str
    processingStatus: str | None = None
    processingConfidence: float | None = None
    required: bool = True
    uploadedAt: str | None = None
    updatedAt: str | None = None

    model_config = ConfigDict(extra="ignore")


class DocumentDeleteResponse(BaseModel):
    detail: str
    documentId: str

    model_config = ConfigDict(extra="ignore")