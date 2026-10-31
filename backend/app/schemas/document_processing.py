from typing import Any
from pydantic import BaseModel, ConfigDict, Field


PROCESSING_STATES = [
    "NOT_STARTED",
    "PROCESSING",
    "COMPLETED",
    "FAILED",
]


class ExtractedField(BaseModel):
    """
    Structured extraction of a single field with raw text snippet,
    normalized value, confidence score (0.0 to 1.0), and page/line evidence.
    """
    rawValue: str | None = None
    normalizedValue: Any | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: str | None = None

    model_config = ConfigDict(extra="ignore")


class ExtractedFields(BaseModel):
    """
    Container for all candidate academic and identity fields.
    Fields are present only when supported by the document.
    """
    candidateName: ExtractedField | None = None
    dob: ExtractedField | None = None
    registrationNumber: ExtractedField | None = None
    institution: ExtractedField | None = None
    course: ExtractedField | None = None
    marksObtained: ExtractedField | None = None
    maxMarks: ExtractedField | None = None
    percentage: ExtractedField | None = None
    cgpa: ExtractedField | None = None
    certificateNumber: ExtractedField | None = None
    issueDate: ExtractedField | None = None
    passingYear: ExtractedField | None = None
    mathematics: ExtractedField | None = None

    model_config = ConfigDict(extra="ignore")


class ClassificationResult(BaseModel):
    """
    Explainable document classification based on transparent, layout-independent heuristics.
    """
    predictedType: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    typeMismatch: bool = False
    observation: str | None = None

    model_config = ConfigDict(extra="ignore")


class DocumentProcessingResult(BaseModel):
    """
    Complete persistent processing result for an uploaded document.
    """
    documentId: str
    applicationId: str | None = None
    documentType: str
    processingState: str = "NOT_STARTED"
    engine: str = "pymupdf+tesseract-ocr"
    pageCount: int = 0
    textExtracted: bool = False
    classification: ClassificationResult = Field(default_factory=ClassificationResult)
    fields: ExtractedFields = Field(default_factory=ExtractedFields)
    overallConfidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)
    errorMessage: str | None = None
    processedAt: str | None = None
    durationMs: int | None = None

    model_config = ConfigDict(extra="ignore")
