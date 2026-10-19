from app.services.verification.engine import validate_document_content
from app.services.verification.name_matcher import compare_names
from app.services.verification.dob_parser import parse_and_compare_dob
from app.services.verification.numeric_comparer import (
    compare_percentages,
    compare_cgpa,
    compare_years,
    compare_board,
    compare_course,
    compare_institution,
)
from app.services.verification.cross_document import run_cross_document_checks
from app.services.verification.synthetic_authoritative import (
    SyntheticAuthoritativeVerificationProvider,
)

__all__ = [
    "validate_document_content",
    "compare_names",
    "parse_and_compare_dob",
    "compare_percentages",
    "compare_cgpa",
    "compare_years",
    "compare_board",
    "compare_course",
    "compare_institution",
    "run_cross_document_checks",
    "SyntheticAuthoritativeVerificationProvider",
]
