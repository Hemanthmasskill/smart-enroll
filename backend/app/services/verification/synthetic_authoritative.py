from datetime import datetime, timezone
from typing import Any
from app.schemas.verification import AuthoritativeVerificationRecord
from app.services.verification.dob_parser import parse_and_compare_dob
from app.services.verification.name_matcher import compare_names


SYNTHETIC_REGISTRY: dict[str, dict[str, Any]] = {
    # 1. Academic records (by registration number or certificate number)
    "SYNTH-REG-2022-001": {
        "status": "VALID",
        "candidateName": "Hemanth M.P.",
        "dob": "2000-05-15",
        "course": "MCA",
        "institution": "B.S. Abdur Rahman Crescent Institute",
        "passingYear": 2024,
        "issuer": "Simulated State University / DigiLocker",
        "applicableDocumentTypes": ["UG_MARKSHEET", "DEGREE_CERTIFICATE"],
    },
    "SYNTH-DEG-998877": {
        "status": "VALID",
        "candidateName": "Hemanth M.P.",
        "dob": "2000-05-15",
        "course": "BCA",
        "institution": "B.S. Abdur Rahman Crescent Institute",
        "passingYear": 2022,
        "issuer": "Simulated State University / DigiLocker",
        "applicableDocumentTypes": ["DEGREE_CERTIFICATE", "UG_MARKSHEET"],
    },
    "SYNTH-10TH-12345": {
        "status": "VALID",
        "candidateName": "Hemanth M.P.",
        "dob": "2000-05-15",
        "percentage": 86.5,
        "institution": "CBSE",
        "issuer": "Central Board of Secondary Education (Simulated)",
        "applicableDocumentTypes": ["10TH_MARKSHEET"],
    },
    # Conflicting or invalid synthetic records
    "SYNTH-REG-CONFLICT-002": {
        "status": "INVALID",
        "candidateName": "Different Name",
        "reason": "Record marked suspended or flagged for identity conflict in authoritative registry.",
        "issuer": "Simulated Academic Issuer",
        "applicableDocumentTypes": ["UG_MARKSHEET", "DEGREE_CERTIFICATE"],
    },
    "SYNTH-DEG-REVOKED-003": {
        "status": "REVOKED",
        "candidateName": "Hemanth M.P.",
        "reason": "Credential revoked by awarding institution.",
        "issuer": "Simulated Academic Issuer",
        "applicableDocumentTypes": ["DEGREE_CERTIFICATE"],
    },
    # 2. Government ID records (by certificate number / ID number)
    "SYNTH-GID-1001": {
        "status": "VALID",
        "candidateName": "Hemanth M.P.",
        "dob": "2000-05-15",
        "issuer": "Simulated UIDAI / National Identity Registry",
        "applicableDocumentTypes": ["GOVERNMENT_ID"],
    },
    "SYNTH-GID-REVOKED-1002": {
        "status": "REVOKED",
        "candidateName": "Hemanth M.P.",
        "reason": "Identity credential marked expired or invalid in simulated registry.",
        "issuer": "Simulated National Identity Registry",
        "applicableDocumentTypes": ["GOVERNMENT_ID"],
    },
}


class SyntheticAuthoritativeVerificationProvider:
    """
    Synthetic Authoritative Verification Provider (DigiLocker / NAD / Issuer simulation).
    Strictly isolated from live government endpoints. Discloses simulation clearly.
    Enforces candidate identity and document-type matching against synthetic fixtures.
    """

    def __init__(self, simulate_provider_fault: bool = False):
        self.simulate_provider_fault = simulate_provider_fault

    def verify_document_credential(
        self,
        document_type: str,
        extracted_fields: dict[str, Any],
        candidate_name: str | None = None,
    ) -> AuthoritativeVerificationRecord:
        now = datetime.now(timezone.utc).isoformat()

        # Check for simulated provider failure trigger
        if self.simulate_provider_fault:
            return AuthoritativeVerificationRecord(
                status="SIMULATION_UNAVAILABLE",
                lookupIdentifier=None,
                lookupField=None,
                verifiedAt=now,
                message="Simulated authoritative verification provider encountered an error.",
            )

        # 1. Determine appropriate lookup field and identifier by document type
        lookup_field: str | None = None
        lookup_identifier: str | None = None

        if document_type in ("10TH_MARKSHEET", "12TH_MARKSHEET", "UG_MARKSHEET"):
            # Registration number preferred, certificate number fallback
            reg = (extracted_fields.get("registrationNumber") or {}).get("normalizedValue")
            cert = (extracted_fields.get("certificateNumber") or {}).get("normalizedValue")
            if reg:
                lookup_field = "registrationNumber"
                lookup_identifier = str(reg).strip()
            elif cert:
                lookup_field = "certificateNumber"
                lookup_identifier = str(cert).strip()
        elif document_type == "DEGREE_CERTIFICATE":
            cert = (extracted_fields.get("certificateNumber") or {}).get("normalizedValue")
            reg = (extracted_fields.get("registrationNumber") or {}).get("normalizedValue")
            if cert:
                lookup_field = "certificateNumber"
                lookup_identifier = str(cert).strip()
            elif reg:
                lookup_field = "registrationNumber"
                lookup_identifier = str(reg).strip()
        elif document_type == "GOVERNMENT_ID":
            # Must strictly use certificate/identifier field, never registration number
            cert = (extracted_fields.get("certificateNumber") or {}).get("normalizedValue")
            if cert:
                lookup_field = "certificateNumber"
                lookup_identifier = str(cert).strip()
        elif document_type == "TRANSFER_CERTIFICATE":
            cert = (extracted_fields.get("certificateNumber") or {}).get("normalizedValue")
            if cert:
                lookup_field = "certificateNumber"
                lookup_identifier = str(cert).strip()

        # Outcome 1: No usable lookup identifier -> SIMULATION_UNAVAILABLE
        if not lookup_identifier or not lookup_field:
            return AuthoritativeVerificationRecord(
                status="SIMULATION_UNAVAILABLE",
                lookupIdentifier=None,
                lookupField=lookup_field,
                verifiedAt=now,
                message="No usable document identifier (registration or certificate number) extracted for authoritative lookup.",
            )

        # Trigger deliberate simulation failure
        if lookup_identifier == "SYNTH-FAIL-TRIGGER":
            return AuthoritativeVerificationRecord(
                status="SIMULATION_UNAVAILABLE",
                lookupIdentifier=lookup_identifier,
                lookupField=lookup_field,
                verifiedAt=now,
                message="Simulated authoritative verification provider network timeout.",
            )

        # Finding 1 / Finding 3: Validate field-level confidence of lookup identifier before registry query
        CONFIDENCE_THRESHOLD = 0.80

        def _get_field_confidence(field_dict: Any) -> float:
            if isinstance(field_dict, dict):
                conf = field_dict.get("confidence")
                if conf is not None:
                    try:
                        val = float(conf)
                        return val if val >= 0.0 else 0.0
                    except (ValueError, TypeError):
                        return 0.0
            return 0.0

        lookup_field_dict = extracted_fields.get(lookup_field) or {}
        lookup_conf = _get_field_confidence(lookup_field_dict)
        if lookup_conf < CONFIDENCE_THRESHOLD:
            return AuthoritativeVerificationRecord(
                status="SIMULATION_UNAVAILABLE",
                lookupIdentifier=lookup_identifier,
                lookupField=lookup_field,
                verifiedAt=now,
                message=(
                    f"Extracted lookup identifier '{lookup_field}' confidence ({lookup_conf:.2f}) "
                    f"is below the required {CONFIDENCE_THRESHOLD:.2f} threshold for authoritative verification."
                ),
            )

        # Outcome 2: Identifier provided but not found in synthetic fixture registry -> SIMULATED_NOT_FOUND
        record = SYNTHETIC_REGISTRY.get(lookup_identifier)
        if not record:
            return AuthoritativeVerificationRecord(
                status="SIMULATION_UNAVAILABLE" if lookup_identifier.startswith("INVALID-") else "SIMULATED_NOT_FOUND",
                lookupIdentifier=lookup_identifier,
                lookupField=lookup_field,
                verifiedAt=now,
                message=f"No authoritative record found in synthetic registry for identifier '{lookup_identifier}'.",
            )

        # Outcome 4: Registered fixture contains a conflict or is marked invalid/revoked -> SIMULATED_MISMATCH
        if record.get("status") in ("INVALID", "REVOKED"):
            return AuthoritativeVerificationRecord(
                status="SIMULATED_MISMATCH",
                lookupIdentifier=lookup_identifier,
                lookupField=lookup_field,
                verifiedAt=now,
                recordData=record,
                message=f"Synthetic authoritative record indicates discrepancy: {record.get('reason', 'Record invalid or revoked in registry.')}",
            )

        # Check document-type compatibility with fixture
        applicable_types = record.get("applicableDocumentTypes")
        if applicable_types and document_type not in applicable_types:
            return AuthoritativeVerificationRecord(
                status="SIMULATION_UNAVAILABLE",
                lookupIdentifier=lookup_identifier,
                lookupField=lookup_field,
                verifiedAt=now,
                recordData=record,
                message=f"Synthetic fixture '{lookup_identifier}' is for document type(s) {applicable_types}, incompatible with requested document type '{document_type}'.",
            )

        # Identity Verification: compare candidate name
        submitted_name = candidate_name
        cand_field = extracted_fields.get("candidateName") or {}
        if not submitted_name:
            submitted_name = cand_field.get("normalizedValue") or cand_field.get("rawValue")

        fixture_name = record.get("candidateName")
        if not submitted_name or not fixture_name:
            return AuthoritativeVerificationRecord(
                status="SIMULATION_UNAVAILABLE",
                lookupIdentifier=lookup_identifier,
                lookupField=lookup_field,
                verifiedAt=now,
                recordData=record,
                message="Insufficient identity evidence (candidate name missing on document or fixture) to establish authoritative match.",
            )

        # Candidate name confidence check before decisive comparison
        name_conf = _get_field_confidence(cand_field)
        if name_conf < CONFIDENCE_THRESHOLD:
            return AuthoritativeVerificationRecord(
                status="SIMULATION_UNAVAILABLE",
                lookupIdentifier=lookup_identifier,
                lookupField=lookup_field,
                verifiedAt=now,
                recordData=record,
                message=(
                    f"Candidate name extraction confidence ({name_conf:.2f}) "
                    f"is below the required {CONFIDENCE_THRESHOLD:.2f} threshold for authoritative verification."
                ),
            )

        name_status, name_msg = compare_names(submitted_name, fixture_name)
        if name_status == "MISMATCH":
            return AuthoritativeVerificationRecord(
                status="SIMULATED_MISMATCH",
                lookupIdentifier=lookup_identifier,
                lookupField=lookup_field,
                verifiedAt=now,
                recordData=record,
                message=f"Identity conflict in authoritative record: submitted name '{submitted_name}' does not match fixture name '{fixture_name}'.",
            )
        elif name_status != "MATCH":
            # Plausible name variation or ambiguity -> cannot declare SIMULATED_MATCH
            return AuthoritativeVerificationRecord(
                status="SIMULATION_UNAVAILABLE",
                lookupIdentifier=lookup_identifier,
                lookupField=lookup_field,
                verifiedAt=now,
                recordData=record,
                message=f"Candidate name on fixture differs from submitted document ({name_msg}). Insufficient proof to establish match.",
            )

        # Finding 1: Check DOB if present on fixture
        fixture_dob = record.get("dob")
        dob_field = extracted_fields.get("dob") or {}
        submitted_dob = dob_field.get("rawValue") or dob_field.get("normalizedValue")

        if fixture_dob:
            if not submitted_dob:
                return AuthoritativeVerificationRecord(
                    status="SIMULATION_UNAVAILABLE",
                    lookupIdentifier=lookup_identifier,
                    lookupField=lookup_field,
                    verifiedAt=now,
                    recordData=record,
                    message="Date of birth is required by the authoritative fixture but missing from extracted document fields.",
                )

            # DOB confidence check before decisive comparison
            dob_conf = _get_field_confidence(dob_field)
            if dob_conf < CONFIDENCE_THRESHOLD:
                return AuthoritativeVerificationRecord(
                    status="SIMULATION_UNAVAILABLE",
                    lookupIdentifier=lookup_identifier,
                    lookupField=lookup_field,
                    verifiedAt=now,
                    recordData=record,
                    message=(
                        f"Date of birth extraction confidence ({dob_conf:.2f}) "
                        f"is below the required {CONFIDENCE_THRESHOLD:.2f} threshold for authoritative verification."
                    ),
                )

            dob_status, dob_msg, _ = parse_and_compare_dob(submitted_dob, fixture_dob)
            if dob_status == "MISMATCH":
                return AuthoritativeVerificationRecord(
                    status="SIMULATED_MISMATCH",
                    lookupIdentifier=lookup_identifier,
                    lookupField=lookup_field,
                    verifiedAt=now,
                    recordData=record,
                    message=f"DOB conflict in authoritative record: submitted DOB '{submitted_dob}' does not match fixture DOB '{fixture_dob}'.",
                )
            elif dob_status != "MATCH":
                # Malformed, unparseable, or ambiguous DOB must not produce SIMULATED_MATCH
                return AuthoritativeVerificationRecord(
                    status="SIMULATION_UNAVAILABLE",
                    lookupIdentifier=lookup_identifier,
                    lookupField=lookup_field,
                    verifiedAt=now,
                    recordData=record,
                    message=f"Date of birth on document could not be decisively verified against authoritative fixture ({dob_msg}).",
                )

        # Outcome 3: Registered synthetic fixture matches with verified identity
        return AuthoritativeVerificationRecord(
            status="SIMULATED_MATCH",
            lookupIdentifier=lookup_identifier,
            lookupField=lookup_field,
            verifiedAt=now,
            recordData=record,
            message=f"Simulated authoritative credential verified via {record.get('issuer', 'DigiLocker/NAD simulation')}.",
        )
