import uuid
from datetime import datetime, timezone
from fastapi import HTTPException, status
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.core.security import get_password_hash, verify_password
from app.schemas.user import UserCreate

ROLE_FRONTEND_TO_BACKEND = {
    "user": "applicant",
    "admin": "admin",
}

ROLE_BACKEND_TO_FRONTEND = {
    "applicant": "user",
    "admin": "admin",
}


def create_user(db: Database, user_in: UserCreate) -> dict:
    """
    Register a new applicant.
    Normalizes email, hashes password, generates applicant_id,
    forces role = 'applicant', and inserts into the users collection.
    Raises HTTP 409 Conflict on duplicate email.
    """
    normalized_email = user_in.email.strip().lower()
    hashed_password = get_password_hash(user_in.password)
    applicant_id = f"APL-{uuid.uuid4().hex[:6].upper()}"

    user_doc = {
        "email": normalized_email,
        "hashed_password": hashed_password,
        "full_name": user_in.fullName,
        "mobile": user_in.mobile,
        "dob": user_in.dob,
        "role": "applicant",  # Client-provided role can NEVER control registration
        "applicant_id": applicant_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        result = db["users"].insert_one(user_doc)
        user_doc["_id"] = result.inserted_id
        return user_doc
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )


def authenticate_user(
    db: Database,
    email: str,
    password: str,
    client_role: str,
) -> dict:
    """
    Authenticate an existing user.
    Normalizes email, looks up user, verifies password, and validates
    that the requested frontend role matches the stored backend role.
    Raises HTTP 401 Unauthorized on nonexistent user, password mismatch,
    or role mismatch.
    """
    normalized_email = email.strip().lower()
    target_backend_role = ROLE_FRONTEND_TO_BACKEND.get(client_role)

    if not target_backend_role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email, password, or role",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db["users"].find_one({"email": normalized_email})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email, password, or role",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(password, user.get("hashed_password", "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email, password, or role",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.get("role") != target_backend_role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email, password, or role",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user
