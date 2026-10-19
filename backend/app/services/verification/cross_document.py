from typing import Any
from pymongo.database import Database

from app.schemas.verification import CrossDocumentCheckResult
from app.services.verification.dob_parser import parse_and_compare_dob
from app.services.verification.name_matcher import compare_names
from app.services.verification.numeric_comparer import compare_years


def get_field_conf(f_dict: dict[str, Any] | None) -> float:
    """Extract float confidence from field dict, defaulting to 0.0 if missing or invalid."""
    if not f_dict:
        return 0.0
    c = f_dict.get("confidence")
    if c is None:
        return 0.0
    try:
        return float(c)
    except (ValueError, TypeError):
        return 0.0


def run_cross_document_checks(
    db: Database | None,
    current_doc: dict[str, Any],
    sibling_docs: list[dict[str, Any]],
) -> list[CrossDocumentCheckResult]:
    """
    Run cross-document consistency checks among documents belonging to the same application.
    If sibling documents are missing or not processed, returns SKIPPED (never false MATCH).
    Enforces 0.80 confidence threshold: low-confidence matches or mismatches become MANUAL_REVIEW.
    """
    results: list[CrossDocumentCheckResult] = []

    curr_type = current_doc.get("documentType", "")
    curr_proc = current_doc.get("processingResult", {}) or {}
    curr_fields = curr_proc.get("fields", {}) or {}

    curr_name = (curr_fields.get("candidateName") or {}).get("normalizedValue")
    curr_dob_raw = (curr_fields.get("dob") or {}).get("rawValue")
    curr_reg = (curr_fields.get("registrationNumber") or {}).get("normalizedValue")
    curr_year = (curr_fields.get("passingYear") or {}).get("normalizedValue")

    # Group sibling documents by type
    siblings_by_type: dict[str, dict[str, Any]] = {
        d.get("documentType"): d
        for d in sibling_docs
        if d.get("documentType") and d.get("documentType") != curr_type
    }

    # 1. Candidate Name Uniformity across applicable processed sibling documents
    for sib_type, sib_doc in siblings_by_type.items():
        sib_proc = sib_doc.get("processingResult")
        if not sib_proc or sib_doc.get("processingStatus") != "COMPLETED":
            results.append(
                CrossDocumentCheckResult(
                    checkName=f"Cross-Document Name Consistency ({curr_type} vs {sib_type})",
                    targetDocumentType=sib_type,
                    status="SKIPPED",
                    message=f"Sibling document '{sib_type}' is not yet processed; cross-document name check skipped.",
                )
            )
            continue

        sib_fields = sib_proc.get("fields", {}) or {}
        sib_name = (sib_fields.get("candidateName") or {}).get("normalizedValue")
        if not curr_name or not sib_name:
            results.append(
                CrossDocumentCheckResult(
                    checkName=f"Cross-Document Name Consistency ({curr_type} vs {sib_type})",
                    targetDocumentType=sib_type,
                    status="SKIPPED",
                    message="Candidate name not extracted on one or both documents; cross-document name check inconclusive.",
                )
            )
            continue

        curr_name_conf = get_field_conf(curr_fields.get("candidateName"))
        sib_name_conf = get_field_conf(sib_fields.get("candidateName"))
        min_name_conf = min(curr_name_conf, sib_name_conf)

        name_status, name_msg = compare_names(curr_name, sib_name)
        if min_name_conf < 0.80 and name_status in ("MATCH", "MISMATCH"):
            name_status = "MANUAL_REVIEW"
            name_msg += f" (Field confidence {min_name_conf:.2f} below 0.80 threshold; requires manual review)."

        results.append(
            CrossDocumentCheckResult(
                checkName=f"Cross-Document Name Consistency ({curr_type} vs {sib_type})",
                targetDocumentType=sib_type,
                status=name_status if name_status in ("MATCH", "MISMATCH", "MANUAL_REVIEW") else "MANUAL_REVIEW",
                message=f"Name consistency between '{curr_type}' and '{sib_type}': {name_msg}",
                details={"currentDocumentName": curr_name, "siblingDocumentName": sib_name},
            )
        )

    # 2. DOB Uniformity (e.g. between 10TH_MARKSHEET and GOVERNMENT_ID)
    if curr_type in ("10TH_MARKSHEET", "GOVERNMENT_ID"):
        target_type = "GOVERNMENT_ID" if curr_type == "10TH_MARKSHEET" else "10TH_MARKSHEET"
        target_doc = siblings_by_type.get(target_type)
        if not target_doc or target_doc.get("processingStatus") != "COMPLETED":
            results.append(
                CrossDocumentCheckResult(
                    checkName=f"DOB Consistency ({curr_type} vs {target_type})",
                    targetDocumentType=target_type,
                    status="SKIPPED",
                    message=f"Target document '{target_type}' is missing or not processed; DOB consistency check skipped.",
                )
            )
        else:
            target_fields = (target_doc.get("processingResult") or {}).get("fields", {}) or {}
            target_dob_raw = (target_fields.get("dob") or {}).get("rawValue")
            curr_dob_conf = get_field_conf(curr_fields.get("dob"))
            target_dob_conf = get_field_conf(target_fields.get("dob"))
            min_dob_conf = min(curr_dob_conf, target_dob_conf)

            if curr_dob_raw and target_dob_raw:
                dob_status, dob_msg, _ = parse_and_compare_dob(curr_dob_raw, target_dob_raw)
                if min_dob_conf < 0.80 and dob_status in ("MATCH", "MISMATCH"):
                    dob_status = "MANUAL_REVIEW"
                    dob_msg += f" (Field confidence {min_dob_conf:.2f} below 0.80 threshold; requires manual review)."

                results.append(
                    CrossDocumentCheckResult(
                        checkName=f"DOB Consistency ({curr_type} vs {target_type})",
                        targetDocumentType=target_type,
                        status=dob_status,
                        message=f"DOB consistency check between '{curr_type}' and '{target_type}': {dob_msg}",
                    )
                )
            else:
                results.append(
                    CrossDocumentCheckResult(
                        checkName=f"DOB Consistency ({curr_type} vs {target_type})",
                        targetDocumentType=target_type,
                        status="SKIPPED",
                        message=f"DOB not extracted from both '{curr_type}' and '{target_type}'; check skipped.",
                    )
                )

    # 3. UG Marksheet vs Degree Certificate Consistency (Registration Number & Passing Year)
    if curr_type in ("UG_MARKSHEET", "DEGREE_CERTIFICATE"):
        target_type = "DEGREE_CERTIFICATE" if curr_type == "UG_MARKSHEET" else "UG_MARKSHEET"
        target_doc = siblings_by_type.get(target_type)
        if not target_doc or target_doc.get("processingStatus") != "COMPLETED":
            results.append(
                CrossDocumentCheckResult(
                    checkName=f"Academic Consistency ({curr_type} vs {target_type})",
                    targetDocumentType=target_type,
                    status="SKIPPED",
                    message=f"Sibling '{target_type}' is missing or not processed; academic consistency check skipped.",
                )
            )
        else:
            target_fields = (target_doc.get("processingResult") or {}).get("fields", {}) or {}
            target_reg = (target_fields.get("registrationNumber") or {}).get("normalizedValue")
            target_year = (target_fields.get("passingYear") or {}).get("normalizedValue")

            # Check registration number
            if curr_reg and target_reg:
                curr_reg_conf = get_field_conf(curr_fields.get("registrationNumber"))
                target_reg_conf = get_field_conf(target_fields.get("registrationNumber"))
                min_reg_conf = min(curr_reg_conf, target_reg_conf)

                curr_reg_clean = str(curr_reg).strip().upper()
                target_reg_clean = str(target_reg).strip().upper()
                if curr_reg_clean == target_reg_clean:
                    reg_status = "MATCH"
                    reg_msg = f"Registration number ({curr_reg_clean}) matches between '{curr_type}' and '{target_type}'."
                else:
                    reg_status = "MISMATCH"
                    reg_msg = f"Registration number mismatch between '{curr_type}' ({curr_reg_clean}) and '{target_type}' ({target_reg_clean})."

                if min_reg_conf < 0.80 and reg_status in ("MATCH", "MISMATCH"):
                    reg_status = "MANUAL_REVIEW"
                    reg_msg += f" (Field confidence {min_reg_conf:.2f} below 0.80 threshold; requires manual review)."

                results.append(
                    CrossDocumentCheckResult(
                        checkName=f"Registration Number Consistency ({curr_type} vs {target_type})",
                        targetDocumentType=target_type,
                        status=reg_status,
                        message=reg_msg,
                    )
                )

            # Check passing year
            if curr_year and target_year:
                curr_yr_conf = get_field_conf(curr_fields.get("passingYear"))
                target_yr_conf = get_field_conf(target_fields.get("passingYear"))
                min_yr_conf = min(curr_yr_conf, target_yr_conf)

                yr_status, yr_msg, _ = compare_years(curr_year, target_year, confidence=min_yr_conf)
                results.append(
                    CrossDocumentCheckResult(
                        checkName=f"Passing Year Consistency ({curr_type} vs {target_type})",
                        targetDocumentType=target_type,
                        status=yr_status,
                        message=f"Passing year comparison between '{curr_type}' and '{target_type}': {yr_msg}",
                    )
                )

    # 4. Cross-Applicant Duplicate Check (targeted query on documents collection)
    if db is not None:
        user_id = current_doc.get("userId")
        identifiers_to_check = []
        if curr_reg:
            identifiers_to_check.append(("registrationNumber", str(curr_reg).strip()))
        cert_no = (curr_fields.get("certificateNumber") or {}).get("normalizedValue")
        if cert_no:
            identifiers_to_check.append(("certificateNumber", str(cert_no).strip()))

        for field_key, id_val in identifiers_to_check:
            # Query for another applicant with identical extracted identifier in the same document type
            duplicate = db["documents"].find_one({
                "userId": {"$ne": user_id},
                "documentType": curr_type,
                f"processingResult.fields.{field_key}.normalizedValue": id_val,
            })
            if duplicate:
                results.append(
                    CrossDocumentCheckResult(
                        checkName=f"Cross-Applicant Duplicate Check ({field_key})",
                        targetDocumentType=None,
                        status="MANUAL_REVIEW",
                        message=f"Document-specific identifier matches another registered record. Flagged for manual review.",
                        details={"field": field_key},
                    )
                )

    return results
