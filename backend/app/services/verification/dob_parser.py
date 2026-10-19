from datetime import date, datetime
import re
from typing import Tuple


NUMERIC_SAME_SEP_REGEX = re.compile(r"^\s*(\d{1,2})([./-])(\d{1,2})\2(\d{4})\s*$")

ISO_DATE_REGEX = re.compile(r"^\s*(\d{4})([./-])(\d{1,2})\2(\d{1,2})\s*$")

NAMED_MONTH_PATTERNS = [
    re.compile(r"^\s*(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\s*$"),
    re.compile(r"^\s*(\d{1,2})[./-]([A-Za-z]{3,9})[./-](\d{4})\s*$"),
    re.compile(r"^\s*([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})\s*$"),
    re.compile(r"^\s*([A-Za-z]{3,9})[./-](\d{1,2})[./-](\d{4})\s*$"),
]

MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def parse_canonical_dob(raw_canonical: str | None) -> date | None:
    """Safely parse canonical DOB string (typically YYYY-MM-DD or DD/MM/YYYY) into date object."""
    if not raw_canonical or not raw_canonical.strip():
        return None
    cleaned = raw_canonical.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            dt = datetime.strptime(cleaned, fmt)
            return dt.date()
        except ValueError:
            continue
    return None


def parse_and_compare_dob(
    raw_extracted_value: str | None,
    canonical_dob_str: str | None,
) -> Tuple[str, str, date | None]:
    """
    Deterministically parse raw extracted DOB string and compare with canonical application DOB.
    Returns: (status, reason_message, parsed_extracted_date)
    Status is one of: "MATCH", "MISMATCH", "MANUAL_REVIEW", "NOT_EXTRACTED"
    """
    if not raw_extracted_value or not raw_extracted_value.strip():
        return "NOT_EXTRACTED", "DOB not extracted from document.", None

    canonical_date = parse_canonical_dob(canonical_dob_str)
    if canonical_date is None:
        return "MANUAL_REVIEW", "Canonical DOB in application record is missing or invalid.", None

    raw = raw_extracted_value.strip()

    # 1. ISO format check (YYYY-MM-DD)
    iso_match = ISO_DATE_REGEX.match(raw)
    if iso_match:
        year = int(iso_match.group(1))
        month = int(iso_match.group(3))
        day = int(iso_match.group(4))
        try:
            parsed_date = date(year, month, day)
        except ValueError:
            return "MANUAL_REVIEW", f"Extracted ISO date '{raw}' is an invalid calendar date.", None

        if parsed_date == canonical_date:
            return "MATCH", "Extracted DOB matches canonical application DOB exactly.", parsed_date
        else:
            return (
                "MISMATCH",
                f"Extracted DOB '{parsed_date.isoformat()}' does not match canonical DOB '{canonical_date.isoformat()}'.",
                parsed_date,
            )

    # 2. Named-month patterns (unambiguous day and month)
    for pat in NAMED_MONTH_PATTERNS:
        m = pat.match(raw)
        if m:
            g1, g2, g3 = m.group(1), m.group(2), m.group(3)
            # Determine which is month name and which is day
            if g1.lower() in MONTH_MAP:
                month = MONTH_MAP[g1.lower()]
                day = int(g2)
                year = int(g3)
            elif g2.lower() in MONTH_MAP:
                day = int(g1)
                month = MONTH_MAP[g2.lower()]
                year = int(g3)
            else:
                continue

            try:
                parsed_date = date(year, month, day)
            except ValueError:
                return (
                    "MANUAL_REVIEW",
                    f"Extracted date with month name '{raw}' is an invalid calendar date.",
                    None,
                )

            if parsed_date == canonical_date:
                return "MATCH", "Extracted DOB matches canonical application DOB exactly.", parsed_date
            else:
                return (
                    "MISMATCH",
                    f"Extracted DOB '{parsed_date.isoformat()}' does not match canonical DOB '{canonical_date.isoformat()}'.",
                    parsed_date,
                )

    # 3. Numeric day/month/year with same separator
    num_match = NUMERIC_SAME_SEP_REGEX.match(raw)
    if num_match:
        part1 = int(num_match.group(1))
        part2 = int(num_match.group(3))
        year = int(num_match.group(4))

        # Check for ambiguity: if both part1 <= 12 and part2 <= 12 and part1 != part2
        if 1 <= part1 <= 12 and 1 <= part2 <= 12 and part1 != part2:
            return (
                "MANUAL_REVIEW",
                f"Extracted numeric date '{raw}' is ambiguous between DD/MM and MM/DD. Manual review required.",
                None,
            )

        # Equal day/month (e.g. 05/05/2005) or one part > 12
        # Determine day and month:
        if part1 > 12:
            # part1 is definitely day, part2 is month
            day = part1
            month = part2
        elif part2 > 12:
            # part2 is definitely day, part1 is month
            month = part1
            day = part2
        else:
            # part1 == part2 (e.g. 05/05/2005)
            day = part1
            month = part2

        try:
            parsed_date = date(year, month, day)
        except ValueError:
            return "MANUAL_REVIEW", f"Extracted numeric date '{raw}' is an invalid calendar date.", None

        if parsed_date == canonical_date:
            return "MATCH", "Extracted DOB matches canonical application DOB exactly.", parsed_date
        else:
            return (
                "MISMATCH",
                f"Extracted DOB '{parsed_date.isoformat()}' does not match canonical DOB '{canonical_date.isoformat()}'.",
                parsed_date,
            )

    # 4. If none of the recognized formats matched
    return "MANUAL_REVIEW", f"Extracted DOB '{raw}' has an unrecognized or malformed format.", None
