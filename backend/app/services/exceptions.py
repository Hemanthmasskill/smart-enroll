from datetime import datetime, timezone
import logging
from typing import Any, Optional
import uuid

from bson import ObjectId
from fastapi import HTTPException, status
from pymongo.database import Database

from app.agents.orchestrator import AgentOrchestrator
from app.agents.tools import REQUIRED_DOCUMENT_TYPES
from app.schemas.exceptions import (
    AuditEvent,
    ExceptionResponse,
    ExceptionSeverity,
    ExceptionStatus,
    ExceptionType,
)

logger = logging.getLogger(__name__)

# Deterministic severity mapping
DEFAULT_SEVERITY_MAP: dict[str, str] = {
    ExceptionType.ELIGIBILITY_CONFLICT.value: ExceptionSeverity.CRITICAL.value,
    ExceptionType.NAME_MISMATCH.value: ExceptionSeverity.HIGH.value,
    ExceptionType.DOB_MISMATCH.value: ExceptionSeverity.HIGH.value,
    ExceptionType.ACADEMIC_MISMATCH.value: ExceptionSeverity.HIGH.value,
    ExceptionType.UNREADABLE_DOCUMENT.value: ExceptionSeverity.HIGH.value,
    ExceptionType.INVALID_FILE.value: ExceptionSeverity.HIGH.value,
    ExceptionType.MISSING_DOCUMENT.value: ExceptionSeverity.MEDIUM.value,
    ExceptionType.DUPLICATE_DOCUMENT.value: ExceptionSeverity.MEDIUM.value,
    ExceptionType.VERIFICATION_UNAVAILABLE.value: ExceptionSeverity.LOW.value,
}

VALID_EXCEPTION_TYPES = set(DEFAULT_SEVERITY_MAP.keys())


def ensure_exception_indexes(db: Database) -> None:
    """
    Ensure robust indexes on the exceptions and notifications collections.
    Includes partial unique index to prevent duplicate active exceptions for the same issue.
    """
    try:
        db["exceptions"].create_index("exceptionId", unique=True)
        db["exceptions"].create_index([("applicationId", 1), ("status", 1)])
        db["exceptions"].create_index([("userId", 1), ("status", 1)])
        db["exceptions"].create_index("createdAt")
        # Unique partial index on dedupeKey for active exceptions
        db["exceptions"].create_index(
            "dedupeKey",
            unique=True,
            partialFilterExpression={"status": {"$in": ["OPEN", "MONITORING"]}},
        )

        # Increment 18 compatible notifications collection indexes
        db["notifications"].create_index("notificationId", unique=True)
        db["notifications"].create_index([("userId", 1), ("read", 1), ("createdAt", -1)])
        db["notifications"].create_index("dedupeKey", unique=True, sparse=True)
    except Exception as e:
        logger.warning("Index creation note for exceptions/notifications: %s", str(e))


def get_exception_severity(exception_type: str, metadata: dict[str, Any] | None = None) -> str:
    """Deterministically map exception type to its severity, respecting explicit overrides if valid."""
    meta = metadata or {}
    if "severity" in meta and meta["severity"] in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        return str(meta["severity"])
    return DEFAULT_SEVERITY_MAP.get(exception_type, ExceptionSeverity.MEDIUM.value)


def compute_dedupe_key(application_id: str, exception_type: str, metadata: dict[str, Any] | None = None) -> str:
    """Compute deterministic idempotency key for an exception instance."""
    meta = metadata or {}
    subject = (
        meta.get("documentType")
        or meta.get("field")
        or meta.get("ruleId")
        or meta.get("documentId")
        or "default"
    )
    return f"{application_id}:{exception_type}:{subject}"


def create_exception(
    db: Database,
    application_id: str,
    exception_type: str,
    description: str,
    source: str = "SYSTEM",
    metadata: dict[str, Any] | None = None,
    created_by: Any = None,
) -> dict[str, Any] | None:
    """
    Create a new persistent exception record in MongoDB.
    Enforces:
    - 9 supported exception types.
    - Deterministic severity mapping.
    - Idempotent active duplicate prevention (returns existing active exception if one exists).
    - Never creates exceptions for ordinary DRAFT applications.
    - Compatible notification dispatch to 'notifications' collection.
    """
    clean_type = (exception_type or "").strip().upper()
    if clean_type not in VALID_EXCEPTION_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid exception type '{exception_type}'. Must be one of: {', '.join(sorted(VALID_EXCEPTION_TYPES))}",
        )

    app = db["applications"].find_one({"applicationId": application_id})
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{application_id}' not found.",
        )

    # Invariant: Do not create false exceptions for ordinary DRAFT applications
    if app.get("status") == "DRAFT":
        logger.info("Ignoring exception creation for DRAFT application %s", application_id)
        return None

    meta = dict(metadata or {})
    severity = get_exception_severity(clean_type, meta)
    dedupe_key = compute_dedupe_key(application_id, clean_type, meta)

    # Check for existing active exception with this dedupeKey
    existing = db["exceptions"].find_one({
        "applicationId": application_id,
        "dedupeKey": dedupe_key,
        "status": {"$in": ["OPEN", "MONITORING"]},
    })
    if existing:
        logger.info("Active exception with dedupeKey '%s' already exists for application %s", dedupe_key, application_id)
        return existing

    now_utc = datetime.now(timezone.utc).isoformat()
    exception_id = f"EXC-{uuid.uuid4().hex[:8].upper()}"
    user_id = str(app.get("userId") or "")
    applicant_id = str(app.get("applicantId") or user_id)
    applicant_name = str(app.get("fullName") or "Applicant")

    actor_info = created_by or "SYSTEM"
    initial_audit = {
        "action": "CREATED",
        "actor": actor_info,
        "timestamp": now_utc,
        "details": {
            "type": clean_type,
            "severity": severity,
            "source": source,
            "description": description,
        },
    }

    exc_doc = {
        "exceptionId": exception_id,
        "applicationId": application_id,
        "applicantId": applicant_id,
        "applicantName": applicant_name,
        "userId": user_id,
        "type": clean_type,
        "description": description,
        "severity": severity,
        "status": ExceptionStatus.OPEN.value,
        "source": source,
        "metadata": meta,
        "dedupeKey": dedupe_key,
        "createdAt": now_utc,
        "updatedAt": now_utc,
        "resolvedAt": None,
        "resolvedBy": None,
        "resolutionReason": None,
        "auditEvents": [initial_audit],
    }

    try:
        db["exceptions"].insert_one(exc_doc)
    except Exception as exc_err:
        # Race-condition fallback: if partial unique index matched concurrent insert
        existing_race = db["exceptions"].find_one({
            "applicationId": application_id,
            "dedupeKey": dedupe_key,
            "status": {"$in": ["OPEN", "MONITORING"]},
        })
        if existing_race:
            return existing_race
        logger.error("Failed to insert exception %s: %s", exception_id, str(exc_err))
        raise

    # Increment 18 Notification Record Compatibility
    notif_id = f"NOTIF-{uuid.uuid4().hex[:8].upper()}"
    notif_dedupe = f"NOTIF:EXC:{exception_id}:CREATED"
    notif_doc = {
        "notificationId": notif_id,
        "userId": user_id,
        "applicantId": applicant_id,
        "applicationId": application_id,
        "type": "EXCEPTION_CREATED",
        "title": f"Action Required: {clean_type.replace('_', ' ').title()}",
        "message": description,
        "read": False,
        "createdAt": now_utc,
        "metadata": {
            "exceptionId": exception_id,
            "exceptionType": clean_type,
            "severity": severity,
        },
        "dedupeKey": notif_dedupe,
    }
    try:
        db["notifications"].update_one(
            {"dedupeKey": notif_dedupe},
            {"$setOnInsert": notif_doc},
            upsert=True,
        )
    except Exception as n_err:
        logger.warning("Could not dispatch exception creation notification: %s", str(n_err))

    return exc_doc


def get_exception_by_id(db: Database, exception_id: str, current_user: dict) -> dict[str, Any]:
    """
    Retrieve exception by ID with strict applicant ownership boundary.
    Admins can view any exception. Applicants can only view their own.
    """
    exc = db["exceptions"].find_one({"exceptionId": exception_id}, {"_id": 0})
    if not exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exception '{exception_id}' not found.",
        )

    user_role = current_user.get("role")
    if user_role != "admin":
        user_id = str(current_user.get("_id") or current_user.get("id"))
        if exc.get("userId") != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: access denied. Not authorized to view this exception.",
            )

    return exc


def list_exceptions(
    db: Database,
    current_user: dict,
    status_filter: Optional[str] = None,
    severity_filter: Optional[str] = None,
    type_filter: Optional[str] = None,
    application_id: Optional[str] = None,
    limit: int = 100,
    skip: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """
    Admin-only listing of exceptions with filtering and pagination.
    """
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operation not permitted for this role. Admin privileges required.",
        )

    query: dict[str, Any] = {}
    if status_filter and status_filter.upper() != "ALL":
        query["status"] = status_filter.upper()
    if severity_filter and severity_filter.upper() != "ALL":
        query["severity"] = severity_filter.upper()
    if type_filter and type_filter.upper() != "ALL":
        query["type"] = type_filter.upper()
    if application_id:
        query["applicationId"] = application_id

    total = db["exceptions"].count_documents(query)
    cursor = (
        db["exceptions"]
        .find(query, {"_id": 0})
        .sort("createdAt", -1)
        .skip(max(0, skip))
        .limit(min(100, max(1, limit)))
    )
    items = list(cursor)
    return items, total


def list_my_exceptions(
    db: Database,
    current_user: dict,
    status_filter: Optional[str] = None,
    limit: int = 50,
    skip: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """
    Retrieve authenticated applicant's own exceptions.
    Strictly scoped to current_user._id.
    """
    user_id = str(current_user.get("_id") or current_user.get("id"))
    query: dict[str, Any] = {"userId": user_id}
    if status_filter and status_filter.upper() != "ALL":
        query["status"] = status_filter.upper()

    total = db["exceptions"].count_documents(query)
    cursor = (
        db["exceptions"]
        .find(query, {"_id": 0})
        .sort("createdAt", -1)
        .skip(max(0, skip))
        .limit(min(100, max(1, limit)))
    )
    items = list(cursor)
    return items, total


def resolve_exception(
    db: Database,
    exception_id: str,
    resolution_reason: str,
    admin_user: dict,
    resume_workflow: bool = True,
) -> dict[str, Any]:
    """
    Admin-only resolution of an exception.
    Enforces:
    - Admin authorization.
    - Mandatory, non-empty, meaningful resolution reason.
    - Precondition check for MISSING_DOCUMENT: verifies document is actually supplied.
    - Atomic CAS update on exception status (prevents double/concurrent resolution).
    - Clears procedural document discrepancy flags where applicable.
    - Notification record compatibility with Increment 18.
    - Safe workflow resumption through existing orchestrator without overriding eligibility rules.
    """
    if admin_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operation not permitted for this role. Admin privileges required.",
        )

    reason_clean = (resolution_reason or "").strip()
    if len(reason_clean) < 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A meaningful resolution reason of at least 5 characters is required.",
        )

    exc = db["exceptions"].find_one({"exceptionId": exception_id})
    if not exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exception '{exception_id}' not found.",
        )

    if exc.get("status") == ExceptionStatus.RESOLVED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Exception '{exception_id}' has already been resolved.",
        )

    app_id = exc.get("applicationId")

    # Precondition for MISSING_DOCUMENT: verify required document has actually been uploaded
    if exc.get("type") == ExceptionType.MISSING_DOCUMENT.value:
        target_doc_type = exc.get("metadata", {}).get("documentType")
        if target_doc_type:
            doc_rec = db["documents"].find_one({
                "applicationId": app_id,
                "documentType": target_doc_type,
                "status": {"$ne": "NOT_UPLOADED"},
            })
            if not doc_rec:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot resolve MISSING_DOCUMENT: document '{target_doc_type}' has not been uploaded yet.",
                )
        else:
            # Check all 6 required document types
            existing_docs = list(db["documents"].find({"applicationId": app_id, "status": {"$ne": "NOT_UPLOADED"}}))
            uploaded_types = {d.get("documentType") for d in existing_docs if d.get("documentType")}
            missing = [t for t in REQUIRED_DOCUMENT_TYPES if t not in uploaded_types]
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot resolve MISSING_DOCUMENT: required document(s) still missing: {', '.join(sorted(missing))}.",
                )

    now_utc = datetime.now(timezone.utc).isoformat()
    admin_actor = {
        "userId": str(admin_user.get("_id") or admin_user.get("id")),
        "email": admin_user.get("email"),
        "fullName": admin_user.get("fullName") or "Administrator",
        "role": admin_user.get("role", "admin"),
    }

    resolution_audit = {
        "action": "RESOLVED",
        "actor": admin_actor,
        "timestamp": now_utc,
        "details": {
            "previousStatus": exc.get("status"),
            "newStatus": ExceptionStatus.RESOLVED.value,
            "resolutionReason": reason_clean,
        },
    }

    # Atomic CAS update: only update if currently OPEN or MONITORING
    updated_exc = db["exceptions"].find_one_and_update(
        {
            "exceptionId": exception_id,
            "status": {"$in": [ExceptionStatus.OPEN.value, ExceptionStatus.MONITORING.value]},
        },
        {
            "$set": {
                "status": ExceptionStatus.RESOLVED.value,
                "resolvedAt": now_utc,
                "resolvedBy": admin_actor,
                "resolutionReason": reason_clean,
                "updatedAt": now_utc,
            },
            "$push": {"auditEvents": resolution_audit},
        },
        return_document=True,
    )
    if not updated_exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflict: Exception was modified or resolved concurrently by another process.",
        )

    # If linked to a document discrepancy (e.g. NAME_MISMATCH, DOB_MISMATCH, ACADEMIC_MISMATCH),
    # update document validationStatus so the orchestrator's verification gate can proceed.
    doc_id = exc.get("metadata", {}).get("documentId")
    doc_type = exc.get("metadata", {}).get("documentType")
    if doc_id:
        db["documents"].update_one(
            {"documentId": doc_id},
            {
                "$set": {
                    "validationStatus": "VALIDATED",
                    "status": "VALIDATED",
                    "validationRemarks": f"Procedural exception cleared by admin ({admin_actor['email']}): {reason_clean}",
                    "updatedAt": now_utc,
                }
            },
        )
    elif doc_type and exc.get("type") in (
        ExceptionType.NAME_MISMATCH.value,
        ExceptionType.DOB_MISMATCH.value,
        ExceptionType.ACADEMIC_MISMATCH.value,
        ExceptionType.VERIFICATION_UNAVAILABLE.value,
    ):
        db["documents"].update_many(
            {"applicationId": app_id, "documentType": doc_type},
            {
                "$set": {
                    "validationStatus": "VALIDATED",
                    "status": "VALIDATED",
                    "validationRemarks": f"Procedural exception cleared by admin ({admin_actor['email']}): {reason_clean}",
                    "updatedAt": now_utc,
                }
            },
        )

    # Increment 18 Notification Record Compatibility
    notif_id = f"NOTIF-{uuid.uuid4().hex[:8].upper()}"
    notif_dedupe = f"NOTIF:EXC:{exception_id}:RESOLVED"
    notif_doc = {
        "notificationId": notif_id,
        "userId": exc.get("userId"),
        "applicantId": exc.get("applicantId"),
        "applicationId": app_id,
        "type": "EXCEPTION_RESOLVED",
        "title": f"Exception Resolved: {exc.get('type', '').replace('_', ' ').title()}",
        "message": f"An administrator resolved your application issue: {reason_clean}",
        "read": False,
        "createdAt": now_utc,
        "metadata": {
            "exceptionId": exception_id,
            "exceptionType": exc.get("type"),
            "resolutionReason": reason_clean,
        },
        "dedupeKey": notif_dedupe,
    }
    try:
        db["notifications"].update_one(
            {"dedupeKey": notif_dedupe},
            {"$setOnInsert": notif_doc},
            upsert=True,
        )
    except Exception as n_err:
        logger.warning("Could not dispatch exception resolution notification: %s", str(n_err))

    # Workflow Resumption Logic
    # Check if there are other active exceptions remaining for this application
    active_count = db["exceptions"].count_documents({
        "applicationId": app_id,
        "status": {"$in": [ExceptionStatus.OPEN.value, ExceptionStatus.MONITORING.value]},
    })

    app_rec = db["applications"].find_one({"applicationId": app_id})
    if active_count == 0 and app_rec:
        current_status = app_rec.get("status")
        # Only transition if currently stalled in EXCEPTION or WAITING_FOR_DOCUMENTS
        if current_status in ("EXCEPTION", "WAITING_FOR_DOCUMENTS"):
            # If resolving an ELIGIBILITY_CONFLICT, return to ELIGIBILITY_CHECK so deterministic engine runs.
            # In all other cases, return to PROCESSING to resume normal workflow progression.
            # Invariant: NEVER mark ELIGIBLE or PROCESSING_COMPLETE directly.
            target_status = "ELIGIBILITY_CHECK" if exc.get("type") == ExceptionType.ELIGIBILITY_CONFLICT.value else "PROCESSING"
            db["applications"].update_one(
                {"applicationId": app_id},
                {
                    "$set": {
                        "status": target_status,
                        "statusReason": f"Exception {exception_id} resolved by admin: {reason_clean}",
                        "updatedAt": now_utc,
                    }
                },
            )

            if resume_workflow:
                try:
                    user_id_val = app_rec.get("userId")
                    owner_user = None
                    if user_id_val:
                        try:
                            owner_user = db["users"].find_one({"_id": ObjectId(user_id_val)})
                        except Exception:
                            owner_user = db["users"].find_one({"_id": user_id_val})
                    if not owner_user:
                        owner_user = {
                            "role": "applicant",
                            "_id": user_id_val,
                            "email": app_rec.get("email"),
                            "fullName": app_rec.get("fullName"),
                        }
                    orchestrator = AgentOrchestrator(db=db)
                    orchestrator.run(app_id, owner_user)
                except Exception as r_err:
                    logger.warning("Workflow resumption safe notice for application %s: %s", app_id, str(r_err))

    # Return serialized exception document without MongoDB _id
    updated_exc.pop("_id", None)
    return updated_exc


def sync_exceptions_for_application(db: Database, application_id: str) -> list[dict[str, Any]]:
    """
    Automatic exception discovery helper:
    Inspects application documents, verification results, and eligibility evaluations,
    creating deterministic exception records for detected discrepancies.
    Does NOT create false exceptions for ordinary DRAFT applications.
    """
    app = db["applications"].find_one({"applicationId": application_id})
    if not app or app.get("status") == "DRAFT":
        return []

    created_or_found: list[dict[str, Any]] = []
    docs = list(db["documents"].find({"applicationId": application_id}))

    # 1. Missing documents check
    existing_types = {d.get("documentType") for d in docs if d.get("status") != "NOT_UPLOADED"}
    missing = [t for t in REQUIRED_DOCUMENT_TYPES if t not in existing_types]
    if missing:
        desc = f"Required document(s) missing: {', '.join(sorted(missing))}."
        res = create_exception(
            db=db,
            application_id=application_id,
            exception_type=ExceptionType.MISSING_DOCUMENT.value,
            description=desc,
            source="ORCHESTRATOR",
            metadata={"missingDocumentTypes": missing},
        )
        if res:
            created_or_found.append(res)

    # 2. Document verification discrepancies
    for d in docs:
        doc_type = d.get("documentType", "DOCUMENT")
        doc_id = d.get("documentId")
        val_status = d.get("validationStatus")
        val_result = d.get("validationResult") or {}
        reasons = val_result.get("reasons") or []
        reasons_text = "; ".join(reasons) if reasons else d.get("validationRemarks") or "Discrepancy detected"

        if d.get("processingStatus") == "FAILED":
            res = create_exception(
                db=db,
                application_id=application_id,
                exception_type=ExceptionType.UNREADABLE_DOCUMENT.value,
                description=f"OCR processing failed for {doc_type}: {reasons_text}",
                source="OCR_PROCESSING",
                metadata={"documentId": doc_id, "documentType": doc_type},
            )
            if res:
                created_or_found.append(res)

        elif val_status in ("MISMATCH", "MANUAL_REVIEW"):
            # Classify specific discrepancy type
            field_results = val_result.get("fieldResults") or {}
            if "candidateName" in field_results or "name" in reasons_text.lower():
                exc_type = ExceptionType.NAME_MISMATCH.value
            elif "dob" in field_results or "dob" in reasons_text.lower() or "date of birth" in reasons_text.lower():
                exc_type = ExceptionType.DOB_MISMATCH.value
            elif "authoritative" in reasons_text.lower() or "simulation_unavailable" in reasons_text.lower():
                exc_type = ExceptionType.VERIFICATION_UNAVAILABLE.value
            elif any(k in field_results for k in ("aggregateMarks", "cgpa", "ugDegree", "university", "passingYear")) or "academic" in reasons_text.lower() or "marks" in reasons_text.lower() or "cgpa" in reasons_text.lower():
                exc_type = ExceptionType.ACADEMIC_MISMATCH.value
            else:
                exc_type = ExceptionType.ACADEMIC_MISMATCH.value

            res = create_exception(
                db=db,
                application_id=application_id,
                exception_type=exc_type,
                description=f"Validation conflict in {doc_type}: {reasons_text}",
                source="DOCUMENT_VERIFICATION",
                metadata={"documentId": doc_id, "documentType": doc_type, "reasons": reasons},
            )
            if res:
                created_or_found.append(res)

    # 3. Eligibility Engine Conflicts
    eval_rec = db["eligibility_evaluations"].find_one({"applicationId": application_id}, sort=[("evaluatedAt", -1)])
    if eval_rec and eval_rec.get("status") in ("INELIGIBLE", "NEEDS_REVIEW"):
        summary = eval_rec.get("summary") or "Academic admission criteria not met or requires review"
        res = create_exception(
            db=db,
            application_id=application_id,
            exception_type=ExceptionType.ELIGIBILITY_CONFLICT.value,
            description=f"Academic eligibility evaluation requires administrative review: {summary}",
            source="ELIGIBILITY_ENGINE",
            metadata={"eligibilityStatus": eval_rec.get("status"), "summary": summary},
        )
        if res:
            created_or_found.append(res)

    return created_or_found

