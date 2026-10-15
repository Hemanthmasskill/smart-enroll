from datetime import datetime, timezone
import time
from typing import Any

from app.schemas.document_processing import (
    ClassificationResult,
    DocumentProcessingResult,
    ExtractedFields,
)
from app.services.ocr.classifier import classify_document
from app.services.ocr.engine import (
    OCREngine,
    OCREngineUnavailableError,
    OCRProcessingError,
    get_ocr_engine,
)
from app.services.ocr.field_extractor import extract_fields_from_text
from app.services.ocr.image_processor import extract_text_from_image_bytes
from app.services.ocr.pdf_processor import process_pdf_bytes


def compute_overall_confidence(
    text: str,
    classification: ClassificationResult,
    fields: ExtractedFields,
) -> float:
    """
    Derive an explainable overall extraction-confidence score bounded within [0.0, 1.0].

    Semantics:
    - 0.0: No text or processing failed.
    - Component 1: Classification confidence (weight 0.30)
    - Component 2: Field extraction confidence (weight 0.45)
    - Component 3: Text completeness / token volume factor (weight 0.25)

    Limitation Note:
    A heuristic extraction confidence indicates how clearly text was recognized
    against known patterns. It does not calibrate statistical truth or prove authenticity.
    """
    if not text or not text.strip():
        return 0.0

    # 1. Classification component
    class_score = classification.confidence

    # 2. Extracted fields component
    field_scores: list[float] = []
    for field_name in ExtractedFields.model_fields:
        f = getattr(fields, field_name)
        if f is not None and getattr(f, "confidence", 0.0) > 0.0:
            field_scores.append(f.confidence)

    if field_scores:
        avg_field_score = sum(field_scores) / len(field_scores)
        # Bonus for capturing critical fields (name, roll, marks or institution)
        has_critical = any(
            getattr(fields, fn) is not None
            for fn in ["candidateName", "registrationNumber", "marksObtained", "cgpa", "institution"]
        )
        if has_critical:
            field_component = min(avg_field_score * 1.05, 1.0)
        else:
            field_component = avg_field_score
    else:
        # No recognized structured fields
        field_component = 0.15

    # 3. Text density factor: text with > 100 characters has adequate content
    word_count = len(text.split())
    text_factor = min(word_count / 80.0, 1.0)

    overall = (0.30 * class_score) + (0.45 * field_component) + (0.25 * text_factor)
    return round(max(0.0, min(overall, 0.99)), 2)


def run_document_processing_pipeline(
    file_bytes: bytes,
    content_type: str,
    document_id: str,
    document_type: str,
    application_id: str | None = None,
    engine: OCREngine | None = None,
) -> DocumentProcessingResult:
    """
    Execute bounded, end-to-end document processing:
    1. File decoding (PDF / Image) with resource boundaries
    2. Native text extraction or OCR
    3. Document classification
    4. Structured field extraction
    5. Normalization
    6. Overall confidence derivation
    7. Result compilation
    """
    start_time = time.perf_counter()
    ocr_engine = engine or get_ocr_engine()
    now_iso = datetime.now(timezone.utc).isoformat()

    all_warnings: list[str] = []
    raw_text = ""
    page_count = 1

    try:
        if content_type == "application/pdf":
            raw_text, page_count, pdf_warnings = process_pdf_bytes(
                file_bytes, ocr_engine=ocr_engine
            )
            all_warnings.extend(pdf_warnings)
        elif content_type in ("image/png", "image/jpeg", "image/jpg"):
            raw_text, img_warnings = extract_text_from_image_bytes(
                file_bytes, ocr_engine=ocr_engine
            )
            all_warnings.extend(img_warnings)
            page_count = 1
        else:
            raise ValueError(f"Unsupported content type for document processing: {content_type}")

        # Classification
        classification = classify_document(raw_text, expected_type=document_type)

        # Field extraction & normalization
        fields = extract_fields_from_text(raw_text, document_type=document_type)

        # Confidence calculation
        overall_conf = compute_overall_confidence(raw_text, classification, fields)

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        return DocumentProcessingResult(
            documentId=document_id,
            applicationId=application_id,
            documentType=document_type,
            processingState="COMPLETED",
            engine=ocr_engine.get_engine_name(),
            pageCount=page_count,
            textExtracted=bool(raw_text.strip()),
            classification=classification,
            fields=fields,
            overallConfidence=overall_conf,
            warnings=all_warnings,
            errorMessage=None,
            processedAt=now_iso,
            durationMs=duration_ms,
        )

    except OCREngineUnavailableError as e:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        return DocumentProcessingResult(
            documentId=document_id,
            applicationId=application_id,
            documentType=document_type,
            processingState="FAILED",
            engine=ocr_engine.get_engine_name(),
            pageCount=page_count,
            textExtracted=False,
            classification=ClassificationResult(),
            fields=ExtractedFields(),
            overallConfidence=0.0,
            warnings=all_warnings,
            errorMessage=str(e),
            processedAt=now_iso,
            durationMs=duration_ms,
        )

    except (OCRProcessingError, ValueError) as e:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        return DocumentProcessingResult(
            documentId=document_id,
            applicationId=application_id,
            documentType=document_type,
            processingState="FAILED",
            engine=ocr_engine.get_engine_name(),
            pageCount=page_count,
            textExtracted=False,
            classification=ClassificationResult(),
            fields=ExtractedFields(),
            overallConfidence=0.0,
            warnings=all_warnings,
            errorMessage=str(e),
            processedAt=now_iso,
            durationMs=duration_ms,
        )

    except Exception as e:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        return DocumentProcessingResult(
            documentId=document_id,
            applicationId=application_id,
            documentType=document_type,
            processingState="FAILED",
            engine=ocr_engine.get_engine_name(),
            pageCount=page_count,
            textExtracted=False,
            classification=ClassificationResult(),
            fields=ExtractedFields(),
            overallConfidence=0.0,
            warnings=all_warnings,
            errorMessage=f"Unexpected document processing error: {str(e)}",
            processedAt=now_iso,
            durationMs=duration_ms,
        )
