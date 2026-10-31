from app.api.deps import assert_owner
from datetime import datetime, timezone
from fastapi import HTTPException, status
from pymongo import ReturnDocument
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.schemas.application import (
    VALID_PROGRAMMES,
    ApplicationCreate,
    ApplicationUpdate,
)

PROTECTED_FIELDS = {
    "_id",
    "applicationId",
    "userId",
    "applicantId",
    "status",
    "createdAt",
    "updatedAt",
    "submittedAt",
}

SUBMISSION_REQUIRED_FIELDS = [
    "fullName",
    "dob",
    "gender",
    "nationality",
    "email",
    "mobile",
    "address",
    "city",
    "state",
    "pinCode",
    "tenthBoard",
    "tenthPercentage",
    "twelfthBoard",
    "twelfthPercentage",
    "ugDegree",
    "university",
    "graduationYear",
    "cgpa",
    "programmeId",
]


def generate_application_id(db: Database) -> str:
    """
    Generate next application ID atomically using the 'counters' collection.
    Format: SE<current_year><5-digit sequential>, e.g., SE202600001.
    Capacity: 99,999 applications per year. Raises RuntimeError if exceeded.
    """
    current_year = datetime.now(timezone.utc).year
    year_str = str(max(current_year, 2026))
    counter_id = f"applications_{year_str}"

    counter_doc = db["counters"].find_one_and_update(
        {"_id": counter_id},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )

    seq = counter_doc["seq"]
    if seq > 99999:
        raise RuntimeError(
            f"Application ID sequence limit exceeded for academic year {year_str} (capacity: 99,999)."
        )

    return f"SE{year_str}{seq:05d}"


def create_application(db: Database, current_user: dict, app_in: ApplicationCreate) -> dict:
    """
    Create a new application in DRAFT state for the authenticated applicant.
    Enforces that an applicant may have only one application.
    Persists only authoritative Increment 11 application-domain data.
    Server controls: applicationId, userId, applicantId, status, createdAt, updatedAt, submittedAt.
    """
    user_id = str(current_user["_id"])
    applicant_id = current_user.get("applicant_id")

    existing = db["applications"].find_one({"userId": user_id})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Application already exists for this applicant",
        )

    application_id = generate_application_id(db)
    now = datetime.now(timezone.utc).isoformat()

    dumped = app_in.model_dump(exclude_unset=True)
    # Ensure server-managed fields are not taken from client payload
    for field in PROTECTED_FIELDS:
        dumped.pop(field, None)

    # Populate defaults from user account if not provided in form
    full_name = dumped.get("fullName") or current_user.get("full_name")
    email = dumped.get("email") or current_user.get("email")
    mobile = dumped.get("mobile") or current_user.get("mobile")
    dob = dumped.get("dob") or current_user.get("dob")

    doc = {
        **dumped,
        "applicationId": application_id,
        "userId": user_id,
        "applicantId": applicant_id,
        "fullName": full_name,
        "email": email,
        "mobile": mobile,
        "dob": dob,
        "status": "DRAFT",
        "submittedAt": None,
        "createdAt": now,
        "updatedAt": now,
    }

    try:
        result = db["applications"].insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Application already exists for this applicant",
        )


def get_application_for_user(db: Database, current_user: dict) -> dict:
    """
    Retrieve the application belonging to the currently authenticated applicant.
    """
    user_id = str(current_user["_id"])
    app = db["applications"].find_one({"userId": user_id}, {"_id": 0})
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No application found for current applicant",
        )
    return app


def get_application_by_id(db: Database, current_user: dict, application_id: str) -> dict:
    """
    Retrieve an application by applicationId only.
    Admin can retrieve any application.
    Applicant can retrieve ONLY their own application.
    """
    app = db["applications"].find_one(
        {"applicationId": application_id},
        {"_id": 0},
    )
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )

    assert_owner(app, current_user)
    return app


def update_application(
    db: Database,
    current_user: dict,
    application_id: str,
    app_update: ApplicationUpdate,
) -> dict:
    """
    Update an existing application in DRAFT status atomically.
    Applicant can update ONLY their own application while it is in DRAFT.
    Server-managed fields cannot be updated.
    """
    updates = app_update.model_dump(exclude_unset=True)
    # Strip any protected fields that may have bypassed client validation
    for field in PROTECTED_FIELDS:
        updates.pop(field, None)

    updates["updatedAt"] = datetime.now(timezone.utc).isoformat()

    user_id = str(current_user.get("_id") or current_user.get("id"))
    is_admin = current_user.get("role") == "admin"

    filter_query = {
        "applicationId": application_id,
        "status": "DRAFT",
    }
    if not is_admin:
        filter_query["userId"] = user_id

    updated = db["applications"].find_one_and_update(
        filter_query,
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )

    if not updated:
        existing = db["applications"].find_one({"applicationId": application_id})
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application not found",
            )
        if not is_admin and existing.get("userId") != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: access denied. Not authorized.",
            )
        curr_status = existing.get("status")
        if curr_status != "DRAFT":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot edit an application that has already been submitted (status: {curr_status})",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Concurrent modification conflict. Please retry.",
        )

    return updated


def submit_application(db: Database, current_user: dict, application_id: str) -> dict:
    """
    Submit a draft application atomically.
    Enforces:
    - Ownership (applicant owns this application)
    - State is DRAFT
    - Completeness (all required personal, contact, academic fields are present)
    - Valid programme selection
    Atomic find_one_and_update ensures exactly one transition to SUBMITTED.
    """
    app = db["applications"].find_one({"applicationId": application_id})
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )

    assert_owner(app, current_user)

    current_status = app.get("status")
    if current_status == "SUBMITTED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Application is already submitted",
        )
    if current_status != "DRAFT":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot submit application in status {current_status}",
        )

    # Basic completeness validation on submission
    missing = []
    for field in SUBMISSION_REQUIRED_FIELDS:
        val = app.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            missing.append(field)

    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Incomplete application: required field(s) missing: {', '.join(missing)}",
        )

    # Programme validation
    if app.get("programmeId") not in VALID_PROGRAMMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid programme selection: {app.get('programmeId')}",
        )

    now = datetime.now(timezone.utc).isoformat()
    submission_updates = {
        "status": "SUBMITTED",
        "submittedAt": now,
        "updatedAt": now,
    }

    user_id = str(current_user.get("_id") or current_user.get("id"))
    is_admin = current_user.get("role") == "admin"

    filter_query = {
        "applicationId": application_id,
        "status": "DRAFT",
    }
    if not is_admin:
        filter_query["userId"] = user_id

    updated = db["applications"].find_one_and_update(
        filter_query,
        {"$set": submission_updates},
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )

    if not updated:
        existing = db["applications"].find_one({"applicationId": application_id})
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application not found",
            )
        if not is_admin and existing.get("userId") != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: access denied. Not authorized.",
            )
        curr_status = existing.get("status")
        if curr_status == "SUBMITTED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Application is already submitted",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot submit application: current status is {curr_status}, expected DRAFT.",
        )

    return updated


def list_applications(
    db: Database,
    skip: int = 0,
    limit: int = 100,
) -> list[dict]:
    """
    List all applications for admin view with pagination support.
    Returns authoritative application-domain summary.
    """
    clamped_limit = min(100, max(1, limit))
    cursor = (
        db["applications"]
        .find({}, {"_id": 0})
        .sort("createdAt", -1)
        .skip(max(0, skip))
        .limit(clamped_limit)
    )
    results = []
    for doc in cursor:
        results.append(
            {
                "applicationId": doc.get("applicationId", ""),
                "applicantId": doc.get("applicantId", ""),
                "applicantName": doc.get("fullName") or doc.get("applicantName", "Applicant"),
                "fullName": doc.get("fullName"),
                "email": doc.get("email"),
                "programmeId": doc.get("programmeId", ""),
                "status": doc.get("status", "DRAFT"),
                "submittedAt": doc.get("submittedAt"),
                "createdAt": doc.get("createdAt"),
            }
        )
    return results


# Backward compatibility with Increment 9 seed helper
def get_application(db: Database, applicant_id: str):
    return db["applications"].find_one(
        {"applicationId": applicant_id},
        {"_id": 0},
    )


def seed_application_record(db: Database, application_data: dict):
    """
    Non-destructive seed operation: inserts mock application record only if absent.
    Never deletes existing application data.
    """
    doc = application_data.copy()
    app_id = doc.get("applicationId")
    if app_id:
        existing = db["applications"].find_one({"applicationId": app_id})
        if existing:
            existing.pop("_id", None)
            return existing
    db["applications"].insert_one(doc)
    doc.pop("_id", None)
    return doc
