"""
Smart Enroll - Deterministic Server-Side Eligibility Engine
Increment 16: Pure, auditable eligibility evaluation following Design Decisions D2-D7.

Rules:
1. Pure function: No database, network, clock (datetime.now), or randomness inside.
2. Given identical inputs, always returns identical outputs and inputHash.
3. Decides solely on values extracted from documents with validationStatus == 'VALIDATED'.
4. Declared application values are used solely for cross-checks / audit context.
"""

from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


EVALUATOR_VERSION = "1.0.0"

# =============================================================================
# Documented Degree Qualification Normalization Table (D4)
# Maps normalized string -> (Canonical Degree Name, Degree Family, Academic Level)
# =============================================================================
DEGREE_NORMALIZATION_TABLE: dict[str, tuple[str, str, str]] = {
    # Engineering & Technology family
    "be": ("Bachelor of Engineering", "ENGINEERING_TECHNOLOGY", "BACHELORS"),
    "b e": ("Bachelor of Engineering", "ENGINEERING_TECHNOLOGY", "BACHELORS"),
    "btech": ("Bachelor of Technology", "ENGINEERING_TECHNOLOGY", "BACHELORS"),
    "b tech": ("Bachelor of Technology", "ENGINEERING_TECHNOLOGY", "BACHELORS"),
    "bachelor of engineering": ("Bachelor of Engineering", "ENGINEERING_TECHNOLOGY", "BACHELORS"),
    "bachelor of technology": ("Bachelor of Technology", "ENGINEERING_TECHNOLOGY", "BACHELORS"),
    "bse": ("Bachelor of Software Engineering", "ENGINEERING_TECHNOLOGY", "BACHELORS"),
    "bs engineering": ("Bachelor of Science in Engineering", "ENGINEERING_TECHNOLOGY", "BACHELORS"),

    # Computer Applications & Information Technology
    "bca": ("Bachelor of Computer Applications", "COMPUTER_APPLICATIONS", "BACHELORS"),
    "b c a": ("Bachelor of Computer Applications", "COMPUTER_APPLICATIONS", "BACHELORS"),
    "bachelor of computer applications": ("Bachelor of Computer Applications", "COMPUTER_APPLICATIONS", "BACHELORS"),
    "bsc cs": ("Bachelor of Science in Computer Science", "SCIENCE", "BACHELORS"),
    "b sc cs": ("Bachelor of Science in Computer Science", "SCIENCE", "BACHELORS"),
    "bsc computer science": ("Bachelor of Science in Computer Science", "SCIENCE", "BACHELORS"),
    "b sc computer science": ("Bachelor of Science in Computer Science", "SCIENCE", "BACHELORS"),
    "bsc it": ("Bachelor of Science in Information Technology", "SCIENCE", "BACHELORS"),
    "b sc it": ("Bachelor of Science in Information Technology", "SCIENCE", "BACHELORS"),
    "bachelor of science in computer science": ("Bachelor of Science in Computer Science", "SCIENCE", "BACHELORS"),
    "bachelor of science in information technology": ("Bachelor of Science in Information Technology", "SCIENCE", "BACHELORS"),

    # Science
    "bsc": ("Bachelor of Science", "SCIENCE", "BACHELORS"),
    "b sc": ("Bachelor of Science", "SCIENCE", "BACHELORS"),
    "bachelor of science": ("Bachelor of Science", "SCIENCE", "BACHELORS"),

    # Commerce & Management
    "bcom": ("Bachelor of Commerce", "COMMERCE", "BACHELORS"),
    "b com": ("Bachelor of Commerce", "COMMERCE", "BACHELORS"),
    "bachelor of commerce": ("Bachelor of Commerce", "COMMERCE", "BACHELORS"),
    "bba": ("Bachelor of Business Administration", "MANAGEMENT", "BACHELORS"),
    "b b a": ("Bachelor of Business Administration", "MANAGEMENT", "BACHELORS"),
    "bbm": ("Bachelor of Business Management", "MANAGEMENT", "BACHELORS"),
    "bachelor of business administration": ("Bachelor of Business Administration", "MANAGEMENT", "BACHELORS"),

    # Arts & Humanities
    "ba": ("Bachelor of Arts", "ARTS", "BACHELORS"),
    "b a": ("Bachelor of Arts", "ARTS", "BACHELORS"),
    "bachelor of arts": ("Bachelor of Arts", "ARTS", "BACHELORS"),

    # Architecture, Pharmacy, Law, Medicine
    "barch": ("Bachelor of Architecture", "ARCHITECTURE", "BACHELORS"),
    "b arch": ("Bachelor of Architecture", "ARCHITECTURE", "BACHELORS"),
    "bpharm": ("Bachelor of Pharmacy", "PHARMACY", "BACHELORS"),
    "b pharm": ("Bachelor of Pharmacy", "PHARMACY", "BACHELORS"),
    "llb": ("Bachelor of Laws", "LAW", "BACHELORS"),
    "mbbs": ("Bachelor of Medicine, Bachelor of Surgery", "MEDICINE", "BACHELORS"),
}


class RuleEvidence(BaseModel):
    model_config = ConfigDict(extra="ignore")

    documentId: str | None = None
    documentType: str
    field: str
    value: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SingleRuleEvaluation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ruleId: str
    name: str
    configured: dict[str, Any]
    observed: dict[str, Any]
    result: str  # "PASSED", "FAILED", "NEEDS_REVIEW", "NOT_APPLICABLE"
    reason: str
    evidence: list[RuleEvidence] = Field(default_factory=list)


class EligibilityEvaluationResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str  # "ELIGIBLE", "INELIGIBLE", "NEEDS_REVIEW"
    ruleVersion: str
    evaluatorVersion: str = EVALUATOR_VERSION
    inputHash: str
    summary: str
    rules: list[SingleRuleEvaluation]


# =============================================================================
# Pure Helper Functions
# =============================================================================

def clean_for_hashing(obj: Any) -> Any:
    """Recursively clean dict/list objects for deterministic JSON serialization."""
    if isinstance(obj, dict):
        clean = {}
        for k, v in obj.items():
            # Exclude MongoDB internal identifiers and volatile run identifiers
            if k in ("_id", "updatedAt", "createdAt", "activeRunId", "eligibilityResult"):
                continue
            clean[k] = clean_for_hashing(v)
        return clean
    elif isinstance(obj, list):
        return [clean_for_hashing(item) for item in obj]
    elif isinstance(obj, (int, float, bool, str)) or obj is None:
        return obj
    else:
        return str(obj)


def compute_input_hash(
    rules: dict[str, Any],
    application_snapshot: dict[str, Any],
    documents_snapshot: list[dict[str, Any]],
) -> str:
    """
    Computes a deterministic SHA-256 hash over canonical inputs (D7).
    Documents are sorted by documentType and documentId to guarantee order invariance.
    """
    sorted_docs = sorted(
        documents_snapshot,
        key=lambda d: (str(d.get("documentType", "")), str(d.get("documentId", ""))),
    )

    canonical_data = {
        "rules": clean_for_hashing(rules),
        "application": clean_for_hashing(application_snapshot),
        "documents": clean_for_hashing(sorted_docs),
    }

    serialized = json.dumps(canonical_data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def normalize_degree(degree_str: str | None) -> tuple[str, str, str] | None:
    """
    Normalize raw degree string using DEGREE_NORMALIZATION_TABLE (D4).
    Matches either the whole normalized string or the leading degree token only.
    Bare-word substring matching anywhere in the text is strictly forbidden.
    Returns (Canonical Name, Degree Family, Degree Level) or None if unrecognized.
    """
    if not degree_str or not isinstance(degree_str, str):
        return None

    cleaned = re.sub(r"[^\w\s]", " ", degree_str.lower()).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        return None

    # Check matches against known degree patterns, prioritizing longer/more specific degree phrases first
    # Match must anchor to the start of the string (^): whole string or leading token
    for key in sorted(DEGREE_NORMALIZATION_TABLE.keys(), key=len, reverse=True):
        if re.match(r"^" + re.escape(key) + r"(?:\b|\s|$)", cleaned):
            return DEGREE_NORMALIZATION_TABLE[key]

    return None


def get_doc_fields(doc: dict[str, Any]) -> dict[str, Any]:
    """Retrieve structured fields dictionary regardless of MongoDB nesting format."""
    if "extractedFields" in doc and isinstance(doc["extractedFields"], dict):
        return doc["extractedFields"]
    if "fields" in doc and isinstance(doc["fields"], dict):
        return doc["fields"]
    proc = doc.get("processingResult")
    if isinstance(proc, dict) and "fields" in proc and isinstance(proc["fields"], dict):
        return proc["fields"]
    ext_data = doc.get("extracted_data")
    if isinstance(ext_data, dict) and "fields" in ext_data and isinstance(ext_data["fields"], dict):
        return ext_data["fields"]
    return {}


def extract_field_value(field_dict: dict[str, Any], field_name: str) -> Any:
    """Extract normalized or raw value for a named field."""
    field_entry = field_dict.get(field_name)
    if field_entry is None:
        return None
    if isinstance(field_entry, dict):
        norm = field_entry.get("normalizedValue")
        if norm is not None:
            return norm
        return field_entry.get("rawValue")
    return field_entry


def sort_evidence(evidence_list: list[RuleEvidence]) -> list[RuleEvidence]:
    """Sort evidence list deterministically by documentType, field, documentId, and value."""
    return sorted(
        evidence_list,
        key=lambda e: (
            str(e.documentType),
            str(e.field),
            str(e.documentId or ""),
            str(e.value),
        ),
    )


# =============================================================================
# Pure Eligibility Evaluator
# =============================================================================

def evaluate_eligibility(
    rules: dict[str, Any],
    application_snapshot: dict[str, Any],
    documents_snapshot: list[dict[str, Any]],
) -> EligibilityEvaluationResult:
    """
    Pure, auditable function evaluating eligibility criteria against application & document evidence.
    Returns structured EligibilityEvaluationResult containing per-rule breakdown and overall status.
    """
    rule_version = str(rules.get("version", "1.0.0"))
    input_hash = compute_input_hash(rules, application_snapshot, documents_snapshot)

    # 1. Index validated documents by documentType deterministically (D2)
    # Sort snapshot by (documentType, documentId, createdAt) to ensure input order invariance
    sorted_docs = sorted(
        documents_snapshot,
        key=lambda d: (
            str(d.get("documentType", "")),
            str(d.get("documentId", "")),
            str(d.get("createdAt", "")),
        ),
    )

    validated_docs_by_type: dict[str, dict[str, Any]] = {}
    for doc in sorted_docs:
        doc_type = doc.get("documentType")
        val_status = doc.get("validationStatus")
        # D2: Values must come from documents whose validationStatus is VALIDATED
        if doc_type and val_status == "VALIDATED":
            # Deterministically retain the first validated document per type
            if doc_type not in validated_docs_by_type:
                validated_docs_by_type[doc_type] = doc

    evaluated_rules: list[SingleRuleEvaluation] = []

    # -------------------------------------------------------------------------
    # RULE 1: Document Completeness (D1, D2)
    # -------------------------------------------------------------------------
    required_doc_types = rules.get(
        "requiredDocumentTypes",
        [
            "10TH_MARKSHEET",
            "12TH_MARKSHEET",
            "UG_MARKSHEET",
            "DEGREE_CERTIFICATE",
            "TRANSFER_CERTIFICATE",
            "GOVERNMENT_ID",
        ],
    )
    missing_docs = [dtype for dtype in required_doc_types if dtype not in validated_docs_by_type]

    doc_evidence: list[RuleEvidence] = []
    for dtype in sorted(validated_docs_by_type.keys()):
        doc = validated_docs_by_type[dtype]
        doc_evidence.append(
            RuleEvidence(
                documentId=doc.get("documentId"),
                documentType=dtype,
                field="validationStatus",
                value="VALIDATED",
            )
        )
    doc_evidence = sort_evidence(doc_evidence)

    if missing_docs:
        evaluated_rules.append(
            SingleRuleEvaluation(
                ruleId="DOCUMENT_COMPLETENESS",
                name="Required Document Verification",
                configured={"requiredDocumentTypes": required_doc_types},
                observed={
                    "validatedTypes": sorted(list(validated_docs_by_type.keys())),
                    "missingTypes": sorted(missing_docs),
                },
                result="NEEDS_REVIEW",
                reason=f"Missing or unvalidated {len(missing_docs)} required document(s): {', '.join(sorted(missing_docs))}; incomplete document set.",
                evidence=doc_evidence,
            )
        )
    else:
        evaluated_rules.append(
            SingleRuleEvaluation(
                ruleId="DOCUMENT_COMPLETENESS",
                name="Required Document Verification",
                configured={"requiredDocumentTypes": required_doc_types},
                observed={"validatedTypes": sorted(list(validated_docs_by_type.keys()))},
                result="PASSED",
                reason=f"All {len(required_doc_types)} required documents verified and validated.",
                evidence=doc_evidence,
            )
        )

    # -------------------------------------------------------------------------
    # RULE 2: Minimum Qualification & Degree Family (D4)
    # -------------------------------------------------------------------------
    degree_cert = validated_docs_by_type.get("DEGREE_CERTIFICATE")
    deg_fields = get_doc_fields(degree_cert) if degree_cert else {}
    raw_course = (
        extract_field_value(deg_fields, "course")
        or extract_field_value(deg_fields, "degreeName")
    )

    allowed_families = rules.get("allowedDegreeFamilies", ["ANY"])
    required_level = rules.get("degreeLevel", "BACHELORS")

    # If no degree name on DEGREE_CERTIFICATE, fallback to UG_MARKSHEET course
    if not raw_course and "UG_MARKSHEET" in validated_docs_by_type:
        ug_fields = get_doc_fields(validated_docs_by_type["UG_MARKSHEET"])
        raw_course = (
            extract_field_value(ug_fields, "course")
            or extract_field_value(ug_fields, "degreeName")
        )

    norm_degree_info = normalize_degree(str(raw_course)) if raw_course else None

    # Cross-check declared form degree for audit context (D2)
    declared_ug_degree = application_snapshot.get("ugDegree") or application_snapshot.get("declaredUgDegree")

    qual_evidence: list[RuleEvidence] = []
    if raw_course and degree_cert:
        qual_evidence.append(
            RuleEvidence(
                documentId=degree_cert.get("documentId"),
                documentType=degree_cert.get("documentType", "DEGREE_CERTIFICATE"),
                field="course",
                value=str(raw_course),
                metadata={"declaredCrossCheck": str(declared_ug_degree) if declared_ug_degree else None},
            )
        )
    qual_evidence = sort_evidence(qual_evidence)

    if not raw_course or not norm_degree_info:
        evaluated_rules.append(
            SingleRuleEvaluation(
                ruleId="MIN_QUALIFICATION",
                name="Qualifying Degree Evaluation",
                configured={"requiredDegreeLevel": required_level, "allowedDegreeFamilies": allowed_families},
                observed={"rawDegree": raw_course, "normalizedDegree": None},
                result="NEEDS_REVIEW",
                reason=f"Qualifying degree '{raw_course or 'None'}' could not be resolved from verified documents; manual evaluation required.",
                evidence=qual_evidence,
            )
        )
    else:
        norm_name, family, level = norm_degree_info
        # Check level
        level_match = (level == required_level)
        # Check family
        family_match = ("ANY" in allowed_families or family in allowed_families)

        if not level_match:
            evaluated_rules.append(
                SingleRuleEvaluation(
                    ruleId="MIN_QUALIFICATION",
                    name="Qualifying Degree Evaluation",
                    configured={"requiredDegreeLevel": required_level, "allowedDegreeFamilies": allowed_families},
                    observed={"normalizedDegree": norm_name, "family": family, "level": level},
                    result="FAILED",
                    reason=f"Degree level '{level}' does not meet required '{required_level}' level.",
                    evidence=qual_evidence,
                )
            )
        elif not family_match:
            # e.g. M.Tech CS requires ENGINEERING_TECHNOLOGY family
            evaluated_rules.append(
                SingleRuleEvaluation(
                    ruleId="MIN_QUALIFICATION",
                    name="Qualifying Degree Evaluation",
                    configured={"requiredDegreeLevel": required_level, "allowedDegreeFamilies": allowed_families},
                    observed={"normalizedDegree": norm_name, "family": family, "level": level},
                    result="FAILED",
                    reason=f"Degree family '{family}' ({norm_name}) does not meet required {allowed_families} family.",
                    evidence=qual_evidence,
                )
            )
        else:
            evaluated_rules.append(
                SingleRuleEvaluation(
                    ruleId="MIN_QUALIFICATION",
                    name="Qualifying Degree Evaluation",
                    configured={"requiredDegreeLevel": required_level, "allowedDegreeFamilies": allowed_families},
                    observed={"normalizedDegree": norm_name, "family": family, "level": level},
                    result="PASSED",
                    reason=f"Degree '{norm_name}' meets qualification requirement for family {allowed_families}.",
                    evidence=qual_evidence,
                )
            )

    # -------------------------------------------------------------------------
    # RULE 3: Minimum Aggregate Percentage / CGPA (D3)
    # -------------------------------------------------------------------------
    min_pct_conf = rules.get("minPercentage", 50.0)
    cgpa_factor_conf = rules.get("cgpaToPercentageFactor", 9.5)

    try:
        d_min_percentage = Decimal(str(min_pct_conf))
        d_cgpa_factor = Decimal(str(cgpa_factor_conf))
    except (InvalidOperation, ValueError, TypeError):
        d_min_percentage = Decimal("50.0")
        d_cgpa_factor = Decimal("9.5")

    # Locate percentage or CGPA from UG_MARKSHEET, fallback to DEGREE_CERTIFICATE
    marks_doc = validated_docs_by_type.get("UG_MARKSHEET") or validated_docs_by_type.get("DEGREE_CERTIFICATE")
    marks_fields = get_doc_fields(marks_doc) if marks_doc else {}

    raw_percentage = extract_field_value(marks_fields, "percentage")
    raw_cgpa = extract_field_value(marks_fields, "cgpa")
    raw_cgpa_scale = extract_field_value(marks_fields, "cgpaScale")

    # If raw_cgpa is formatted as "X/Y" (e.g. "3.5/4.0"), split value and scale
    if raw_cgpa is not None and isinstance(raw_cgpa, str) and "/" in raw_cgpa:
        parts = raw_cgpa.split("/", 1)
        raw_cgpa = parts[0].strip()
        if raw_cgpa_scale is None:
            raw_cgpa_scale = parts[1].strip()

    pct_evidence: list[RuleEvidence] = []
    pct_observed: dict[str, Any] = {}
    pct_result: str = "NEEDS_REVIEW"
    pct_reason: str = ""

    if raw_percentage is not None:
        try:
            d_observed_pct = Decimal(str(raw_percentage))
            pct_observed["rawPercentage"] = str(d_observed_pct)

            # Out-of-range (<0 or >100) gives NEEDS_REVIEW, never FAILED
            if d_observed_pct < Decimal("0") or d_observed_pct > Decimal("100"):
                pct_result = "NEEDS_REVIEW"
                pct_reason = f"Extracted percentage {d_observed_pct}% is outside valid range (0 to 100); manual review required."
            elif d_observed_pct >= d_min_percentage:
                pct_result = "PASSED"
                pct_reason = f"Extracted percentage {d_observed_pct}% meets or exceeds minimum {d_min_percentage}%."
            else:
                pct_result = "FAILED"
                pct_reason = f"Extracted percentage {d_observed_pct}% is below minimum required {d_min_percentage}%."

            if marks_doc:
                pct_evidence.append(
                    RuleEvidence(
                        documentId=marks_doc.get("documentId"),
                        documentType=marks_doc.get("documentType", "UG_MARKSHEET"),
                        field="percentage",
                        value=str(d_observed_pct),
                    )
                )
        except (InvalidOperation, ValueError, TypeError):
            pct_result = "NEEDS_REVIEW"
            pct_reason = f"Extracted percentage '{raw_percentage}' is not a valid decimal number; manual review required."

    elif raw_cgpa is not None:
        # Check scale first: convert CGPA only for scale 10; unknown or other scales give NEEDS_REVIEW
        if raw_cgpa_scale is None:
            pct_result = "NEEDS_REVIEW"
            pct_reason = f"Extracted CGPA '{raw_cgpa}' has unknown grading scale; manual review required."
            pct_observed["rawCgpa"] = str(raw_cgpa)
            pct_observed["cgpaScale"] = None
        else:
            try:
                d_scale = Decimal(str(raw_cgpa_scale))
                pct_observed["cgpaScale"] = str(d_scale)
                if d_scale != Decimal("10"):
                    # Other scale (e.g. 4.0 as in 3.5/4.0) gives NEEDS_REVIEW
                    pct_result = "NEEDS_REVIEW"
                    pct_reason = f"Extracted CGPA scale {d_scale} is not standard scale 10; manual review required."
                    pct_observed["rawCgpa"] = str(raw_cgpa)
                else:
                    # Scale 10: evaluate CGPA
                    try:
                        d_observed_cgpa = Decimal(str(raw_cgpa))
                        pct_observed["rawCgpa"] = str(d_observed_cgpa)
                        pct_observed["cgpaToPercentageFactor"] = str(d_cgpa_factor)

                        # Out-of-range (<0 or >10) gives NEEDS_REVIEW, never FAILED
                        if d_observed_cgpa < Decimal("0") or d_observed_cgpa > Decimal("10"):
                            pct_result = "NEEDS_REVIEW"
                            pct_reason = f"Extracted CGPA {d_observed_cgpa} is outside valid 0 to 10 scale; manual review required."
                        else:
                            computed_pct = d_observed_cgpa * d_cgpa_factor
                            pct_observed["computedPercentage"] = str(computed_pct)

                            if computed_pct < Decimal("0") or computed_pct > Decimal("100"):
                                pct_result = "NEEDS_REVIEW"
                                pct_reason = f"Computed percentage {computed_pct}% from CGPA {d_observed_cgpa} is outside valid 0 to 100 range; manual review required."
                            elif computed_pct >= d_min_percentage:
                                pct_result = "PASSED"
                                pct_reason = f"Computed percentage {computed_pct}% (CGPA {d_observed_cgpa} × {d_cgpa_factor}) meets or exceeds minimum {d_min_percentage}%."
                            else:
                                pct_result = "FAILED"
                                pct_reason = f"Computed percentage {computed_pct}% (CGPA {d_observed_cgpa} × {d_cgpa_factor}) is below minimum required {d_min_percentage}%."

                        if marks_doc:
                            pct_evidence.append(
                                RuleEvidence(
                                    documentId=marks_doc.get("documentId"),
                                    documentType=marks_doc.get("documentType", "UG_MARKSHEET"),
                                    field="cgpa",
                                    value=str(d_observed_cgpa),
                                    metadata={
                                        "computedPercentage": str(pct_observed.get("computedPercentage")),
                                        "cgpaToPercentageFactor": str(d_cgpa_factor),
                                        "cgpaScale": str(d_scale),
                                    },
                                )
                            )
                    except (InvalidOperation, ValueError, TypeError):
                        pct_result = "NEEDS_REVIEW"
                        pct_reason = f"Extracted CGPA '{raw_cgpa}' is not a valid decimal number; manual review required."
            except (InvalidOperation, ValueError, TypeError):
                pct_result = "NEEDS_REVIEW"
                pct_reason = f"Extracted CGPA scale '{raw_cgpa_scale}' is not a valid decimal number; manual review required."
    else:
        pct_result = "NEEDS_REVIEW"
        pct_reason = "Neither aggregate percentage nor CGPA was found in verified marksheets; manual review required."

    pct_evidence = sort_evidence(pct_evidence)
    evaluated_rules.append(
        SingleRuleEvaluation(
            ruleId="MIN_PERCENTAGE",
            name="Minimum Qualifying Marks",
            configured={"minPercentage": str(d_min_percentage), "cgpaToPercentageFactor": str(d_cgpa_factor)},
            observed=pct_observed,
            result=pct_result,
            reason=pct_reason,
            evidence=pct_evidence,
        )
    )

    # -------------------------------------------------------------------------
    # RULE 4: Mathematics Prerequisite (D5)
    # -------------------------------------------------------------------------
    math_req = rules.get("mathematicsRequirement", "NONE")
    math_evidence: list[RuleEvidence] = []
    math_result: str = "NEEDS_REVIEW"
    math_reason: str = ""

    if math_req == "NONE":
        math_result = "PASSED"
        math_reason = "Mathematics is not required for this programme."
    else:
        # Check UG_MARKSHEET and 12TH_MARKSHEET
        ug_doc = validated_docs_by_type.get("UG_MARKSHEET")
        twelfth_doc = validated_docs_by_type.get("12TH_MARKSHEET")

        def check_math_in_doc(doc: dict[str, Any] | None) -> tuple[bool, str | None, str | None]:
            if not doc:
                return False, None, None
            flds = get_doc_fields(doc)
            # Check structured field
            math_field = flds.get("mathematics")
            if isinstance(math_field, dict):
                norm = math_field.get("normalizedValue")
                line = str(math_field.get("matchedLine") or math_field.get("evidence") or math_field.get("rawValue") or "")
                raw_val = str(math_field.get("rawValue") or "")

                # Reject if line or evidence contains fail or absent markers
                if re.search(r"(?i)\b(?:fail|failed|f|ab|abs|absent|withheld)\b", line):
                    return False, None, None

                # Require a mark strictly above zero (> 0)
                mark_match = re.search(r"\b(\d{1,3}(?:\.\d{1,2})?)\b", raw_val or line)
                if mark_match:
                    try:
                        if float(mark_match.group(1)) <= 0:
                            return False, None, None
                    except ValueError:
                        return False, None, None

                if norm is True or (norm and str(norm).lower() in ("true", "passed", "yes")):
                    return True, str(mark_match.group(1) if mark_match else norm), line
            elif math_field is True:
                return True, "True", None

            # Fallback check rawText / ocrText with deterministic regex
            raw_text = doc.get("ocrText") or doc.get("rawText") or flds.get("ocrText")
            if raw_text and isinstance(raw_text, str):
                for line in raw_text.splitlines():
                    # Look for 'Mathematics' or 'Maths' with a numeric mark on the line
                    if re.search(r"(?i)\b(?:mathematics|maths)\b", line):
                        # Reject fail or absent markers
                        if re.search(r"(?i)\b(?:fail|failed|f|ab|abs|absent|withheld)\b", line):
                            continue
                        num_match = re.search(r"\b(\d{1,3}(?:\.\d{1,2})?)\b", line)
                        if num_match:
                            try:
                                mark_val = float(num_match.group(1))
                                if mark_val > 0:
                                    return True, num_match.group(1), line.strip()
                            except ValueError:
                                pass
            return False, None, None

        ug_math_found, ug_val, ug_line = check_math_in_doc(ug_doc)
        twelfth_math_found, twelfth_val, twelfth_line = check_math_in_doc(twelfth_doc)

        if math_req == "GRADUATION":
            # Must be found at graduation level (UG_MARKSHEET)
            if ug_math_found and ug_doc:
                math_result = "PASSED"
                math_reason = f"Mathematics verified at graduation level in UG Marksheet (Mark/Status: {ug_val})."
                math_evidence.append(
                    RuleEvidence(
                        documentId=ug_doc.get("documentId"),
                        documentType="UG_MARKSHEET",
                        field="mathematics",
                        value=str(ug_val),
                        metadata={"matchedLine": ug_line},
                    )
                )
            else:
                # D5: Missing OCR text is not proof of absence -> NEVER FAILED, gives NEEDS_REVIEW
                math_result = "NEEDS_REVIEW"
                math_reason = "Mathematics evidence was not detected at graduation level on UG Marksheet; requires manual review."

        elif math_req == "10+2_OR_GRADUATION":
            # Found at either 10+2 or graduation level gives PASSED
            if ug_math_found and ug_doc:
                math_result = "PASSED"
                math_reason = f"Mathematics verified at graduation level in UG Marksheet (Mark/Status: {ug_val})."
                math_evidence.append(
                    RuleEvidence(
                        documentId=ug_doc.get("documentId"),
                        documentType="UG_MARKSHEET",
                        field="mathematics",
                        value=str(ug_val),
                        metadata={"matchedLine": ug_line},
                    )
                )
            elif twelfth_math_found and twelfth_doc:
                math_result = "PASSED"
                math_reason = f"Mathematics verified at 10+2 level in 12th Marksheet (Mark/Status: {twelfth_val})."
                math_evidence.append(
                    RuleEvidence(
                        documentId=twelfth_doc.get("documentId"),
                        documentType="12TH_MARKSHEET",
                        field="mathematics",
                        value=str(twelfth_val),
                        metadata={"matchedLine": twelfth_line},
                    )
                )
            else:
                # D5: Missing OCR text is not proof of absence -> NEVER FAILED, gives NEEDS_REVIEW
                math_result = "NEEDS_REVIEW"
                math_reason = "Mathematics evidence was not detected on 12th Marksheet or UG Marksheet; requires manual review."

    math_evidence = sort_evidence(math_evidence)
    evaluated_rules.append(
        SingleRuleEvaluation(
            ruleId="MATHEMATICS_REQUIREMENT",
            name="Mathematics Prerequisite",
            configured={"mathematicsRequirement": math_req},
            observed={"requirementMet": math_result == "PASSED"},
            result=math_result,
            reason=math_reason,
            evidence=math_evidence,
        )
    )

    # -------------------------------------------------------------------------
    # RULE 5: Entrance Exam Requirement (D1)
    # -------------------------------------------------------------------------
    entrance_required = rules.get("entranceRequired", False)
    if not entrance_required:
        evaluated_rules.append(
            SingleRuleEvaluation(
                ruleId="ENTRANCE_EXAM",
                name="Entrance Examination",
                configured={"entranceRequired": False},
                observed={"required": False},
                result="NOT_APPLICABLE",
                reason="Entrance examination is not applicable for this programme.",
                evidence=[],
            )
        )
    else:
        # For future increments if applicable
        evaluated_rules.append(
            SingleRuleEvaluation(
                ruleId="ENTRANCE_EXAM",
                name="Entrance Examination",
                configured={"entranceRequired": True},
                observed={"score": None},
                result="NEEDS_REVIEW",
                reason="Entrance score verification requires manual review.",
                evidence=[],
            )
        )

    # -------------------------------------------------------------------------
    # OVERALL OUTCOME HIERARCHY (D6)
    # Any FAILED -> INELIGIBLE
    # Else any NEEDS_REVIEW -> NEEDS_REVIEW
    # Else -> ELIGIBLE
    # -------------------------------------------------------------------------
    has_failed = any(r.result == "FAILED" for r in evaluated_rules)
    has_review = any(r.result == "NEEDS_REVIEW" for r in evaluated_rules)

    if has_failed:
        overall_status = "INELIGIBLE"
        failed_reasons = [r.reason for r in evaluated_rules if r.result == "FAILED"]
        summary = f"Ineligible: {'; '.join(failed_reasons)}"
    elif has_review:
        overall_status = "NEEDS_REVIEW"
        review_reasons = [r.reason for r in evaluated_rules if r.result == "NEEDS_REVIEW"]
        summary = f"Manual Review Required: {'; '.join(review_reasons)}"
    else:
        overall_status = "ELIGIBLE"
        summary = "All admission eligibility criteria fully met and verified on authoritative evidence."

    return EligibilityEvaluationResult(
        status=overall_status,
        ruleVersion=rule_version,
        evaluatorVersion=EVALUATOR_VERSION,
        inputHash=input_hash,
        summary=summary,
        rules=evaluated_rules,
    )
