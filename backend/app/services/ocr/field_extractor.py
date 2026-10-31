from datetime import datetime
import re
from typing import Any
from app.schemas.document_processing import ExtractedField, ExtractedFields

MAX_OCR_TEXT_LENGTH = 100_000


# Regex patterns for key labels
NAME_PATTERNS = [
    re.compile(r"(?:candidate(?:'s)?\s*name|student(?:'s)?\s*name|name\s*of\s*the\s*candidate|name\s*of\s*student|name)\s*[:\-–]\s*([A-Za-z\.\' ]{3,50})", re.I),
    re.compile(r"(?:this\s+is\s+to\s+certify\s+that)\s+([A-Za-z\.\' ]{3,50})\s+(?:son|daughter|has\s+completed|bearing)", re.I),
]

DOB_PATTERNS = [
    re.compile(r"(?:date\s*of\s*birth|d\.?o\.?b\.?|birth\s*date)\s*[:\-–]?\s*([0-3]?\d[\/\-\.][0-1]?\d[\/\-\.]\d{2,4})", re.I),
    re.compile(r"(?:date\s*of\s*birth|d\.?o\.?b\.?)\s*[:\-–]?\s*([0-3]?\d\s+[A-Za-z]{3,9}\s+\d{4})", re.I),
]

REG_NO_PATTERNS = [
    re.compile(r"(?:roll\s*(?:no|number)|registration\s*(?:no|number)|register\s*no|reg\.?\s*no|enrollment\s*(?:no|number)|hall\s*ticket\s*no)\s*[:\-–]?\s*([A-Za-z0-9\/\-]{4,25})", re.I),
]

INSTITUTION_PATTERNS = [
    re.compile(r"(?:institution|college|school|university|board)\s*[:\-–]\s*([A-Za-z0-9\s\,\.\-]{5,80})", re.I),
    re.compile(r"([A-Za-z\s]{4,60}(?:institute of technology|university|college of engineering|higher secondary school|vidyalaya|public school))\b", re.I),
]

COURSE_PATTERNS = [
    re.compile(r"(?:course|degree|examination|programme|qualification)\s*[:\-–]\s*([A-Za-z0-9\s\.\,]{3,60})", re.I),
    re.compile(r"\b(bachelor\s*of\s*[A-Za-z\s]{3,30}|b\.tech|b\.sc|b\.c\.a|bca|mca|b\.com|b\.e|master\s*of\s*[A-Za-z\s]{3,30}|secondary\s*school\s*examination|higher\s*secondary\s*examination)\b", re.I),
]

MARKS_OBTAINED_PATTERNS = [
    re.compile(r"(?:marks\s*obtained|total\s*marks\s*obtained|total\s*secured|marks\s*secured)\s*[:\-–]?\s*(\d{2,4}(?:\.\d{1,2})?)", re.I),
    re.compile(r"(?:total\s*marks)\s*[:\-–]?\s*(\d{2,4})\s*(?:\/|\s*out\s*of\s*)\s*(\d{2,4})", re.I),
]

MAX_MARKS_PATTERNS = [
    re.compile(r"(?:maximum\s*marks|max\.?\s*marks|total\s*maximum|out\s*of)\s*[:\-–]?\s*(\d{2,4})", re.I),
]

PERCENTAGE_PATTERNS = [
    re.compile(r"(?:percentage|aggregate\s*percentage|total\s*percentage|aggregate\s*\%|\%)\s*[:\-–]?\s*(\d{1,2}(?:\.\d{1,2})?)\s*\%?", re.I),
    re.compile(r"\b(\d{1,2}\.\d{1,2})\s*\%", re.I),
]

CGPA_PATTERNS = [
    re.compile(r"(?:cgpa|cumulative\s*grade\s*point\s*average|ogpa|final\s*cgpa)\s*[:\-–]?\s*(\d{1,2}(?:\.\d{1,2})?)(?:\s*(?:\/|\s*out\s*of\s*)\s*10(?:\.0)?)?", re.I),
]

CERTIFICATE_NO_PATTERNS = [
    re.compile(r"(?:certificate\s*(?:no|number)|sl\.?\s*no\.?|serial\s*no\.?)\s*[:\-–]?\s*([A-Za-z0-9\/\-]{4,25})", re.I),
]

PASSING_YEAR_PATTERNS = [
    re.compile(r"(?:year\s*of\s*passing|passing\s*year|passed\s*in|graduation\s*year|month\s*and\s*year\s*of\s*passing)\s*[:\-–]?\s*(?:[A-Za-z]{3,9}\s*)?(\b(?:19|20)\d{2}\b)", re.I),
]

ISSUE_DATE_PATTERNS = [
    re.compile(r"(?:date\s*of\s*issue|issue\s*date|dated|date)\s*[:\-–]\s*([0-3]?\d[\/\-\.][0-1]?\d[\/\-\.]\d{2,4})", re.I),
]


def normalize_date_string(raw: str) -> str | None:
    """
    Attempt to normalize common unambiguous date formats into YYYY-MM-DD.
    Returns None if date is ambiguous or invalid.
    """
    cleaned = raw.strip()
    formats_to_try = [
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d %B %Y",
        "%d %b %Y",
        "%d %B, %Y",
        "%d %b, %Y",
    ]
    for fmt in formats_to_try:
        try:
            dt = datetime.strptime(cleaned, fmt)
            # Sanity check: valid academic/DOB range 1940 - 2035
            if 1940 <= dt.year <= 2035:
                return dt.strftime("%Y-%m-%d")
        except Exception:
            continue
    return None


def normalize_numeric_string(raw: str) -> float | None:
    """Parse numeric float from string."""
    cleaned = raw.strip().replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def clean_name(raw: str) -> str:
    """Clean name string of unwanted noise, multiple spaces, and title casing."""
    line = raw.split("\n")[0].split("\r")[0].strip()
    # Strip any trailing label keywords that might appear on the line
    line = re.split(
        r"\b(roll|reg|registration|register|date|dob|father|mother|gender|school|college|institution|board)\b",
        line,
        flags=re.I,
    )[0]
    cleaned = re.sub(r"\b(mr|ms|mrs|shri|smt|kumari|dr)\b\.?", "", line, flags=re.I)
    cleaned = re.sub(r"[^A-Za-z\s\.\']", "", cleaned)
    parts = cleaned.split()
    return " ".join(parts).title()


def extract_fields_from_text(text: str, document_type: str | None = None) -> ExtractedFields:
    """
    Extract structured candidate academic and identity fields from OCR/PDF text.
    Conservative pattern matching prevents fabrication.
    """
    if not text:
        return ExtractedFields()

    # Defense-in-depth: cap input length to prevent catastrophic backtracking (ReDoS)
    text = text[:MAX_OCR_TEXT_LENGTH]

    fields = ExtractedFields()

    # 1. Candidate Name
    for pattern in NAME_PATTERNS:
        m = pattern.search(text)
        if m:
            raw = m.group(1).split("\n")[0].split("\r")[0].strip()
            cleaned = clean_name(raw)
            if len(cleaned) >= 3 and not any(kw in cleaned.lower() for kw in ["examination", "board", "college", "marksheet"]):
                fields.candidateName = ExtractedField(
                    rawValue=raw,
                    normalizedValue=cleaned,
                    confidence=0.88 if len(cleaned.split()) >= 2 else 0.75,
                    evidence=m.group(0).strip()[:80],
                )
                break

    # 2. Date of Birth
    for pattern in DOB_PATTERNS:
        m = pattern.search(text)
        if m:
            raw = m.group(1).strip()
            normalized = normalize_date_string(raw)
            fields.dob = ExtractedField(
                rawValue=raw,
                normalizedValue=normalized,
                confidence=0.92 if normalized else 0.50,
                evidence=m.group(0).strip()[:80],
            )
            break

    # 3. Registration Number
    for pattern in REG_NO_PATTERNS:
        m = pattern.search(text)
        if m:
            raw = m.group(1).strip()
            # Clean punctuation from edges
            cleaned = raw.strip("/-.")
            if len(cleaned) >= 4:
                fields.registrationNumber = ExtractedField(
                    rawValue=raw,
                    normalizedValue=cleaned.upper(),
                    confidence=0.85,
                    evidence=m.group(0).strip()[:80],
                )
                break

    # 4. Institution / Board
    for pattern in INSTITUTION_PATTERNS:
        m = pattern.search(text)
        if m:
            raw = m.group(1).strip()
            cleaned = " ".join(raw.split()).title()
            if len(cleaned) >= 6:
                fields.institution = ExtractedField(
                    rawValue=raw,
                    normalizedValue=cleaned,
                    confidence=0.80,
                    evidence=m.group(0).strip()[:100],
                )
                break

    # 5. Course / Qualification
    for pattern in COURSE_PATTERNS:
        m = pattern.search(text)
        if m:
            raw = m.group(1).strip()
            cleaned = " ".join(raw.split()).title()
            fields.course = ExtractedField(
                rawValue=raw,
                normalizedValue=cleaned,
                confidence=0.80,
                evidence=m.group(0).strip()[:80],
            )
            break

    # 6. Marks Obtained & Max Marks
    for pattern in MARKS_OBTAINED_PATTERNS:
        m = pattern.search(text)
        if m:
            if len(m.groups()) == 2 and m.group(2):
                # Matched X / Y pattern
                raw_obt = m.group(1).strip()
                raw_max = m.group(2).strip()
                val_obt = normalize_numeric_string(raw_obt)
                val_max = normalize_numeric_string(raw_max)
                if val_obt is not None:
                    fields.marksObtained = ExtractedField(
                        rawValue=raw_obt,
                        normalizedValue=val_obt,
                        confidence=0.85,
                        evidence=m.group(0).strip()[:60],
                    )
                if val_max is not None:
                    fields.maxMarks = ExtractedField(
                        rawValue=raw_max,
                        normalizedValue=val_max,
                        confidence=0.85,
                        evidence=m.group(0).strip()[:60],
                    )
            else:
                raw_obt = m.group(1).strip()
                val_obt = normalize_numeric_string(raw_obt)
                if val_obt is not None:
                    fields.marksObtained = ExtractedField(
                        rawValue=raw_obt,
                        normalizedValue=val_obt,
                        confidence=0.80,
                        evidence=m.group(0).strip()[:60],
                    )
            break

    # Max Marks (standalone if not captured above)
    if not fields.maxMarks:
        for pattern in MAX_MARKS_PATTERNS:
            m = pattern.search(text)
            if m:
                raw_max = m.group(1).strip()
                val_max = normalize_numeric_string(raw_max)
                if val_max is not None:
                    fields.maxMarks = ExtractedField(
                        rawValue=raw_max,
                        normalizedValue=val_max,
                        confidence=0.80,
                        evidence=m.group(0).strip()[:60],
                    )
                    break

    # 7. Percentage
    for pattern in PERCENTAGE_PATTERNS:
        m = pattern.search(text)
        if m:
            raw = m.group(1).strip()
            val = normalize_numeric_string(raw)
            if val is not None and 0.0 <= val <= 100.0:
                fields.percentage = ExtractedField(
                    rawValue=raw,
                    normalizedValue=val,
                    confidence=0.88,
                    evidence=m.group(0).strip()[:60],
                )
                break

    # If percentage missing but marks obtained and max marks exist, calculate with evidence
    if not fields.percentage and fields.marksObtained and fields.maxMarks:
        obt = fields.marksObtained.normalizedValue
        max_m = fields.maxMarks.normalizedValue
        if obt and max_m and max_m > 0 and obt <= max_m:
            derived_pct = round((obt / max_m) * 100.0, 2)
            fields.percentage = ExtractedField(
                rawValue=f"{obt}/{max_m}",
                normalizedValue=derived_pct,
                confidence=0.82,
                evidence=f"Derived from marks {obt} / {max_m}",
            )

    # 8. CGPA
    for pattern in CGPA_PATTERNS:
        m = pattern.search(text)
        if m:
            raw = m.group(1).strip()
            val = normalize_numeric_string(raw)
            if val is not None and 0.0 <= val <= 10.0:
                fields.cgpa = ExtractedField(
                    rawValue=raw,
                    normalizedValue=val,
                    confidence=0.88,
                    evidence=m.group(0).strip()[:60],
                )
                break

    # 9. Certificate Number
    for pattern in CERTIFICATE_NO_PATTERNS:
        m = pattern.search(text)
        if m:
            raw = m.group(1).strip()
            cleaned = raw.strip("/-.")
            if len(cleaned) >= 4:
                fields.certificateNumber = ExtractedField(
                    rawValue=raw,
                    normalizedValue=cleaned.upper(),
                    confidence=0.82,
                    evidence=m.group(0).strip()[:60],
                )
                break

    # 10. Passing Year / Graduation Year
    for pattern in PASSING_YEAR_PATTERNS:
        m = pattern.search(text)
        if m:
            raw = m.group(1).strip()
            try:
                yr = int(raw)
                if 1970 <= yr <= 2035:
                    fields.passingYear = ExtractedField(
                        rawValue=raw,
                        normalizedValue=yr,
                        confidence=0.88,
                        evidence=m.group(0).strip()[:60],
                    )
                    break
            except ValueError:
                pass

    # 11. Issue Date
    for pattern in ISSUE_DATE_PATTERNS:
        m = pattern.search(text)
        if m:
            raw = m.group(1).strip()
            normalized = normalize_date_string(raw)
            fields.issueDate = ExtractedField(
                rawValue=raw,
                normalizedValue=normalized,
                confidence=0.85 if normalized else 0.50,
                evidence=m.group(0).strip()[:60],
            )
            break

    # 12. Mathematics Evidence (D5)
    # Extracts 'Mathematics' or 'Maths' with numeric marks on 12TH_MARKSHEET and UG_MARKSHEET
    if document_type in (None, "12TH_MARKSHEET", "UG_MARKSHEET"):
        for line in text.splitlines():
            line_clean = line.strip()
            if not line_clean:
                continue
            # ReDoS-safe linear check: look for mathematics or maths
            if re.search(r"(?i)\b(?:mathematics|maths)\b", line_clean):
                mark_match = re.search(r"\b(\d{1,3}(?:\.\d{1,2})?)\b", line_clean)
                if mark_match:
                    raw_mark = mark_match.group(1)
                    try:
                        numeric_mark = float(raw_mark)
                        if 0 <= numeric_mark <= 100:
                            fields.mathematics = ExtractedField(
                                rawValue=raw_mark,
                                normalizedValue=True,
                                confidence=0.88,
                                evidence=line_clean[:120],
                            )
                            break
                    except ValueError:
                        pass

    return fields
