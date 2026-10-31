import copy
from decimal import Decimal
import pytest

from app.services.eligibility.engine import (
    EVALUATOR_VERSION,
    compute_input_hash,
    evaluate_eligibility,
    normalize_degree,
)
from app.services.programme_rules import CANONICAL_PROGRAMME_RULES_V1


def get_canonical_rule(programme_id: str) -> dict:
    for r in CANONICAL_PROGRAMME_RULES_V1:
        if r["programmeId"] == programme_id:
            return copy.deepcopy(r)
    raise ValueError(f"Unknown programme {programme_id}")


def build_test_documents(
    percentage: float | str | None = 65.0,
    cgpa: float | str | None = None,
    degree_name: str = "B.Tech",
    math_ug: bool = True,
    math_12th: bool = True,
    all_validated: bool = True,
) -> list[dict]:
    docs = []
    types = [
        "10TH_MARKSHEET",
        "12TH_MARKSHEET",
        "UG_MARKSHEET",
        "DEGREE_CERTIFICATE",
        "TRANSFER_CERTIFICATE",
        "GOVERNMENT_ID",
    ]
    for dtype in types:
        doc = {
            "documentId": f"doc_{dtype.lower()}",
            "documentType": dtype,
            "status": "VALIDATED" if all_validated else "UPLOADED",
            "validationStatus": "VALIDATED" if all_validated else "MANUAL_REVIEW",
            "extractedFields": {},
        }
        if dtype == "12TH_MARKSHEET":
            if math_12th:
                doc["extractedFields"]["mathematics"] = {
                    "normalizedValue": True,
                    "matchedLine": "Mathematics 85/100",
                }
        elif dtype == "UG_MARKSHEET":
            if percentage is not None:
                doc["extractedFields"]["percentage"] = {"normalizedValue": percentage}
            if cgpa is not None:
                doc["extractedFields"]["cgpa"] = {"normalizedValue": cgpa}
            if math_ug:
                doc["extractedFields"]["mathematics"] = {
                    "normalizedValue": True,
                    "matchedLine": "Engineering Mathematics-I 78",
                }
        elif dtype == "DEGREE_CERTIFICATE":
            doc["extractedFields"]["course"] = {"normalizedValue": degree_name}

        docs.append(doc)
    return docs


def test_determinism_same_inputs_same_output_and_hash():
    """Verify that pure evaluate_eligibility produces identical output and inputHash every time."""
    rules = get_canonical_rule("mca")
    app = {"applicationId": "APP-2026-001", "programmeId": "mca", "declaredUgDegree": "BCA"}
    docs = build_test_documents(percentage=60.0, degree_name="BCA", math_12th=True)

    res1 = evaluate_eligibility(rules, app, docs)
    res2 = evaluate_eligibility(rules, app, docs)

    assert res1.status == "ELIGIBLE"
    assert res1.inputHash == res2.inputHash
    assert res1.model_dump() == res2.model_dump()


def test_percentage_boundary_conditions_mca_and_mba():
    """Verify exact inclusive percentage boundary conditions for MCA and MBA (50.0% min)."""
    rules_mca = get_canonical_rule("mca")
    rules_mba = get_canonical_rule("mba")
    app = {"applicationId": "APP-001", "programmeId": "mca"}

    # 49.99% -> FAILED (never round up!)
    docs_49_99 = build_test_documents(percentage=49.99, degree_name="BCA")
    res_mca_fail = evaluate_eligibility(rules_mca, app, docs_49_99)
    assert res_mca_fail.status == "INELIGIBLE"
    rule_pct = next(r for r in res_mca_fail.rules if r.ruleId == "MIN_PERCENTAGE")
    assert rule_pct.result == "FAILED"

    # 50.00% -> PASSED (inclusive >=)
    docs_50_00 = build_test_documents(percentage=50.00, degree_name="BCA")
    res_mca_pass = evaluate_eligibility(rules_mca, app, docs_50_00)
    assert res_mca_pass.status == "ELIGIBLE"
    rule_pct = next(r for r in res_mca_pass.rules if r.ruleId == "MIN_PERCENTAGE")
    assert rule_pct.result == "PASSED"

    # 50.01% -> PASSED
    docs_50_01 = build_test_documents(percentage=50.01, degree_name="B.Com")
    res_mba_pass = evaluate_eligibility(rules_mba, app, docs_50_01)
    assert res_mba_pass.status == "ELIGIBLE"


def test_percentage_boundary_conditions_msc_and_mtech():
    """Verify percentage thresholds: MSc-CS (55.0% min) and MTech-CS (60.0% min)."""
    rules_msc = get_canonical_rule("msc-cs")
    rules_mtech = get_canonical_rule("mtech-cs")
    app = {"applicationId": "APP-001"}

    # MSc CS: 54.99% FAILED, 55.00% PASSED
    res_msc_fail = evaluate_eligibility(rules_msc, app, build_test_documents(percentage=54.99, degree_name="B.Sc CS"))
    assert res_msc_fail.status == "INELIGIBLE"

    res_msc_pass = evaluate_eligibility(rules_msc, app, build_test_documents(percentage=55.00, degree_name="B.Sc CS"))
    assert res_msc_pass.status == "ELIGIBLE"

    # MTech CS: 59.99% FAILED, 60.00% PASSED
    res_mtech_fail = evaluate_eligibility(rules_mtech, app, build_test_documents(percentage=59.99, degree_name="B.Tech"))
    assert res_mtech_fail.status == "INELIGIBLE"

    res_mtech_pass = evaluate_eligibility(rules_mtech, app, build_test_documents(percentage=60.00, degree_name="B.Tech"))
    assert res_mtech_pass.status == "ELIGIBLE"


def test_cgpa_conversion_and_factor():
    """Verify CGPA * factor (default 9.5) conversion around boundaries."""
    rules_mca = get_canonical_rule("mca")
    app = {"applicationId": "APP-001"}

    # CGPA 5.26 * 9.5 = 49.970% (< 50%) -> FAILED
    docs_cgpa_fail = build_test_documents(percentage=None, cgpa=5.26, degree_name="BCA")
    res_fail = evaluate_eligibility(rules_mca, app, docs_cgpa_fail)
    assert res_fail.status == "INELIGIBLE"
    pct_rule = next(r for r in res_fail.rules if r.ruleId == "MIN_PERCENTAGE")
    assert pct_rule.result == "FAILED"
    assert "49.97" in pct_rule.reason

    # CGPA 5.27 * 9.5 = 50.065% (>= 50%) -> PASSED
    docs_cgpa_pass = build_test_documents(percentage=None, cgpa=5.27, degree_name="BCA")
    res_pass = evaluate_eligibility(rules_mca, app, docs_cgpa_pass)
    assert res_pass.status == "ELIGIBLE"
    pct_rule = next(r for r in res_pass.rules if r.ruleId == "MIN_PERCENTAGE")
    assert pct_rule.result == "PASSED"
    assert pct_rule.evidence[0].metadata["cgpaToPercentageFactor"] == "9.5"


def test_invalid_percentage_and_cgpa_rejection():
    """Verify rejection of invalid percentages (<0, >100, non-numeric) and CGPA (<0, >10)."""
    rules = get_canonical_rule("mca")
    app = {"applicationId": "APP-001"}

    for invalid in [-5.0, 105.0, "not_a_number"]:
        res = evaluate_eligibility(rules, app, build_test_documents(percentage=invalid, degree_name="BCA"))
        assert res.status == "INELIGIBLE"
        pct_rule = next(r for r in res.rules if r.ruleId == "MIN_PERCENTAGE")
        assert pct_rule.result == "FAILED"

    # Invalid CGPA
    for invalid_cgpa in [-1.0, 11.5]:
        res = evaluate_eligibility(rules, app, build_test_documents(percentage=None, cgpa=invalid_cgpa, degree_name="BCA"))
        assert res.status == "INELIGIBLE"


def test_qualification_normalization_and_mtech_engineering_family():
    """Verify qualification normalization table and M.Tech CS engineering family enforcement."""
    rules_mtech = get_canonical_rule("mtech-cs")
    rules_mca = get_canonical_rule("mca")
    app = {"applicationId": "APP-001"}

    # MTech with Engineering degree (B.Tech, B.E) -> PASSED
    res_btech = evaluate_eligibility(rules_mtech, app, build_test_documents(percentage=70.0, degree_name="B.Tech"))
    assert res_btech.status == "ELIGIBLE"

    res_be = evaluate_eligibility(rules_mtech, app, build_test_documents(percentage=70.0, degree_name="B.E. Computer Science"))
    assert res_be.status == "ELIGIBLE"

    # MTech with Non-Engineering degree (B.Com, BA, BCA) -> FAILED
    for non_eng in ["B.Com", "BCA", "B.A", "BBA"]:
        res_non_eng = evaluate_eligibility(rules_mtech, app, build_test_documents(percentage=75.0, degree_name=non_eng))
        assert res_non_eng.status == "INELIGIBLE"
        qual_rule = next(r for r in res_non_eng.rules if r.ruleId == "MIN_QUALIFICATION")
        assert qual_rule.result == "FAILED"
        assert "ENGINEERING_TECHNOLOGY" in qual_rule.reason

    # Unknown degree name -> NEEDS_REVIEW
    res_unknown = evaluate_eligibility(rules_mca, app, build_test_documents(percentage=75.0, degree_name="Doctor of Philosophy in Divinity"))
    assert res_unknown.status == "NEEDS_REVIEW"
    qual_rule = next(r for r in res_unknown.rules if r.ruleId == "MIN_QUALIFICATION")
    assert qual_rule.result == "NEEDS_REVIEW"
    assert "could not be resolved" in qual_rule.reason


def test_mathematics_evidence_presence_and_absence():
    """Verify mathematics prerequisite logic: absence never yields FAILED, only NEEDS_REVIEW."""
    rules_mca = get_canonical_rule("mca")
    rules_mba = get_canonical_rule("mba")
    rules_msc = get_canonical_rule("msc-cs")
    app = {"applicationId": "APP-001"}

    # MBA does not require mathematics -> PASSED even if math is absent
    docs_no_math = build_test_documents(percentage=65.0, degree_name="B.Com", math_ug=False, math_12th=False)
    res_mba = evaluate_eligibility(rules_mba, app, docs_no_math)
    assert res_mba.status == "ELIGIBLE"

    # MCA requires math at 10+2 OR graduation
    # Math in 12th only -> PASSED
    docs_12th_math = build_test_documents(percentage=65.0, degree_name="BCA", math_ug=False, math_12th=True)
    res_mca_12th = evaluate_eligibility(rules_mca, app, docs_12th_math)
    assert res_mca_12th.status == "ELIGIBLE"

    # Math missing in both -> NEEDS_REVIEW (never FAILED!)
    res_mca_no_math = evaluate_eligibility(rules_mca, app, docs_no_math)
    assert res_mca_no_math.status == "NEEDS_REVIEW"
    math_rule = next(r for r in res_mca_no_math.rules if r.ruleId == "MATHEMATICS_REQUIREMENT")
    assert math_rule.result == "NEEDS_REVIEW"

    # MSc CS requires math at graduation level
    # If present in 12th but not in UG -> NEEDS_REVIEW
    res_msc_12th_only = evaluate_eligibility(rules_msc, app, docs_12th_math)
    assert res_msc_12th_only.status == "NEEDS_REVIEW"
    math_rule = next(r for r in res_msc_12th_only.rules if r.ruleId == "MATHEMATICS_REQUIREMENT")
    assert math_rule.result == "NEEDS_REVIEW"


def test_outcome_hierarchy_failed_outranks_needs_review():
    """
    Verify D6 hierarchy:
    A definite failure (e.g. percentage < minimum) outranks unknowns (e.g. missing math or unknown degree).
    """
    rules_mca = get_canonical_rule("mca")
    app = {"applicationId": "APP-001"}

    # Percentage = 40% (FAILED) AND Mathematics missing (NEEDS_REVIEW)
    docs = build_test_documents(percentage=40.0, degree_name="BCA", math_ug=False, math_12th=False)
    res = evaluate_eligibility(rules_mca, app, docs)

    # Must be INELIGIBLE because FAILED outranks NEEDS_REVIEW
    assert res.status == "INELIGIBLE"
    assert "Ineligible" in res.summary


def test_evidence_hierarchy_ignores_declared_form_values_alone():
    """
    Verify D2 evidence hierarchy:
    Decisions must be based solely on extracted values from VALIDATED documents.
    Declared form values are never sufficient to pass.
    """
    rules_mca = get_canonical_rule("mca")
    # Declared percentage is 88%, but verified marksheet has 42%
    app = {
        "applicationId": "APP-001",
        "declaredPercentage": 88.0,
        "ugDegree": "BCA",
    }
    docs = build_test_documents(percentage=42.0, degree_name="BCA")
    res = evaluate_eligibility(rules_mca, app, docs)
    assert res.status == "INELIGIBLE"


def test_document_completeness_failure_leads_to_ineligible():
    """Missing or unvalidated documents fail the DOCUMENT_COMPLETENESS rule."""
    rules_mca = get_canonical_rule("mca")
    app = {"applicationId": "APP-001"}

    # 1. One document unvalidated
    docs_unvalidated = build_test_documents(all_validated=False)
    res_unval = evaluate_eligibility(rules_mca, app, docs_unvalidated)
    assert res_unval.status == "INELIGIBLE"
    doc_rule = next(r for r in res_unval.rules if r.ruleId == "DOCUMENT_COMPLETENESS")
    assert doc_rule.result == "FAILED"

    # 2. Missing degree certificate completely
    docs_missing = [d for d in build_test_documents() if d["documentType"] != "DEGREE_CERTIFICATE"]
    res_missing = evaluate_eligibility(rules_mca, app, docs_missing)
    assert res_missing.status == "INELIGIBLE"


def test_degree_level_mismatch_and_fallback_to_ug_marksheet():
    """Verify degree level mismatch and falling back to UG_MARKSHEET when DEGREE_CERTIFICATE course is absent."""
    rules_masters = get_canonical_rule("mca")
    rules_masters["degreeLevel"] = "MASTERS"  # Simulate a program requiring Masters
    app = {"applicationId": "APP-001"}

    docs = build_test_documents(degree_name="B.Tech")
    res = evaluate_eligibility(rules_masters, app, docs)
    assert res.status == "INELIGIBLE"
    qual_rule = next(r for r in res.rules if r.ruleId == "MIN_QUALIFICATION")
    assert qual_rule.result == "FAILED"
    assert "does not meet required 'MASTERS'" in qual_rule.reason

    # Fallback to UG_MARKSHEET when DEGREE_CERTIFICATE has no course
    docs_fallback = build_test_documents(percentage=70.0)
    # Remove course from DEGREE_CERTIFICATE
    for d in docs_fallback:
        if d["documentType"] == "DEGREE_CERTIFICATE":
            d["extractedFields"] = {}
        elif d["documentType"] == "UG_MARKSHEET":
            d["extractedFields"]["course"] = {"normalizedValue": "B.Tech"}

    rules_mca = get_canonical_rule("mca")
    res_fallback = evaluate_eligibility(rules_mca, app, docs_fallback)
    assert res_fallback.status == "ELIGIBLE"


def test_field_extraction_variants_and_ocr_text_math_fallback():
    """Verify get_doc_fields extraction variants (fields, processingResult, extracted_data) and OCR text scanning for math."""
    rules_mca = get_canonical_rule("mca")
    app = {"applicationId": "APP-001"}

    # Use processingResult and rawText / ocrText
    docs = []
    types = [
        "10TH_MARKSHEET",
        "12TH_MARKSHEET",
        "UG_MARKSHEET",
        "DEGREE_CERTIFICATE",
        "TRANSFER_CERTIFICATE",
        "GOVERNMENT_ID",
    ]
    for dtype in types:
        doc = {
            "documentId": f"doc_{dtype.lower()}",
            "documentType": dtype,
            "validationStatus": "VALIDATED",
        }
        if dtype == "UG_MARKSHEET":
            doc["processingResult"] = {
                "fields": {
                    "percentage": {"normalizedValue": 68.5},
                    "course": {"rawValue": "BCA"},
                }
            }
            # Test boolean mathematics field
            doc["processingResult"]["fields"]["mathematics"] = True
        elif dtype == "DEGREE_CERTIFICATE":
            doc["extracted_data"] = {
                "fields": {
                    "course": {"rawValue": "Bachelor of Computer Applications"},
                }
            }
        elif dtype == "12TH_MARKSHEET":
            # Test regex text fallback for mathematics
            doc["ocrText"] = "Subject 1: English 80\nSubject 2: Mathematics 95/100\nSubject 3: Physics 88"
        docs.append(doc)

    res = evaluate_eligibility(rules_mca, app, docs)
    assert res.status == "ELIGIBLE"
    math_rule = next(r for r in res.rules if r.ruleId == "MATHEMATICS_REQUIREMENT")
    assert math_rule.result == "PASSED"


def test_cgpa_calculation_edge_cases_and_invalid_data():
    """Verify CGPA edge cases: invalid non-numeric string, computed percentage > 100, and corrupt rule config."""
    rules_corrupt = get_canonical_rule("mca")
    rules_corrupt["minPercentage"] = "corrupt_min_pct"
    rules_corrupt["cgpaToPercentageFactor"] = "corrupt_factor"
    app = {"applicationId": "APP-001"}

    # Even with corrupt rule strings, falls back safely to 50.0% and 9.5
    docs = build_test_documents(percentage=55.0)
    res = evaluate_eligibility(rules_corrupt, app, docs)
    assert res.status == "ELIGIBLE"

    # Non-numeric CGPA string
    docs_bad_cgpa = build_test_documents(percentage=None, cgpa="bad_cgpa_string")
    res_bad = evaluate_eligibility(rules_corrupt, app, docs_bad_cgpa)
    assert res_bad.status == "INELIGIBLE"
    pct_rule = next(r for r in res_bad.rules if r.ruleId == "MIN_PERCENTAGE")
    assert pct_rule.result == "FAILED"

    # CGPA resulting in > 100 computed percentage
    rules_high_factor = get_canonical_rule("mca")
    rules_high_factor["cgpaToPercentageFactor"] = 20.0
    docs_high_cgpa = build_test_documents(percentage=None, cgpa=8.0)
    res_high = evaluate_eligibility(rules_high_factor, app, docs_high_cgpa)
    assert res_high.status == "INELIGIBLE"
    pct_rule_high = next(r for r in res_high.rules if r.ruleId == "MIN_PERCENTAGE")
    assert pct_rule_high.result == "FAILED"
    assert "outside valid 0 to 100 range" in pct_rule_high.reason


def test_clean_for_hashing_and_entrance_required():
    """Verify clean_for_hashing ignores volatile keys and entranceRequired=True yields NEEDS_REVIEW."""
    from app.services.eligibility.engine import clean_for_hashing

    dirty = {
        "_id": "507f1f77bcf86cd799439011",
        "updatedAt": "2026-10-31T00:00:00Z",
        "activeRunId": "run_123",
        "eligibilityResult": {"status": "ELIGIBLE"},
        "customObject": Decimal("10.5"),
        "nested": [{"a": 1, "_id": "skip_me"}],
    }
    cleaned = clean_for_hashing(dirty)
    assert "_id" not in cleaned
    assert "updatedAt" not in cleaned
    assert "activeRunId" not in cleaned
    assert "eligibilityResult" not in cleaned
    assert cleaned["customObject"] == "10.5"
    assert "_id" not in cleaned["nested"][0]

    # Test entranceRequired: True
    rules_entrance = get_canonical_rule("mca")
    rules_entrance["entranceRequired"] = True
    app = {"applicationId": "APP-001"}
    docs = build_test_documents()
    res_entrance = evaluate_eligibility(rules_entrance, app, docs)
    assert res_entrance.status == "NEEDS_REVIEW"
    entrance_rule = next(r for r in res_entrance.rules if r.ruleId == "ENTRANCE_EXAM")
    assert entrance_rule.result == "NEEDS_REVIEW"

