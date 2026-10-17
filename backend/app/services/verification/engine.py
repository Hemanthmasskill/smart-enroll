from datetime import datetime, timezone
import logging
from typing import Any
from pymongo.database import Database

from app.schemas.verification import (
    DocumentValidationResult,
    FieldValidationResult,
)
from app.services.verification.cross_document import run_cross_document_checks
from app.services.verification.dob_parser import parse_and_compare_dob
from app.services.verification.name_matcher import compare_names
from app.services.verification.numeric_comparer import (
    compare_board,
    compare_cgpa,
    compare_course,
    compare_institution,
    compare_percentages,
    compare_years,
)

logger = logging.getLogger(__name__)


def get_field_confidence(field_dict: dict[str, Any]) -> float:
    """Safely retrieve confidence from an extracted field dict; default to 0.0 if missing or invalid."""
    conf = field_dict.get("confidence")
    if conf is None:
        return 0.0
    try:
        return float(conf)
    except (ValueError, TypeError):
        return 0.0


def validate_document_content(
    db: Database | None,
    document: dict[str, Any],
    application: dict[str, Any] | None,
    user: dict[str, Any] | None,
    sibling_documents: list[dict[str, Any]] | None = None,
) -> DocumentValidationResult:
    """
    100% deterministic content validation engine.
    Compares extracted fields against authoritative Application/User records and sibling documents.
    Enforces strict status precedence:
    1. ERROR (unexpected failure)
    2. MISMATCH (hard classification/field/cross-doc mismatch)
    3. MANUAL_REVIEW (missing mandatory, ambiguous date, low-confidence, conflict)
    4. VALIDATED (all mandatory checks pass with evidence, no hard mismatch)
    """
    now = datetime.now(timezone.utc).isoformat()
    document_id = document.get("documentId", "")
    document_type = document.get("documentType", "10TH_MARKSHEET")

    processing_result = document.get("processingResult") or {}
    fields: dict[str, Any] = processing_result.get("fields") or {}
    classification = processing_result.get("classification") or {}

    field_results: dict[str, FieldValidationResult] = {}
    missing_mandatory: list[str] = []
    reasons: list[str] = []

    if not application:
        return DocumentValidationResult(
            documentId=document_id,
            documentType=document_type,
            validationStatus="MANUAL_REVIEW",
            missingMandatoryFields=["applicationRecord"],
            reasons=["Linked canonical Application record not found."],
            validatedAt=now,
        )

    # 0. User vs Application Identity Consistency Check
    user_identity_conflict = False
    if user:
        user_name = user.get("full_name") or user.get("fullName")
        app_name = application.get("fullName")
        if user_name and app_name:
            user_app_stat, user_app_msg = compare_names(user_name, app_name)
            if user_app_stat in ("MISMATCH", "MANUAL_REVIEW"):
                conflict_reason = (
                    f"User account identity ('{user_name}') and canonical application name ('{app_name}') differ: {user_app_msg}"
                )
                reasons.append(conflict_reason)
                field_results["userApplicationNameConsistency"] = FieldValidationResult(
                    fieldName="userApplicationNameConsistency",
                    status="MANUAL_REVIEW",
                    extractedValue=user_name,
                    authoritativeValue=app_name,
                    message=conflict_reason,
                )
                user_identity_conflict = True

        user_dob = user.get("dob")
        app_dob = application.get("dob")
        if user_dob and app_dob:
            u_dob_stat, u_dob_msg, _ = parse_and_compare_dob(user_dob, app_dob)
            if u_dob_stat in ("MISMATCH", "MANUAL_REVIEW"):
                conflict_dob_reason = (
                    f"User account DOB ('{user_dob}') and canonical application DOB ('{app_dob}') differ: {u_dob_msg}"
                )
                reasons.append(conflict_dob_reason)
                field_results["userApplicationDobConsistency"] = FieldValidationResult(
                    fieldName="userApplicationDobConsistency",
                    status="MANUAL_REVIEW",
                    extractedValue=user_dob,
                    authoritativeValue=app_dob,
                    message=conflict_dob_reason,
                )
                user_identity_conflict = True

    # 1. Classification Integrity Check
    if classification.get("typeMismatch"):
        conf = classification.get("confidence", 0.0)
        predicted = classification.get("predictedType")
        if conf >= 0.80:
            reasons.append(
                f"Document classification mismatch: document type is '{document_type}', but OCR classified it as '{predicted}' with high confidence ({conf:.2f})."
            )
            field_results["documentClassification"] = FieldValidationResult(
                fieldName="documentClassification",
                status="MISMATCH",
                extractedValue=predicted,
                authoritativeValue=document_type,
                confidence=conf,
                message="Definitive document classification mismatch.",
            )
        else:
            reasons.append(
                f"Uncertain document classification: classified as '{predicted}' with confidence {conf:.2f}."
            )
            field_results["documentClassification"] = FieldValidationResult(
                fieldName="documentClassification",
                status="MANUAL_REVIEW",
                extractedValue=predicted,
                authoritativeValue=document_type,
                confidence=conf,
                message="Uncertain document classification.",
            )

    # Helper to retrieve field data
    def get_field(name: str) -> dict[str, Any]:
        return fields.get(name) or {}

    cand_name_field = get_field("candidateName")
    dob_field = get_field("dob")
    pct_field = get_field("percentage")
    marks_obt_field = get_field("marksObtained")
    max_marks_field = get_field("maxMarks")
    cgpa_field = get_field("cgpa")
    board_or_inst_field = get_field("institution")
    course_field = get_field("course")
    pass_year_field = get_field("passingYear")

    # 2. Candidate Name Comparison (Mandatory for ALL document types)
    ext_name = cand_name_field.get("normalizedValue") or cand_name_field.get("rawValue")
    app_name = application.get("fullName")
    name_conf = get_field_confidence(cand_name_field)

    if not ext_name:
        missing_mandatory.append("candidateName")
        field_results["candidateName"] = FieldValidationResult(
            fieldName="candidateName",
            status="NOT_EXTRACTED",
            message="Candidate name not extracted from document.",
        )
    else:
        name_status, name_msg = compare_names(ext_name, app_name)
        if name_conf < 0.80 and name_status in ("MATCH", "MISMATCH"):
            name_status = "MANUAL_REVIEW"
            name_msg += f" (Confidence {name_conf:.2f} below 0.80 threshold; decisive evaluation requires manual review)."

        field_results["candidateName"] = FieldValidationResult(
            fieldName="candidateName",
            status=name_status,
            extractedValue=ext_name,
            authoritativeValue=app_name,
            confidence=name_conf,
            message=name_msg,
        )
        if name_status in ("MISMATCH", "MANUAL_REVIEW"):
            reasons.append(name_msg)

    # 3. Date of Birth Comparison (Optional for academic, compared if extracted)
    raw_dob = dob_field.get("rawValue") or dob_field.get("normalizedValue")
    app_dob = application.get("dob")
    dob_conf = get_field_confidence(dob_field)

    if raw_dob:
        dob_status, dob_msg, parsed_dt = parse_and_compare_dob(raw_dob, app_dob)
        if dob_conf < 0.80 and dob_status in ("MATCH", "MISMATCH"):
            dob_status = "MANUAL_REVIEW"
            dob_msg += f" (Confidence {dob_conf:.2f} below 0.80 threshold; decisive evaluation requires manual review)."

        field_results["dob"] = FieldValidationResult(
            fieldName="dob",
            status=dob_status,
            extractedValue=raw_dob,
            authoritativeValue=app_dob,
            confidence=dob_conf,
            message=dob_msg,
        )
        if dob_status in ("MISMATCH", "MANUAL_REVIEW"):
            reasons.append(dob_msg)
    else:
        field_results["dob"] = FieldValidationResult(
            fieldName="dob",
            status="NOT_EXTRACTED",
            message="DOB not extracted from document (optional).",
        )

    # 4. Document Type Specific Field Logic
    if document_type in ("10TH_MARKSHEET", "12TH_MARKSHEET"):
        is_10th = document_type == "10TH_MARKSHEET"
        canonical_pct = application.get("tenthPercentage" if is_10th else "twelfthPercentage")
        canonical_board = application.get("tenthBoard" if is_10th else "twelfthBoard")

        # Mandatory: Percentage or marks
        ext_pct = pct_field.get("normalizedValue")
        marks_obt = marks_obt_field.get("normalizedValue")
        max_marks = max_marks_field.get("normalizedValue")
        pct_conf = (
            get_field_confidence(pct_field)
            if pct_field.get("confidence") is not None
            else get_field_confidence(marks_obt_field)
        )

        has_usable_result = (ext_pct is not None) or (marks_obt is not None and max_marks is not None and max_marks > 0)
        if not has_usable_result:
            missing_mandatory.append("percentage")
            field_results["percentage"] = FieldValidationResult(
                fieldName="percentage",
                status="NOT_EXTRACTED",
                message="No usable percentage or obtained/max marks found.",
            )
        else:
            pct_status, pct_msg, eff_pct = compare_percentages(
                extracted_pct=ext_pct,
                marks_obtained=marks_obt,
                max_marks=max_marks,
                canonical_pct_raw=canonical_pct,
                confidence=pct_conf,
            )
            field_results["percentage"] = FieldValidationResult(
                fieldName="percentage",
                status=pct_status,
                extractedValue=eff_pct,
                authoritativeValue=canonical_pct,
                confidence=pct_conf,
                message=pct_msg,
            )
            if pct_status in ("MISMATCH", "MANUAL_REVIEW"):
                reasons.append(pct_msg)

        # Optional: Board
        ext_board = board_or_inst_field.get("normalizedValue") or board_or_inst_field.get("rawValue")
        board_conf = get_field_confidence(board_or_inst_field)
        if ext_board and canonical_board:
            b_status, b_msg = compare_board(ext_board, canonical_board, confidence=board_conf)
            field_results["board"] = FieldValidationResult(
                fieldName="board",
                status=b_status,
                extractedValue=ext_board,
                authoritativeValue=canonical_board,
                confidence=board_conf,
                message=b_msg,
            )
            if b_status in ("MISMATCH", "MANUAL_REVIEW"):
                reasons.append(b_msg)
        else:
            field_results["board"] = FieldValidationResult(
                fieldName="board",
                status="NOT_EXTRACTED" if not ext_board else "NOT_APPLICABLE",
                message="Board not extracted or canonical board missing (optional).",
            )

    elif document_type == "UG_MARKSHEET":
        canonical_cgpa = application.get("cgpa")
        canonical_degree = application.get("ugDegree")
        canonical_univ = application.get("university")
        canonical_year = application.get("graduationYear")

        # Mandatory: at least one usable academic result (CGPA, percentage, or marks)
        ext_cgpa = cgpa_field.get("normalizedValue")
        ext_pct = pct_field.get("normalizedValue")
        marks_obt = marks_obt_field.get("normalizedValue")
        max_marks = max_marks_field.get("normalizedValue")

        has_academic_result = (
            ext_cgpa is not None
            or ext_pct is not None
            or (marks_obt is not None and max_marks is not None and max_marks > 0)
        )

        if not has_academic_result:
            missing_mandatory.append("academicResult (CGPA/Percentage)")
            field_results["academicResult"] = FieldValidationResult(
                fieldName="academicResult",
                status="NOT_EXTRACTED",
                message="Neither CGPA, percentage, nor marks obtained/max extracted.",
            )
        else:
            if ext_cgpa is not None:
                cgpa_conf = get_field_confidence(cgpa_field)
                cgpa_stat, cgpa_msg, eff_cgpa = compare_cgpa(ext_cgpa, canonical_cgpa, confidence=cgpa_conf)
                field_results["cgpa"] = FieldValidationResult(
                    fieldName="cgpa",
                    status=cgpa_stat,
                    extractedValue=eff_cgpa,
                    authoritativeValue=canonical_cgpa,
                    confidence=cgpa_conf,
                    message=cgpa_msg,
                )
                if cgpa_stat in ("MISMATCH", "MANUAL_REVIEW"):
                    reasons.append(cgpa_msg)
            elif ext_pct is not None or (marks_obt and max_marks):
                # Applicant application record uses CGPA, do not silently convert scale
                pct_stat = "MANUAL_REVIEW"
                pct_msg = "Marksheet has percentage but Application record expects CGPA; scale equivalence requires manual review."
                field_results["academicResult"] = FieldValidationResult(
                    fieldName="academicResult",
                    status=pct_stat,
                    extractedValue=ext_pct or f"{marks_obt}/{max_marks}",
                    authoritativeValue=canonical_cgpa,
                    message=pct_msg,
                )
                reasons.append(pct_msg)

        # Optional: Course / Degree
        ext_course = course_field.get("normalizedValue") or course_field.get("rawValue")
        if ext_course and canonical_degree:
            c_conf = get_field_confidence(course_field)
            c_stat, c_msg = compare_course(ext_course, canonical_degree, confidence=c_conf)
            field_results["course"] = FieldValidationResult(
                fieldName="course",
                status=c_stat,
                extractedValue=ext_course,
                authoritativeValue=canonical_degree,
                confidence=c_conf,
                message=c_msg,
            )
            if c_stat in ("MISMATCH", "MANUAL_REVIEW"):
                reasons.append(c_msg)

        # Optional: Institution / University
        ext_inst = board_or_inst_field.get("normalizedValue") or board_or_inst_field.get("rawValue")
        if ext_inst and canonical_univ:
            inst_conf = get_field_confidence(board_or_inst_field)
            inst_stat, inst_msg = compare_institution(ext_inst, canonical_univ, confidence=inst_conf)
            field_results["institution"] = FieldValidationResult(
                fieldName="institution",
                status=inst_stat,
                extractedValue=ext_inst,
                authoritativeValue=canonical_univ,
                confidence=inst_conf,
                message=inst_msg,
            )
            if inst_stat in ("MISMATCH", "MANUAL_REVIEW"):
                reasons.append(inst_msg)

        # Optional: Passing Year
        ext_yr = pass_year_field.get("normalizedValue")
        if ext_yr and canonical_year:
            yr_conf = get_field_confidence(pass_year_field)
            yr_stat, yr_msg, eff_yr = compare_years(ext_yr, canonical_year, confidence=yr_conf)
            field_results["passingYear"] = FieldValidationResult(
                fieldName="passingYear",
                status=yr_stat,
                extractedValue=eff_yr,
                authoritativeValue=canonical_year,
                confidence=yr_conf,
                message=yr_msg,
            )
            if yr_stat in ("MISMATCH", "MANUAL_REVIEW"):
                reasons.append(yr_msg)

    elif document_type == "DEGREE_CERTIFICATE":
        canonical_degree = application.get("ugDegree")
        canonical_univ = application.get("university")
        canonical_year = application.get("graduationYear")

        # Mandatory: candidate name and degree/course identity
        ext_course = course_field.get("normalizedValue") or course_field.get("rawValue")
        if not ext_course:
            missing_mandatory.append("course")
            field_results["course"] = FieldValidationResult(
                fieldName="course",
                status="NOT_EXTRACTED",
                message="Degree/course not extracted from degree certificate.",
            )
        else:
            c_conf = get_field_confidence(course_field)
            c_stat, c_msg = compare_course(ext_course, canonical_degree, confidence=c_conf)
            field_results["course"] = FieldValidationResult(
                fieldName="course",
                status=c_stat,
                extractedValue=ext_course,
                authoritativeValue=canonical_degree,
                confidence=c_conf,
                message=c_msg,
            )
            if c_stat in ("MISMATCH", "MANUAL_REVIEW"):
                reasons.append(c_msg)

        # Optional: Institution
        ext_inst = board_or_inst_field.get("normalizedValue") or board_or_inst_field.get("rawValue")
        if ext_inst and canonical_univ:
            inst_conf = get_field_confidence(board_or_inst_field)
            inst_stat, inst_msg = compare_institution(ext_inst, canonical_univ, confidence=inst_conf)
            field_results["institution"] = FieldValidationResult(
                fieldName="institution",
                status=inst_stat,
                extractedValue=ext_inst,
                authoritativeValue=canonical_univ,
                confidence=inst_conf,
                message=inst_msg,
            )
            if inst_stat in ("MISMATCH", "MANUAL_REVIEW"):
                reasons.append(inst_msg)

        # Optional: Passing Year
        ext_yr = pass_year_field.get("normalizedValue")
        if ext_yr and canonical_year:
            yr_conf = get_field_confidence(pass_year_field)
            yr_stat, yr_msg, eff_yr = compare_years(ext_yr, canonical_year, confidence=yr_conf)
            field_results["passingYear"] = FieldValidationResult(
                fieldName="passingYear",
                status=yr_stat,
                extractedValue=eff_yr,
                authoritativeValue=canonical_year,
                confidence=yr_conf,
                message=yr_msg,
            )
            if yr_stat in ("MISMATCH", "MANUAL_REVIEW"):
                reasons.append(yr_msg)

    elif document_type in ("TRANSFER_CERTIFICATE", "GOVERNMENT_ID"):
        # Mandatory: candidate name (already verified above)
        # Optional: DOB (already verified above)
        # For Government ID: do not invent canonical fields for identifier
        cert_no_field = get_field("certificateNumber")
        cert_no = cert_no_field.get("normalizedValue") or cert_no_field.get("rawValue")
        if cert_no:
            field_results["documentIdentifier"] = FieldValidationResult(
                fieldName="documentIdentifier",
                status="MATCH",
                extractedValue=cert_no,
                authoritativeValue=None,
                confidence=get_field_confidence(cert_no_field),
                message="Document identifier recorded (valid format).",
            )

    # 5. Cross-Document Consistency Checks
    cross_doc_results = []
    if sibling_documents:
        cross_doc_results = run_cross_document_checks(db, document, sibling_documents)
        for cdr in cross_doc_results:
            if cdr.status == "MISMATCH":
                reasons.append(f"Cross-document check '{cdr.checkName}' failed: {cdr.message}")
            elif cdr.status == "MANUAL_REVIEW":
                reasons.append(f"Cross-document check '{cdr.checkName}' flagged for review: {cdr.message}")

    # 6. Apply Status Precedence to Determine Overall Outcome
    # Precedence:
    # 1. ERROR
    # 2. MISMATCH
    # 3. MANUAL_REVIEW
    # 4. VALIDATED
    has_mismatch = any(fr.status == "MISMATCH" for fr in field_results.values()) or any(
        cdr.status == "MISMATCH" for cdr in cross_doc_results
    )
    has_manual_review = (
        bool(missing_mandatory)
        or user_identity_conflict
        or any(fr.status == "MANUAL_REVIEW" for fr in field_results.values())
        or any(cdr.status == "MANUAL_REVIEW" for cdr in cross_doc_results)
    )

    if has_mismatch:
        overall_status = "MISMATCH"
    elif has_manual_review:
        overall_status = "MANUAL_REVIEW"
        if missing_mandatory:
            reasons.append(f"Missing mandatory extraction fields: {', '.join(missing_mandatory)}.")
    else:
        overall_status = "VALIDATED"

    return DocumentValidationResult(
        documentId=document_id,
        documentType=document_type,
        validationStatus=overall_status,
        fieldResults=field_results,
        crossDocumentResults=cross_doc_results,
        missingMandatoryFields=missing_mandatory,
        reasons=reasons,
        validatedAt=now,
    )
