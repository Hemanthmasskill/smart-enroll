import re
from app.schemas.document import DOCUMENT_TYPES
from app.schemas.document_processing import ClassificationResult

MAX_CLASSIFIER_TEXT_LENGTH = 100_000

# Evidence rules with weighting
CLASSIFICATION_PATTERNS: dict[str, list[tuple[re.Pattern, str, float]]] = {
    "10TH_MARKSHEET": [
        (re.compile(r"\b(secondary school examination|secondary school certificate|sslc|matriculation)\b", re.I), "Secondary school certificate heading", 0.5),
        (re.compile(r"\b(class\s*x\b|class\s*10\b|10th\s*marksheet|tenth\s*standard|high\s*school\s*certificate)\b", re.I), "Class 10 / Secondary reference", 0.4),
        (re.compile(r"\b(board of secondary education|central board of secondary education)\b", re.I), "Secondary board authority", 0.3),
        (re.compile(r"\b(statement of marks.*secondary|secondary.*marksheet)\b", re.I), "Secondary marksheet header", 0.4),
    ],
    "12TH_MARKSHEET": [
        (re.compile(r"\b(higher secondary|senior school certificate|hsc|senior secondary)\b", re.I), "Higher secondary certificate heading", 0.5),
        (re.compile(r"\b(class\s*xii\b|class\s*12\b|12th\s*marksheet|twelfth\s*standard|intermediate examination)\b", re.I), "Class 12 / Higher secondary reference", 0.4),
        (re.compile(r"\b(board of higher secondary|council of higher secondary)\b", re.I), "Higher secondary board authority", 0.3),
        (re.compile(r"\b(statement of marks.*higher secondary|senior school marksheet)\b", re.I), "Senior school marksheet header", 0.4),
    ],
    "UG_MARKSHEET": [
        (re.compile(r"\b(consolidated (statement of )?marks|grade card|semester|grade sheet|cumulative grade point)\b", re.I), "Semester / Consolidated grade card terminology", 0.4),
        (re.compile(r"\b(bachelor of (technology|science|computer applications|commerce|engineering|arts)|b\.tech|b\.sc|b\.c\.a|bca|b\.com|b\.e)\b", re.I), "Undergraduate degree program reference", 0.4),
        (re.compile(r"\b(undergraduate marksheet|ug marksheet|transcript of records)\b", re.I), "UG transcript reference", 0.5),
        (re.compile(r"\b(credits earned|sgpa|cgpa|course code|subject credits)\b", re.I), "University grade metrics", 0.3),
    ],
    "DEGREE_CERTIFICATE": [
        (re.compile(r"\b(degree of bachelor|admitted to the degree|conferred upon|awarded the degree)\b", re.I), "Degree conferral declaration", 0.5),
        (re.compile(r"\b(provisional (degree )?certificate|original degree certificate|course completion certificate)\b", re.I), "Degree certificate title", 0.5),
        (re.compile(r"\b(convocation|chancellor|vice[-\s]?chancellor|registrar)\b", re.I), "University degree signatories", 0.3),
        (re.compile(r"\b(qualified for the degree|passed the examination for the degree)\b", re.I), "Degree qualification clause", 0.4),
    ],
    "TRANSFER_CERTIFICATE": [
        (re.compile(r"\b(transfer certificate|school leaving certificate|college leaving certificate)\b", re.I), "Transfer / Leaving certificate title", 0.6),
        (re.compile(r"\b(conduct certificate|character certificate|migration certificate)\b", re.I), "Conduct / Migration certificate title", 0.5),
        (re.compile(r"\b(date of leaving|reason for leaving|left the school|left the college)\b", re.I), "Leaving details", 0.4),
        (re.compile(r"\b(admitted on|date of admission.*date of relief)\b", re.I), "Attendance / Relief clause", 0.3),
    ],
    "GOVERNMENT_ID": [
        (re.compile(r"\b(unique identification authority of india|uidai|aadhaar|eaadhaar)\b", re.I), "Aadhaar government identifier", 0.6),
        (re.compile(r"\b(income tax department|permanent account number|pan card)\b", re.I), "PAN card identifier", 0.6),
        (re.compile(r"\b(election commission of india|elector'?s photo identity|voter id|epic)\b", re.I), "Voter ID identifier", 0.6),
        (re.compile(r"\b(driving licen[cs]e|motor vehicles department|republic of india passport)\b", re.I), "License / Passport identifier", 0.6),
        (re.compile(r"\b(government of india|govt\. of india)\b", re.I), "Government of India emblem / header", 0.3),
    ],
}


def classify_document(text: str, expected_type: str | None = None) -> ClassificationResult:
    """
    Classify document text using deterministic keyword and pattern matching.
    Calculates predicted type, confidence score, matched evidence, and discrepancy observations.
    Never alters stored document types.
    """
    if not text or not text.strip():
        return ClassificationResult(
            predictedType=None,
            confidence=0.0,
            evidence=[],
            typeMismatch=False,
            observation="No text content available to perform document classification.",
        )

    # Defense-in-depth: cap text length to prevent ReDoS
    capped_text = text[:MAX_CLASSIFIER_TEXT_LENGTH]
    clean_text = " ".join(capped_text.split())

    scores: dict[str, float] = {dtype: 0.0 for dtype in DOCUMENT_TYPES}
    evidence_map: dict[str, list[str]] = {dtype: [] for dtype in DOCUMENT_TYPES}

    for dtype, patterns in CLASSIFICATION_PATTERNS.items():
        for pattern, label, weight in patterns:
            match = pattern.search(clean_text)
            if match:
                scores[dtype] += weight
                evidence_map[dtype].append(f"{label} ('{match.group(0)[:40]}')")

    # Find highest scoring type
    best_type: str | None = None
    best_score = 0.0

    # Sort descending by score
    sorted_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_type, top_score = sorted_scores[0]

    # Minimum evidence threshold to avoid false random matches
    if top_score >= 0.3:
        best_type = top_type
        # Calibrated confidence bound: min(top_score, 1.0)
        # Margin over second-best score provides confidence weighting
        second_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0
        confidence = min(0.5 + (top_score - second_score) * 0.3 + top_score * 0.2, 0.98)
    else:
        best_type = None
        confidence = 0.0

    evidence = evidence_map[best_type] if best_type else []

    # Check for discrepancy with expected uploaded type
    type_mismatch = False
    observation: str | None = None

    if best_type is None:
        observation = "Insufficient layout-independent evidence to confidently classify document."
    elif expected_type:
        if best_type != expected_type:
            type_mismatch = True
            observation = (
                f"Classification observation: document content strongly resembles '{best_type}', "
                f"which differs from the uploaded slot '{expected_type}'."
            )
        else:
            observation = f"Document content conforms to expected slot '{expected_type}'."
    else:
        observation = f"Document classified as '{best_type}' with {len(evidence)} evidence points."

    return ClassificationResult(
        predictedType=best_type,
        confidence=round(confidence, 2),
        evidence=evidence,
        typeMismatch=type_mismatch,
        observation=observation,
    )
