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
    Generate next application ID following the project convention:
    SE<current_year><4-digit sequential>, e.g., SE20260001.
    """
    current_year = datetime.now(timezone.utc).year
    # Preserve 2026 academic year convention if before or in 2026
    year_str = str(max(current_year, 2026))
    prefix = f"SE{year_str}"

    pattern = f"^{prefix}\\d{{4}}$"
    highest_doc = db["applications"].find_one(
        {"applicationId": {"$regex": pattern}},
        sort=[("applicationId", -1)],
    )

    if highest_doc and "applicationId" in highest_doc:
        try:
            seq = int(highest_doc["applicationId"][len(prefix) :])
            next_seq = seq + 1
        except (ValueError, IndexError):
            next_seq = 1
    else:
        next_seq = 1

    return f"{prefix}{next_seq:04d}"


def create_application(db: Database, current_user: dict, app_in: ApplicationCreate) -> dict:
    """
    Create a new application in DRAFT state for the authenticated applicant.
    Enforces that an applicant may have only one application.
    Persists only authoritative Increment 11 application-domain data.
    Server controls: applicationId, userId, applicantId, status, createdAt, updatedAt, submittedAt.
    """
    user_id = str(current_user["_id"])
    applicant_id = current_user.get("applicant_id")

    query = {"$or": [{"userId": user_id}]}
    if applicant_id:
        query["$or"].append({"applicantId": applicant_id})

    existing = db["applications"].find_one(query)
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
    applicant_id = current_user.get("applicant_id")

    query = {"$or": [{"userId": user_id}]}
    if applicant_id:
        query["$or"].append({"applicantId": applicant_id})

    app = db["applications"].find_one(query, {"_id": 0})
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No application found for current applicant",
        )
    return app


def get_application_by_id(db: Database, current_user: dict, application_id: str) -> dict:
    """
    Retrieve an application by applicationId or applicantId.
    Admin can retrieve any application.
    Applicant can retrieve ONLY their own application.
    """
    app = db["applications"].find_one(
        {"$or": [{"applicationId": application_id}, {"applicantId": application_id}]},
        {"_id": 0},
    )
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )

    user_role = current_user.get("role")
    if user_role == "admin":
        return app

    if user_role == "applicant":
        user_id = str(current_user["_id"])
        applicant_id = current_user.get("applicant_id")
        app_user_id = app.get("userId")
        app_applicant_id = app.get("applicantId")

        if app_user_id != user_id and app_applicant_id != applicant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this application",
            )
        return app

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Operation not permitted for this role",
    )


def update_application(
    db: Database,
    current_user: dict,
    application_id: str,
    app_update: ApplicationUpdate,
) -> dict:
    """
    Update an existing application in DRAFT status.
    Applicant can update ONLY their own application while it is in DRAFT.
    Server-managed fields cannot be updated.
    """
    app = db["applications"].find_one(
        {"$or": [{"applicationId": application_id}, {"applicantId": application_id}]}
    )
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )

    user_id = str(current_user["_id"])
    applicant_id = current_user.get("applicant_id")
    app_user_id = app.get("userId")
    app_applicant_id = app.get("applicantId")

    if app_user_id != user_id and app_applicant_id != applicant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this application",
        )

    if app.get("status") != "DRAFT":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot edit an application that has already been submitted",
        )

    updates = app_update.model_dump(exclude_unset=True)
    # Strip any protected fields that may have bypassed client validation
    for field in PROTECTED_FIELDS:
        updates.pop(field, None)

    updates["updatedAt"] = datetime.now(timezone.utc).isoformat()

    updated = db["applications"].find_one_and_update(
        {"_id": app["_id"]},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    return updated


def submit_application(db: Database, current_user: dict, application_id: str) -> dict:
    """
    Submit a draft application.
    Enforces:
    - Ownership (applicant owns this application)
    - State is DRAFT
    - Completeness (all required personal, contact, academic fields are present)
    - Valid programme selection
    Transitions status to SUBMITTED and sets submittedAt.
    """
    app = db["applications"].find_one(
        {"$or": [{"applicationId": application_id}, {"applicantId": application_id}]}
    )
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )

    user_id = str(current_user["_id"])
    applicant_id = current_user.get("applicant_id")
    app_user_id = app.get("userId")
    app_applicant_id = app.get("applicantId")

    if app_user_id != user_id and app_applicant_id != applicant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to submit this application",
        )

    current_status = app.get("status")
    if current_status == "SUBMITTED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Application is already submitted",
        )
    if current_status != "DRAFT":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
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

    updated = db["applications"].find_one_and_update(
        {"_id": app["_id"]},
        {"$set": submission_updates},
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    return updated


def list_applications(db: Database) -> list[dict]:
    """
    List all applications for admin view. Returns authoritative application-domain summary.
    """
    cursor = db["applications"].find({}, {"_id": 0}).sort("createdAt", -1)
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
        {"$or": [{"applicantId": applicant_id}, {"applicationId": applicant_id}]},
        {"_id": 0},
    )


def seed_application_record(db: Database, application_data: dict):
    doc = application_data.copy()
    app_id = doc.get("applicationId")
    if app_id:
        db["applications"].delete_many({"applicationId": app_id})
    db["applications"].insert_one(doc)
    doc.pop("_id", None)
    return doc
