import re
from typing import Tuple


CONFIDENCE_THRESHOLD = 0.80
PERCENTAGE_TOLERANCE = 0.5
CGPA_TOLERANCE = 0.05

BOARD_ALIASES: dict[str, set[str]] = {
    "cbse": {
        "cbse",
        "central board of secondary education",
        "central board of secondary education new delhi",
        "central board",
    },
    "icse": {
        "icse",
        "isc",
        "indian certificate of secondary education",
        "cisce",
        "council for the indian school certificate examinations",
    },
    "tamil_nadu_state_board": {
        "tamil nadu state board",
        "tamil nadu state board of school examinations",
        "tamil nadu board of higher secondary education",
        "tamil nadu state board of secondary education",
        "state board of school examinations tamil nadu",
        "tamil nadu matriculation",
    },
    "karnataka_state_board": {
        "karnataka state board",
        "karnataka secondary education examination board",
        "kseeb",
        "department of pre university education karnataka",
    },
    "maharashtra_state_board": {
        "maharashtra state board",
        "maharashtra state board of secondary and higher secondary education",
        "msbshse",
    },
    "andhra_pradesh_state_board": {
        "andhra pradesh state board",
        "board of secondary education andhra pradesh",
        "bseap",
        "board of intermediate education andhra pradesh",
    },
    "kerala_state_board": {
        "kerala state board",
        "board of higher secondary education kerala",
        "dhse kerala",
    },
}

STATE_REGIONS = [
    "tamil nadu",
    "karnataka",
    "maharashtra",
    "andhra pradesh",
    "kerala",
    "telangana",
    "uttar pradesh",
    "madhya pradesh",
    "west bengal",
    "gujarat",
    "rajasthan",
    "bihar",
    "punjab",
    "haryana",
    "delhi",
]

# Degree Qualification Categories
DEGREE_CATEGORIES: dict[str, set[str]] = {
    "bca": {"bca", "b.c.a", "b.c.a.", "bachelor of computer applications", "bachelor in computer applications"},
    "mca": {"mca", "m.c.a", "m.c.a.", "master of computer applications", "master in computer applications"},
    "btech_be": {
        "btech", "b.tech", "b.tech.", "bachelor of technology",
        "be", "b.e", "b.e.", "bachelor of engineering"
    },
    "mtech_me": {
        "mtech", "m.tech", "m.tech.", "master of technology",
        "me", "m.e", "m.e.", "master of engineering"
    },
    "bsc": {"bsc", "b.sc", "b.sc.", "bachelor of science"},
    "msc": {"msc", "m.sc", "m.sc.", "master of science"},
    "bcom": {"bcom", "b.com", "b.com.", "bachelor of commerce"},
    "mcom": {"mcom", "m.com", "m.com.", "master of commerce"},
    "bba": {"bba", "b.b.a", "b.b.a.", "bachelor of business administration"},
    "mba": {"mba", "m.b.a", "m.b.a.", "master of business administration"},
    "ba": {"ba", "b.a", "b.a.", "bachelor of arts"},
    "ma": {"ma", "m.a", "m.a.", "master of arts"},
}


def parse_float_safe(val: str | float | int | None) -> float | None:
    """Extract float value from string or numeric type safely."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    cleaned = str(val).strip().rstrip("%").strip()
    if "/" in cleaned:
        cleaned = cleaned.split("/")[0].strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_int_safe(val: str | int | None) -> int | None:
    """Extract integer value safely."""
    if val is None:
        return None
    if isinstance(val, int):
        return val
    cleaned = str(val).strip()
    try:
        return int(cleaned)
    except ValueError:
        return None


def normalize_text_token_set(text: str) -> set[str]:
    """Normalize text by stripping harmless punctuation, lowercasing, and tokenizing."""
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    return set(cleaned.split())


def compare_percentages(
    extracted_pct: float | None,
    marks_obtained: float | None,
    max_marks: float | None,
    canonical_pct_raw: float | int | str | None,
    confidence: float | None = 1.0,
) -> Tuple[str, str, float | None]:
    """
    Deterministically compare percentage against canonical percentage.
    Accepts direct percentage or calculates (marks_obtained / max_marks) * 100.
    Returns: (status, message, effective_percentage)
    """
    canonical_pct = parse_float_safe(canonical_pct_raw)
    if canonical_pct is None:
        return "MANUAL_REVIEW", "Canonical percentage is missing or invalid in application record.", None

    effective_pct: float | None = None
    if extracted_pct is not None:
        effective_pct = extracted_pct
    elif marks_obtained is not None and max_marks is not None and max_marks > 0:
        effective_pct = round((marks_obtained / max_marks) * 100.0, 2)

    if effective_pct is None:
        return "NOT_EXTRACTED", "No usable percentage or (obtained/max marks) extracted from document.", None

    if effective_pct < 0.0 or effective_pct > 100.0:
        return "MANUAL_REVIEW", f"Extracted percentage value {effective_pct}% is out of valid range (0-100%).", effective_pct

    # Confidence check
    if confidence is None or confidence < CONFIDENCE_THRESHOLD:
        conf_val = confidence if confidence is not None else 0.0
        return (
            "MANUAL_REVIEW",
            f"Extracted percentage ({effective_pct}%) confidence {conf_val:.2f} is below decisive threshold {CONFIDENCE_THRESHOLD}.",
            effective_pct,
        )

    diff = abs(effective_pct - canonical_pct)
    if diff <= PERCENTAGE_TOLERANCE:
        return (
            "MATCH",
            f"Percentage matches canonical record ({effective_pct}% vs {canonical_pct}% within {PERCENTAGE_TOLERANCE}% tolerance).",
            effective_pct,
        )
    else:
        return (
            "MISMATCH",
            f"Percentage mismatch: extracted {effective_pct}%, canonical application record is {canonical_pct}%.",
            effective_pct,
        )


def compare_cgpa(
    extracted_cgpa_raw: float | int | str | None,
    canonical_cgpa_raw: float | int | str | None,
    confidence: float | None = 1.0,
) -> Tuple[str, str, float | None]:
    """
    Compare CGPA using absolute tolerance of 0.05 on standard 10-point scale.
    """
    canonical_cgpa = parse_float_safe(canonical_cgpa_raw)
    if canonical_cgpa is None:
        return "MANUAL_REVIEW", "Canonical CGPA is missing or invalid in application record.", None

    extracted_cgpa = parse_float_safe(extracted_cgpa_raw)
    if extracted_cgpa is None:
        return "NOT_EXTRACTED", "CGPA not extracted from document.", None

    if extracted_cgpa < 0.0 or extracted_cgpa > 10.0:
        return "MANUAL_REVIEW", f"Extracted CGPA {extracted_cgpa} is out of standard 10-point scale (0-10).", extracted_cgpa

    if canonical_cgpa < 0.0 or canonical_cgpa > 10.0:
        return "MANUAL_REVIEW", f"Canonical CGPA {canonical_cgpa} is out of standard 10-point scale (0-10).", extracted_cgpa

    if confidence is None or confidence < CONFIDENCE_THRESHOLD:
        conf_val = confidence if confidence is not None else 0.0
        return (
            "MANUAL_REVIEW",
            f"Extracted CGPA ({extracted_cgpa}) confidence {conf_val:.2f} is below decisive threshold {CONFIDENCE_THRESHOLD}.",
            extracted_cgpa,
        )

    diff = abs(extracted_cgpa - canonical_cgpa)
    if diff <= CGPA_TOLERANCE:
        return (
            "MATCH",
            f"CGPA matches canonical record ({extracted_cgpa} vs {canonical_cgpa} within {CGPA_TOLERANCE} tolerance).",
            extracted_cgpa,
        )
    else:
        return (
            "MISMATCH",
            f"CGPA mismatch: extracted {extracted_cgpa}, canonical application record is {canonical_cgpa}.",
            extracted_cgpa,
        )


def compare_years(
    extracted_year_raw: int | str | None,
    canonical_year_raw: int | str | None,
    confidence: float | None = 1.0,
) -> Tuple[str, str, int | None]:
    """Exact comparison of 4-digit academic passing/graduation years."""
    canonical_year = parse_int_safe(canonical_year_raw)
    if canonical_year is None:
        return "MANUAL_REVIEW", "Canonical graduation year missing in application record.", None

    extracted_year = parse_int_safe(extracted_year_raw)
    if extracted_year is None:
        return "NOT_EXTRACTED", "Passing year not extracted from document.", None

    if not (1970 <= extracted_year <= 2035):
        return "MANUAL_REVIEW", f"Extracted year {extracted_year} is out of realistic academic range (1970-2035).", extracted_year

    if confidence is None or confidence < CONFIDENCE_THRESHOLD:
        conf_val = confidence if confidence is not None else 0.0
        return (
            "MANUAL_REVIEW",
            f"Extracted year ({extracted_year}) confidence {conf_val:.2f} is below decisive threshold {CONFIDENCE_THRESHOLD}.",
            extracted_year,
        )

    if extracted_year == canonical_year:
        return "MATCH", f"Passing year ({extracted_year}) matches canonical graduation year ({canonical_year}).", extracted_year
    else:
        return (
            "MISMATCH",
            f"Passing year mismatch: extracted {extracted_year}, canonical graduation year is {canonical_year}.",
            extracted_year,
        )


def get_board_key(norm_text: str) -> str | None:
    """Resolve normalized board text to known specific board alias key."""
    for key, aliases in BOARD_ALIASES.items():
        if norm_text in aliases:
            return key
        if any(alias in norm_text for alias in aliases):
            return key
    return None


def get_state_region(norm_text: str) -> str | None:
    """Identify specific state region mentioned in board text."""
    for region in STATE_REGIONS:
        if region in norm_text:
            return region
    return None


def compare_board(
    extracted_board: str | None,
    canonical_board: str | None,
    confidence: float | None = 1.0,
) -> Tuple[str, str]:
    """
    Compare educational board name conservatively.
    Does not collapse distinct state boards or broad substring overlap.
    """
    if not extracted_board or not extracted_board.strip():
        return "NOT_EXTRACTED", "Board name not extracted from document."
    if not canonical_board or not canonical_board.strip():
        return "MANUAL_REVIEW", "Canonical board name missing in application record."

    if confidence is None or confidence < CONFIDENCE_THRESHOLD:
        conf_val = confidence if confidence is not None else 0.0
        return (
            "MANUAL_REVIEW",
            f"Extracted board ('{extracted_board}') confidence {conf_val:.2f} is below decisive threshold {CONFIDENCE_THRESHOLD}.",
        )

    ext_norm = re.sub(r"[^\w\s]", " ", extracted_board.lower()).strip()
    can_norm = re.sub(r"[^\w\s]", " ", canonical_board.lower()).strip()
    ext_norm = " ".join(ext_norm.split())
    can_norm = " ".join(can_norm.split())

    # 1. Exact normalized match
    if ext_norm == can_norm:
        return "MATCH", f"Board matches canonical record ('{extracted_board}')."

    ext_key = get_board_key(ext_norm)
    can_key = get_board_key(can_norm)

    # 2. Both resolve to same specific board
    if ext_key and can_key and ext_key == can_key:
        return "MATCH", f"Board '{extracted_board}' matches canonical board '{canonical_board}' via recognized board identifier '{ext_key}'."

    # 3. Both resolve to different specific boards -> definitive MISMATCH
    if ext_key and can_key and ext_key != can_key:
        return (
            "MISMATCH",
            f"Board mismatch: extracted board '{extracted_board}' ({ext_key}) conflicts with canonical board '{canonical_board}' ({can_key}).",
        )

    # 4. Check for distinct state regions (e.g. Tamil Nadu vs Maharashtra)
    ext_region = get_state_region(ext_norm)
    can_region = get_state_region(can_norm)
    if ext_region and can_region and ext_region != can_region:
        return (
            "MISMATCH",
            f"Board mismatch: extracted board region '{ext_region}' conflicts with canonical board region '{can_region}'.",
        )

    # 5. Generic 'state board' vs specific state board -> MANUAL_REVIEW
    if ("state board" in ext_norm and can_region) or ("state board" in can_norm and ext_region):
        return (
            "MANUAL_REVIEW",
            f"Generic state board reference cannot establish equivalence with specific regional board ('{extracted_board}' vs '{canonical_board}'). Manual review required.",
        )

    # 6. One of them is CBSE or ICSE and the other is a state board / unknown -> MISMATCH
    if (ext_key in ("cbse", "icse") and can_region) or (can_key in ("cbse", "icse") and ext_region):
        return (
            "MISMATCH",
            f"Board mismatch: national board ('{ext_key or can_key}') conflicts with state board ('{canonical_board if ext_key else extracted_board}').",
        )

    return (
        "MANUAL_REVIEW",
        f"Board equivalence between extracted '{extracted_board}' and canonical '{canonical_board}' requires manual review.",
    )


def get_degree_level(norm_text: str) -> str | None:
    """Identify qualification academic level: 'bachelor', 'master', or 'diploma'."""
    tokens = set(norm_text.split())
    # Acronyms and prefixes
    bachelor_indicators = {"bachelor", "bachelors", "undergraduate", "ug", "bca", "bsc", "btech", "bcom", "bba", "ba", "be"}
    master_indicators = {"master", "masters", "postgraduate", "pg", "mca", "msc", "mtech", "mcom", "mba", "ma", "me"}

    # Also check dotted abbreviations
    if any(t in tokens for t in ["b.sc", "b.sc.", "b.tech", "b.tech.", "b.c.a", "b.c.a.", "b.e", "b.e.", "b.com", "b.com.", "b.a", "b.a."]):
        return "bachelor"
    if any(t in tokens for t in ["m.sc", "m.sc.", "m.tech", "m.tech.", "m.c.a", "m.c.a.", "m.e", "m.e.", "m.com", "m.com.", "m.a", "m.a."]):
        return "master"

    has_bachelor = bool(tokens.intersection(bachelor_indicators))
    has_master = bool(tokens.intersection(master_indicators))

    if has_bachelor and not has_master:
        return "bachelor"
    if has_master and not has_bachelor:
        return "master"
    if "diploma" in tokens or "polytechnic" in tokens:
        return "diploma"

    return None


def get_degree_category(norm_text: str) -> str | None:
    """Identify recognized degree category (e.g. 'bca', 'bsc', 'btech_be')."""
    tokens = norm_text.split()
    for cat_name, aliases in DEGREE_CATEGORIES.items():
        if norm_text in aliases:
            return cat_name
        for a in aliases:
            if a in tokens or a == norm_text:
                return cat_name
    return None


def compare_course(
    extracted_course: str | None,
    canonical_degree: str | None,
    confidence: float | None = 1.0,
) -> Tuple[str, str]:
    """
    Compare academic course / degree name conservatively.
    Never lets shared subject overlap (e.g. 'Computer Science') override conflicting degree types/levels.
    """
    if not extracted_course or not extracted_course.strip():
        return "NOT_EXTRACTED", "Course/degree name not extracted from document."
    if not canonical_degree or not canonical_degree.strip():
        return "MANUAL_REVIEW", "Canonical UG degree missing in application record."

    if confidence is None or confidence < CONFIDENCE_THRESHOLD:
        conf_val = confidence if confidence is not None else 0.0
        return (
            "MANUAL_REVIEW",
            f"Extracted course ('{extracted_course}') confidence {conf_val:.2f} is below decisive threshold {CONFIDENCE_THRESHOLD}.",
        )

    ext_norm = re.sub(r"[^\w\s\.]", " ", extracted_course.lower()).strip()
    can_norm = re.sub(r"[^\w\s\.]", " ", canonical_degree.lower()).strip()
    ext_norm = " ".join(ext_norm.split())
    can_norm = " ".join(can_norm.split())

    # 1. Exact normalized match
    if ext_norm == can_norm:
        return "MATCH", f"Course matches canonical degree ('{extracted_course}')."

    # 2. Check academic degree level conflict (e.g. Bachelor vs Master)
    ext_level = get_degree_level(ext_norm)
    can_level = get_degree_level(can_norm)
    if ext_level and can_level and ext_level != can_level:
        return (
            "MISMATCH",
            f"Degree level mismatch: extracted qualification '{extracted_course}' ({ext_level} level) conflicts with canonical degree '{canonical_degree}' ({can_level} level).",
        )

    # 3. Check degree category
    ext_cat = get_degree_category(ext_norm)
    can_cat = get_degree_category(can_norm)

    if ext_cat and can_cat:
        if ext_cat == can_cat:
            return (
                "MATCH",
                f"Course '{extracted_course}' matches canonical degree '{canonical_degree}' via recognized qualification alias '{ext_cat}'.",
            )
        else:
            return (
                "MISMATCH",
                f"Degree qualification mismatch: extracted course '{extracted_course}' ({ext_cat}) conflicts with canonical degree '{canonical_degree}' ({can_cat}).",
            )

    # 4. Check if one category is known and the other clearly conflicts
    if ext_cat and not can_cat:
        # e.g. Extracted is B.Tech, Canonical is BCA
        return (
            "MANUAL_REVIEW",
            f"Course equivalence between extracted '{extracted_course}' and canonical '{canonical_degree}' requires manual review.",
        )

    return (
        "MANUAL_REVIEW",
        f"Course equivalence between extracted '{extracted_course}' and canonical '{canonical_degree}' requires manual review.",
    )


def compare_institution(
    extracted_inst: str | None,
    canonical_univ: str | None,
    confidence: float | None = 1.0,
) -> Tuple[str, str]:
    """Compare awarding university / institution name."""
    if not extracted_inst or not extracted_inst.strip():
        return "NOT_EXTRACTED", "Institution not extracted from document."
    if not canonical_univ or not canonical_univ.strip():
        return "MANUAL_REVIEW", "Canonical university missing in application record."

    if confidence is None or confidence < CONFIDENCE_THRESHOLD:
        conf_val = confidence if confidence is not None else 0.0
        return (
            "MANUAL_REVIEW",
            f"Extracted institution ('{extracted_inst}') confidence {conf_val:.2f} is below decisive threshold {CONFIDENCE_THRESHOLD}.",
        )

    ext_norm = extracted_inst.strip().lower()
    can_norm = canonical_univ.strip().lower()

    if ext_norm == can_norm:
        return "MATCH", f"Institution matches canonical university ('{extracted_inst}')."

    ext_tokens = normalize_text_token_set(extracted_inst)
    can_tokens = normalize_text_token_set(canonical_univ)
    stopwords = {"university", "college", "institute", "of", "technology", "and", "sciences", "the"}
    ext_core = ext_tokens - stopwords
    can_core = can_tokens - stopwords

    overlap = ext_core.intersection(can_core)
    if overlap and len(overlap) >= min(len(ext_core), len(can_core), 2):
        return "MATCH", f"Institution '{extracted_inst}' matches canonical university '{canonical_univ}' on core keywords ({', '.join(sorted(overlap))})."

    return "MANUAL_REVIEW", f"Institution equivalence between extracted '{extracted_inst}' and canonical '{canonical_univ}' requires manual review."
