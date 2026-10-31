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
    cgpa_scale: float | str | None = 10.0,
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
                if cgpa_scale is not None:
                    doc["extractedFields"]["cgpaScale"] = {"normalizedValue": cgpa_scale}
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


def test_shuffled_documents_yield_identical_result_object():
    """
    Verify that document selection and evidence sorting guarantee order-invariance.
    Passing documents in different orders must yield identical result objects and inputHash.
    """
    import random

    rules = get_canonical_rule("mca")
    app = {"applicationId": "APP-2026-001", "programmeId": "mca"}
    docs = build_test_documents(percentage=72.5, degree_name="BCA")

    base_res = evaluate_eligibility(rules, app, docs)

    # Test with multiple shuffled permutations and with multiple documents of same type
    for seed in range(10):
        shuffled_docs = copy.deepcopy(docs)
        random.seed(seed)
        random.shuffle(shuffled_docs)

        shuffled_res = evaluate_eligibility(rules, app, shuffled_docs)

        assert shuffled_res.status == base_res.status
        assert shuffled_res.inputHash == base_res.inputHash
        assert shuffled_res.model_dump() == base_res.model_dump()


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
    """
    Verify out-of-range, negative, or non-numeric percentages and CGPAs give NEEDS_REVIEW, never FAILED.
    FAILED is allowed only for a valid value below the threshold.
    Convert CGPA only for scale 10; unknown or other scales give NEEDS_REVIEW.
    Tests specifically cover: 3.5/4.0, 150, -1, 10.01, "abc".
    """
    rules = get_canonical_rule("mca")
    app = {"applicationId": "APP-001"}

    # 1. Percentage tests:
    # 150 (out of range >100) -> NEEDS_REVIEW
    res_150 = evaluate_eligibility(rules, app, build_test_documents(percentage=150, degree_name="BCA"))
    assert res_150.status == "NEEDS_REVIEW"
    pct_rule_150 = next(r for r in res_150.rules if r.ruleId == "MIN_PERCENTAGE")
    assert pct_rule_150.result == "NEEDS_REVIEW"

    # -1 (negative <0) -> NEEDS_REVIEW
    res_neg1 = evaluate_eligibility(rules, app, build_test_documents(percentage=-1, degree_name="BCA"))
    assert res_neg1.status == "NEEDS_REVIEW"
    pct_rule_neg1 = next(r for r in res_neg1.rules if r.ruleId == "MIN_PERCENTAGE")
    assert pct_rule_neg1.result == "NEEDS_REVIEW"

    # "abc" (non-numeric) -> NEEDS_REVIEW
    res_abc = evaluate_eligibility(rules, app, build_test_documents(percentage="abc", degree_name="BCA"))
    assert res_abc.status == "NEEDS_REVIEW"
    pct_rule_abc = next(r for r in res_abc.rules if r.ruleId == "MIN_PERCENTAGE")
    assert pct_rule_abc.result == "NEEDS_REVIEW"

    # 2. CGPA tests:
    # 3.5/4.0 (scale 4.0 - other scale) -> NEEDS_REVIEW
    res_scale4 = evaluate_eligibility(rules, app, build_test_documents(percentage=None, cgpa=3.5, cgpa_scale=4.0, degree_name="BCA"))
    assert res_scale4.status == "NEEDS_REVIEW"
    pct_rule_scale4 = next(r for r in res_scale4.rules if r.ruleId == "MIN_PERCENTAGE")
    assert pct_rule_scale4.result == "NEEDS_REVIEW"
    assert "not standard scale 10" in pct_rule_scale4.reason

    # Composite string "3.5/4.0" directly in cgpa field -> NEEDS_REVIEW
    res_comp_scale4 = evaluate_eligibility(rules, app, build_test_documents(percentage=None, cgpa="3.5/4.0", cgpa_scale=None, degree_name="BCA"))
    assert res_comp_scale4.status == "NEEDS_REVIEW"
    pct_rule_comp = next(r for r in res_comp_scale4.rules if r.ruleId == "MIN_PERCENTAGE")
    assert pct_rule_comp.result == "NEEDS_REVIEW"

    # 10.01 (out of range >10 on scale 10) -> NEEDS_REVIEW
    res_1001 = evaluate_eligibility(rules, app, build_test_documents(percentage=None, cgpa=10.01, cgpa_scale=10.0, degree_name="BCA"))
    assert res_1001.status == "NEEDS_REVIEW"
    pct_rule_1001 = next(r for r in res_1001.rules if r.ruleId == "MIN_PERCENTAGE")
    assert pct_rule_1001.result == "NEEDS_REVIEW"
    assert "outside valid 0 to 10 scale" in pct_rule_1001.reason

    # -1 on CGPA -> NEEDS_REVIEW
    res_cgpa_neg1 = evaluate_eligibility(rules, app, build_test_documents(percentage=None, cgpa=-1, cgpa_scale=10.0, degree_name="BCA"))
    assert res_cgpa_neg1.status == "NEEDS_REVIEW"
    pct_rule_cgpa_neg1 = next(r for r in res_cgpa_neg1.rules if r.ruleId == "MIN_PERCENTAGE")
    assert pct_rule_cgpa_neg1.result == "NEEDS_REVIEW"

    # "abc" on CGPA -> NEEDS_REVIEW
    res_cgpa_abc = evaluate_eligibility(rules, app, build_test_documents(percentage=None, cgpa="abc", cgpa_scale=10.0, degree_name="BCA"))
    assert res_cgpa_abc.status == "NEEDS_REVIEW"
    pct_rule_cgpa_abc = next(r for r in res_cgpa_abc.rules if r.ruleId == "MIN_PERCENTAGE")
    assert pct_rule_cgpa_abc.result == "NEEDS_REVIEW"

    # Missing scale with CGPA <= 7 (cannot infer scale 10) -> NEEDS_REVIEW
    res_cgpa_unknown = evaluate_eligibility(rules, app, build_test_documents(percentage=None, cgpa=3.5, cgpa_scale=None, degree_name="BCA"))
    assert res_cgpa_unknown.status == "NEEDS_REVIEW"
    pct_rule_unknown = next(r for r in res_cgpa_unknown.rules if r.ruleId == "MIN_PERCENTAGE")
    assert pct_rule_unknown.result == "NEEDS_REVIEW"
    assert "cannot infer 10-point scale" in pct_rule_unknown.reason

    # Missing scale with 7 < CGPA <= 10 (infers scale 10) -> ELIGIBLE
    res_cgpa_inferred = evaluate_eligibility(rules, app, build_test_documents(percentage=None, cgpa=8.5, cgpa_scale=None, degree_name="BCA"))
    assert res_cgpa_inferred.status == "ELIGIBLE"

    # 3. FAILED is allowed ONLY for valid value below threshold:
    # Valid percentage 45% (< 50%) -> FAILED
    res_fail_pct = evaluate_eligibility(rules, app, build_test_documents(percentage=45.0, degree_name="BCA"))
    assert res_fail_pct.status == "INELIGIBLE"
    pct_rule_fail = next(r for r in res_fail_pct.rules if r.ruleId == "MIN_PERCENTAGE")
    assert pct_rule_fail.result == "FAILED"

    # Valid scale-10 CGPA 4.4 (4.4 * 9.5 = 41.8% < 50%) -> FAILED
    res_fail_cgpa = evaluate_eligibility(rules, app, build_test_documents(percentage=None, cgpa=4.4, cgpa_scale=10.0, degree_name="BCA"))
    assert res_fail_cgpa.status == "INELIGIBLE"
    pct_rule_fail_cgpa = next(r for r in res_fail_cgpa.rules if r.ruleId == "MIN_PERCENTAGE")
    assert pct_rule_fail_cgpa.result == "FAILED"


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


def test_normalize_degree_leading_token_and_true_positives_table():
    """
    Verify normalize_degree matches whole string or leading token only.
    Bare-word substring matches anywhere in the string are rejected.
    """
    # 1. Negative test explicitly specified: "Bachelor of Arts to be conferred"
    # must NOT resolve to Engineering (via 'be'); it must resolve to ARTS.
    res_ba = normalize_degree("Bachelor of Arts to be conferred")
    assert res_ba is not None
    assert res_ba[1] == "ARTS"
    assert res_ba[0] == "Bachelor of Arts"
    assert res_ba[1] != "ENGINEERING_TECHNOLOGY"

    # String with 'be' in the middle but not leading degree
    assert normalize_degree("Certificate to be issued upon request") is None
    assert normalize_degree("Doctor of Philosophy to be conferred") is None

    # 2. Comprehensive table of true positives
    true_positives = [
        ("BE", "Bachelor of Engineering", "ENGINEERING_TECHNOLOGY"),
        ("B.E.", "Bachelor of Engineering", "ENGINEERING_TECHNOLOGY"),
        ("B.E. Computer Science and Engineering", "Bachelor of Engineering", "ENGINEERING_TECHNOLOGY"),
        ("BTech", "Bachelor of Technology", "ENGINEERING_TECHNOLOGY"),
        ("B.Tech", "Bachelor of Technology", "ENGINEERING_TECHNOLOGY"),
        ("B.Tech in Information Technology", "Bachelor of Technology", "ENGINEERING_TECHNOLOGY"),
        ("Bachelor of Technology (Honours)", "Bachelor of Technology", "ENGINEERING_TECHNOLOGY"),
        ("Bachelor of Engineering in Mechanical", "Bachelor of Engineering", "ENGINEERING_TECHNOLOGY"),
        ("BCA", "Bachelor of Computer Applications", "COMPUTER_APPLICATIONS"),
        ("B.C.A.", "Bachelor of Computer Applications", "COMPUTER_APPLICATIONS"),
        ("Bachelor of Computer Applications with Data Science", "Bachelor of Computer Applications", "COMPUTER_APPLICATIONS"),
        ("BSc", "Bachelor of Science", "SCIENCE"),
        ("B.Sc.", "Bachelor of Science", "SCIENCE"),
        ("BSc CS", "Bachelor of Science in Computer Science", "SCIENCE"),
        ("B.Sc. Computer Science", "Bachelor of Science in Computer Science", "SCIENCE"),
        ("BSc IT", "Bachelor of Science in Information Technology", "SCIENCE"),
        ("B.Com", "Bachelor of Commerce", "COMMERCE"),
        ("Bachelor of Commerce (Finance)", "Bachelor of Commerce", "COMMERCE"),
        ("BBA", "Bachelor of Business Administration", "MANAGEMENT"),
        ("B.B.A.", "Bachelor of Business Administration", "MANAGEMENT"),
        ("Bachelor of Business Administration in Marketing", "Bachelor of Business Administration", "MANAGEMENT"),
        ("BA", "Bachelor of Arts", "ARTS"),
        ("B.A. English Literature", "Bachelor of Arts", "ARTS"),
        ("Bachelor of Arts", "Bachelor of Arts", "ARTS"),
        ("BArch", "Bachelor of Architecture", "ARCHITECTURE"),
        ("B.Pharm", "Bachelor of Pharmacy", "PHARMACY"),
        ("LLB", "Bachelor of Laws", "LAW"),
        ("MBBS", "Bachelor of Medicine, Bachelor of Surgery", "MEDICINE"),
    ]

    for raw_input, expected_name, expected_family in true_positives:
        norm = normalize_degree(raw_input)
        assert norm is not None, f"Failed to normalize true positive: '{raw_input}'"
        assert norm[0] == expected_name, f"Expected {expected_name} for '{raw_input}', got {norm[0]}"
        assert norm[1] == expected_family, f"Expected family {expected_family} for '{raw_input}', got {norm[1]}"


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

    # Math with zero mark (e.g. 0/100) -> requires mark > 0, gives NEEDS_REVIEW
    docs_zero_math = build_test_documents(percentage=65.0, degree_name="BCA", math_ug=False, math_12th=False)
    for d in docs_zero_math:
        if d["documentType"] == "12TH_MARKSHEET":
            d["extractedFields"]["mathematics"] = {
                "normalizedValue": True,
                "rawValue": "0",
                "matchedLine": "Mathematics: 0 / 100",
            }
    res_zero = evaluate_eligibility(rules_mca, app, docs_zero_math)
    assert res_zero.status == "NEEDS_REVIEW"
    math_rule_zero = next(r for r in res_zero.rules if r.ruleId == "MATHEMATICS_REQUIREMENT")
    assert math_rule_zero.result == "NEEDS_REVIEW"

    # Math with explicit "FAIL" or "ABSENT" marker -> gives NEEDS_REVIEW
    docs_fail_math = build_test_documents(percentage=65.0, degree_name="BCA", math_ug=False, math_12th=False)
    for d in docs_fail_math:
        if d["documentType"] == "12TH_MARKSHEET":
            d["extractedFields"]["mathematics"] = {
                "normalizedValue": True,
                "rawValue": "35",
                "matchedLine": "Mathematics 35 FAIL",
            }
    res_fail = evaluate_eligibility(rules_mca, app, docs_fail_math)
    assert res_fail.status == "NEEDS_REVIEW"
    math_rule_fail = next(r for r in res_fail.rules if r.ruleId == "MATHEMATICS_REQUIREMENT")
    assert math_rule_fail.result == "NEEDS_REVIEW"

    docs_abs_math = build_test_documents(percentage=65.0, degree_name="BCA", math_ug=False, math_12th=False)
    for d in docs_abs_math:
        if d["documentType"] == "12TH_MARKSHEET":
            d["extractedFields"]["mathematics"] = {
                "normalizedValue": True,
                "rawValue": "0",
                "matchedLine": "Mathematics ABSENT",
            }
    res_abs = evaluate_eligibility(rules_mca, app, docs_abs_math)
    assert res_abs.status == "NEEDS_REVIEW"
    math_rule_abs = next(r for r in res_abs.rules if r.ruleId == "MATHEMATICS_REQUIREMENT")
    assert math_rule_abs.result == "NEEDS_REVIEW"


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


def test_document_completeness_incomplete_leads_to_needs_review():
    """
    Missing, unvalidated, or mismatched required documents give NEEDS_REVIEW (incomplete), not FAILED.
    Explicitly tests zero documents and one unvalidated document.
    """
    rules_mca = get_canonical_rule("mca")
    app = {"applicationId": "APP-001"}

    # 1. Zero documents provided
    res_zero = evaluate_eligibility(rules_mca, app, [])
    assert res_zero.status == "NEEDS_REVIEW"
    doc_rule_zero = next(r for r in res_zero.rules if r.ruleId == "DOCUMENT_COMPLETENESS")
    assert doc_rule_zero.result == "NEEDS_REVIEW"
    assert "Missing or unvalidated" in doc_rule_zero.reason

    # 2. One unvalidated document (5 validated, 1 with validationStatus="MANUAL_REVIEW")
    docs_all = build_test_documents(all_validated=True)
    docs_one_unval = [copy.deepcopy(d) for d in docs_all]
    docs_one_unval[0]["validationStatus"] = "MANUAL_REVIEW"
    res_one_unval = evaluate_eligibility(rules_mca, app, docs_one_unval)
    assert res_one_unval.status == "NEEDS_REVIEW"
    doc_rule_unval = next(r for r in res_one_unval.rules if r.ruleId == "DOCUMENT_COMPLETENESS")
    assert doc_rule_unval.result == "NEEDS_REVIEW"
    assert "Missing or unvalidated 1 required document" in doc_rule_unval.reason

    # 3. Missing degree certificate completely
    docs_missing = [d for d in build_test_documents() if d["documentType"] != "DEGREE_CERTIFICATE"]
    res_missing = evaluate_eligibility(rules_mca, app, docs_missing)
    assert res_missing.status == "NEEDS_REVIEW"
    doc_rule_missing = next(r for r in res_missing.rules if r.ruleId == "DOCUMENT_COMPLETENESS")
    assert doc_rule_missing.result == "NEEDS_REVIEW"


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

    # Non-numeric CGPA string gives NEEDS_REVIEW (never FAILED)
    docs_bad_cgpa = build_test_documents(percentage=None, cgpa="bad_cgpa_string")
    res_bad = evaluate_eligibility(rules_corrupt, app, docs_bad_cgpa)
    assert res_bad.status == "NEEDS_REVIEW"
    pct_rule = next(r for r in res_bad.rules if r.ruleId == "MIN_PERCENTAGE")
    assert pct_rule.result == "NEEDS_REVIEW"

    # CGPA resulting in > 100 computed percentage gives NEEDS_REVIEW (out of range, never FAILED)
    rules_high_factor = get_canonical_rule("mca")
    rules_high_factor["cgpaToPercentageFactor"] = 20.0
    docs_high_cgpa = build_test_documents(percentage=None, cgpa=8.0)
    res_high = evaluate_eligibility(rules_high_factor, app, docs_high_cgpa)
    assert res_high.status == "NEEDS_REVIEW"
    pct_rule_high = next(r for r in res_high.rules if r.ruleId == "MIN_PERCENTAGE")
    assert pct_rule_high.result == "NEEDS_REVIEW"
    assert "outside valid 0 to 100 range" in pct_rule_high.reason


def test_deterministic_cgpa_scale_inference_and_cases():
    """
    Increment 16 Final Hardening (Issue 1):
    Verify deterministic CGPA scale inference across all required cases:
    1. CGPA: 8.5 with no printed scale -> inferred scale 10 -> ELIGIBLE (meets 50%).
    2. CGPA: 3.5 with no printed scale -> <= 7 with no scale -> NEEDS_REVIEW.
    3. CGPA: 3.5 / 4.0 -> explicit non-10 scale -> NEEDS_REVIEW.
    4. CGPA: 8.5 / 10 -> explicit scale 10 -> ELIGIBLE.
    5. CGPA: -1 -> out of range -> NEEDS_REVIEW (never FAILED).
    6. CGPA: 10.01 -> out of range -> NEEDS_REVIEW (never FAILED).
    7. Non-numeric CGPA values -> NEEDS_REVIEW (never FAILED).
    8. Missing CGPA evidence -> NEEDS_REVIEW (never FAILED).
    """
    rules = get_canonical_rule("mca")
    app = {"applicationId": "APP-CGPA-INFER"}

    # 1. CGPA: 8.5 with no printed scale (7 < CGPA <= 10 -> infer scale 10)
    docs_8_5_no_scale = build_test_documents(percentage=None, cgpa=8.5, cgpa_scale=None)
    res_1 = evaluate_eligibility(rules, app, docs_8_5_no_scale)
    assert res_1.status == "ELIGIBLE"
    r1 = next(r for r in res_1.rules if r.ruleId == "MIN_PERCENTAGE")
    assert r1.result == "PASSED"
    assert r1.observed["cgpaScaleInferred"] is True
    assert r1.observed["cgpaScale"] == "10"
    assert "inferred scale 10" in r1.reason
    assert any(ev.metadata and ev.metadata.get("cgpaScaleInferred") is True for ev in r1.evidence)

    # 2. CGPA: 3.5 with no printed scale (CGPA <= 7 with no printed scale -> NEEDS_REVIEW)
    docs_3_5_no_scale = build_test_documents(percentage=None, cgpa=3.5, cgpa_scale=None)
    res_2 = evaluate_eligibility(rules, app, docs_3_5_no_scale)
    assert res_2.status == "NEEDS_REVIEW"
    r2 = next(r for r in res_2.rules if r.ruleId == "MIN_PERCENTAGE")
    assert r2.result == "NEEDS_REVIEW"
    assert "cannot infer 10-point scale" in r2.reason

    # 3. CGPA: 3.5 / 4.0 (explicit non-10 scale -> NEEDS_REVIEW)
    docs_3_5_scale_4 = build_test_documents(percentage=None, cgpa="3.5/4.0", cgpa_scale=None)
    res_3 = evaluate_eligibility(rules, app, docs_3_5_scale_4)
    assert res_3.status == "NEEDS_REVIEW"
    r3 = next(r for r in res_3.rules if r.ruleId == "MIN_PERCENTAGE")
    assert r3.result == "NEEDS_REVIEW"
    assert "not standard scale 10" in r3.reason

    # Also test explicit scale passed via cgpa_scale
    docs_3_5_scale_4b = build_test_documents(percentage=None, cgpa=3.5, cgpa_scale=4.0)
    res_3b = evaluate_eligibility(rules, app, docs_3_5_scale_4b)
    assert res_3b.status == "NEEDS_REVIEW"

    # 4. CGPA: 8.5 / 10 (explicit scale 10 -> PASSED / ELIGIBLE)
    docs_8_5_scale_10 = build_test_documents(percentage=None, cgpa=8.5, cgpa_scale=10.0)
    res_4 = evaluate_eligibility(rules, app, docs_8_5_scale_10)
    assert res_4.status == "ELIGIBLE"
    r4 = next(r for r in res_4.rules if r.ruleId == "MIN_PERCENTAGE")
    assert r4.result == "PASSED"
    assert r4.observed["cgpaScaleInferred"] is False
    assert r4.observed["cgpaScale"] == "10"

    docs_8_5_scale_10_str = build_test_documents(percentage=None, cgpa="8.5/10", cgpa_scale=None)
    res_4b = evaluate_eligibility(rules, app, docs_8_5_scale_10_str)
    assert res_4b.status == "ELIGIBLE"

    # 5. CGPA: -1 (negative value -> NEEDS_REVIEW, never FAILED)
    docs_neg = build_test_documents(percentage=None, cgpa=-1.0, cgpa_scale=None)
    res_5 = evaluate_eligibility(rules, app, docs_neg)
    assert res_5.status == "NEEDS_REVIEW"
    r5 = next(r for r in res_5.rules if r.ruleId == "MIN_PERCENTAGE")
    assert r5.result == "NEEDS_REVIEW"
    assert "outside valid 0 to 10 scale" in r5.reason

    # 6. CGPA: 10.01 (greater than 10 -> NEEDS_REVIEW, never FAILED)
    docs_high = build_test_documents(percentage=None, cgpa=10.01, cgpa_scale=None)
    res_6 = evaluate_eligibility(rules, app, docs_high)
    assert res_6.status == "NEEDS_REVIEW"
    r6 = next(r for r in res_6.rules if r.ruleId == "MIN_PERCENTAGE")
    assert r6.result == "NEEDS_REVIEW"
    assert "outside valid 0 to 10 scale" in r6.reason

    # 7. Non-numeric CGPA values ("abc" -> NEEDS_REVIEW, never FAILED)
    docs_non_num = build_test_documents(percentage=None, cgpa="abc", cgpa_scale=None)
    res_7 = evaluate_eligibility(rules, app, docs_non_num)
    assert res_7.status == "NEEDS_REVIEW"
    r7 = next(r for r in res_7.rules if r.ruleId == "MIN_PERCENTAGE")
    assert r7.result == "NEEDS_REVIEW"
    assert "not a valid decimal number" in r7.reason

    # 8. Missing CGPA evidence (percentage=None, cgpa=None -> NEEDS_REVIEW, never FAILED)
    docs_missing = build_test_documents(percentage=None, cgpa=None, cgpa_scale=None)
    res_8 = evaluate_eligibility(rules, app, docs_missing)
    assert res_8.status == "NEEDS_REVIEW"
    r8 = next(r for r in res_8.rules if r.ruleId == "MIN_PERCENTAGE")
    assert r8.result == "NEEDS_REVIEW"
    assert "Neither aggregate percentage nor CGPA was found" in r8.reason


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

