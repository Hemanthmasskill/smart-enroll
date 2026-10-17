from collections import Counter
import re
import unicodedata
from typing import Tuple


HONORIFICS = {
    "mr",
    "mrs",
    "ms",
    "miss",
    "master",
    "shri",
    "sri",
    "smt",
    "shrimati",
    "kumari",
    "km",
    "dr",
    "prof",
    "er",
}


def detect_script(text: str) -> str:
    """
    Detect dominant script in the given string: 'latin', 'tamil', 'devanagari', or 'unknown'.
    """
    counts = {"latin": 0, "tamil": 0, "devanagari": 0}
    for char in text:
        cp = ord(char)
        if (0x0041 <= cp <= 0x005A) or (0x0061 <= cp <= 0x007A) or (0x00C0 <= cp <= 0x024F):
            counts["latin"] += 1
        elif 0x0B80 <= cp <= 0x0BFF:
            counts["tamil"] += 1
        elif 0x0900 <= cp <= 0x097F:
            counts["devanagari"] += 1

    dominant = max(counts, key=counts.get)
    if counts[dominant] > 0:
        return dominant
    return "unknown"


def tokenize_name(name: str) -> Tuple[list[str], str]:
    """
    Normalize Unicode (NFC), casefold, strip punctuation/honorifics,
    and return (tokens, script).
    """
    if not name or not name.strip():
        return [], "unknown"

    nfc = unicodedata.normalize("NFC", name.strip())
    script = detect_script(nfc)

    # Unicode-aware casefold
    lowered = nfc.casefold()

    # Split punctuation and special characters into spaces, preserving letters/numbers/combining marks
    # Keep Unicode alphanumeric and combining marks
    cleaned_chars = []
    for ch in lowered:
        cat = unicodedata.category(ch)
        # L = letter, M = combining mark, N = number
        if cat.startswith("L") or cat.startswith("M") or cat.startswith("N"):
            cleaned_chars.append(ch)
        else:
            cleaned_chars.append(" ")

    raw_tokens = "".join(cleaned_chars).split()

    # Filter recognized honorifics
    filtered_tokens = [tok for tok in raw_tokens if tok not in HONORIFICS]

    return filtered_tokens, script


def is_initial(token: str) -> bool:
    """A token is considered an initial if it is 1 letter long."""
    return len(token) == 1


def compare_names(extracted_name: str | None, canonical_name: str | None) -> Tuple[str, str]:
    """
    Deterministic comparison between extracted candidate name and authoritative canonical name.
    Returns: (status, reason_message)
    Status is one of: "MATCH", "MISMATCH", "MANUAL_REVIEW", "NOT_EXTRACTED"
    """
    if not extracted_name or not extracted_name.strip():
        return "NOT_EXTRACTED", "Candidate name not extracted from document."
    if not canonical_name or not canonical_name.strip():
        return "MANUAL_REVIEW", "Authoritative candidate name missing in canonical record."

    extracted_tokens, extracted_script = tokenize_name(extracted_name)
    canonical_tokens, canonical_script = tokenize_name(canonical_name)

    if not extracted_tokens:
        return "NOT_EXTRACTED", "Extracted name contains no usable tokens after normalization."
    if not canonical_tokens:
        return "MANUAL_REVIEW", "Canonical name contains no usable tokens after normalization."

    # Script compatibility check
    if (
        extracted_script != "unknown"
        and canonical_script != "unknown"
        and extracted_script != canonical_script
    ):
        return (
            "MANUAL_REVIEW",
            f"Different scripts detected (extracted: {extracted_script}, canonical: {canonical_script}). Equivalence requires manual review.",
        )

    # All-initial check: a name containing only initials cannot match full name
    extracted_all_initials = all(is_initial(t) for t in extracted_tokens)
    canonical_all_initials = all(is_initial(t) for t in canonical_tokens)
    if extracted_all_initials or canonical_all_initials:
        # If one is only initials, it's not enough to confirm identity
        return (
            "MANUAL_REVIEW",
            "Name consists solely of single-letter initials; cannot establish identity deterministically.",
        )

    extracted_counter = Counter(extracted_tokens)
    canonical_counter = Counter(canonical_tokens)

    # 1. Exact Token Multiset Agreement
    if extracted_counter == canonical_counter:
        has_full_token = any(len(t) >= 2 for t in extracted_tokens)
        if has_full_token:
            return "MATCH", "Candidate name matches canonical name exactly."
        return "MANUAL_REVIEW", "Candidate name tokens match but are too short for decisive confirmation."

    # Separate full tokens (len >= 2) and initials (len == 1)
    ext_full = [t for t in extracted_tokens if len(t) >= 2]
    can_full = [t for t in canonical_tokens if len(t) >= 2]

    ext_initials = [t for t in extracted_tokens if is_initial(t)]
    can_initials = [t for t in canonical_tokens if is_initial(t)]

    # Check for hard conflicts in full tokens:
    # If there are full tokens in extracted that don't match any full tokens or initials in canonical,
    # or vice-versa, examine if this is a conflicting identity.
    common_full = set(ext_full).intersection(set(can_full))
    ext_unmatched_full = set(ext_full) - common_full
    can_unmatched_full = set(can_full) - common_full

    # If both sides have full tokens that are completely disjoint, this is a clear MISMATCH
    if not common_full and ext_full and can_full:
        return (
            "MISMATCH",
            f"Candidate name '{extracted_name}' does not share core name tokens with canonical '{canonical_name}'.",
        )

    # Check if unmatched full tokens could plausibly correspond to initials on the other side
    # e.g. ext has initial 'm', can has full token 'madanapalli' starting with 'm'
    def could_be_initial_expansion(unmatched_full_tokens: set[str], initials: list[str]) -> bool:
        initial_set = set(initials)
        return all(tok[0] in initial_set for tok in unmatched_full_tokens)

    ext_expanded = could_be_initial_expansion(ext_unmatched_full, can_initials)
    can_expanded = could_be_initial_expansion(can_unmatched_full, ext_initials)

    # If there are unmatched full tokens that DO NOT match any initials and don't look like omitted components
    # E.g. extracted is "John Adams Smith", canonical is "John Brown Smith"
    # Here common_full is {"john", "smith"}, but ext has "adams" and can has "brown".
    # Neither "adams" matches 'b' nor "brown" matches 'a'.
    if ext_unmatched_full and can_unmatched_full:
        # Both sides have different full tokens that cannot be explained by initials
        if not (ext_expanded and can_expanded):
            return (
                "MISMATCH",
                f"Definitive conflicting name components detected: extracted has '{', '.join(sorted(ext_unmatched_full))}', canonical has '{', '.join(sorted(can_unmatched_full))}'.",
            )

    # If one side has unmatched full tokens or initials (e.g. initials expanded into names, omitted middle name, etc.)
    # This is a plausible variant, so return MANUAL_REVIEW (never claim MATCH and never claim hard MISMATCH).
    return (
        "MANUAL_REVIEW",
        f"Plausible name variation detected (e.g., expanded initials, omitted middle name, or additional tokens) between '{extracted_name}' and '{canonical_name}'.",
    )
