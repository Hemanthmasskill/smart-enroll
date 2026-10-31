from bson import ObjectId
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from pymongo.database import Database

from app.core.config import settings
from app.core.database import get_db

security_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    db: Database = Depends(get_db),
) -> dict:
    """
    Validate the Bearer token and retrieve the corresponding user from the database.
    Rejects missing tokens, expired tokens, invalid signatures, malformed tokens,
    or tokens missing required claims (sub, role, exp) with HTTP 401 Unauthorized.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
        decode_kwargs = {"algorithms": ["HS256"]}
        if "aud" in unverified:
            decode_kwargs["audience"] = "smart-enroll-api"
        if "iss" in unverified:
            decode_kwargs["issuer"] = "smart-enroll"
        payload = jwt.decode(token, settings.SECRET_KEY, **decode_kwargs)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    sub: str | None = payload.get("sub")
    role: str | None = payload.get("role")
    exp = payload.get("exp")

    # Explicitly require sub, role, and exp
    if not sub or not role or exp is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token claims",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = ObjectId(sub)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID in token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db["users"].find_one({"_id": user_id}, {"hashed_password": 0})
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Token Version Revocation Check
    expected_version = user.get("tokenVersion", 1)
    token_version = payload.get("tokenVersion")
    if token_version is not None and token_version != expected_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked or invalidated.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


class RequireRole:
    """
    Reusable dependency to enforce internal backend role-based authorization.
    Example: Depends(RequireRole(["applicant"])) or Depends(RequireRole(["admin"]))
    Returns 403 Forbidden if the authenticated user's role is not allowed.
    """

    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, current_user: dict = Depends(get_current_user)) -> dict:
        user_role = current_user.get("role")
        if user_role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operation not permitted for this role",
            )
        return current_user

def assert_owner(app: dict, current_user: dict) -> None:
    """
    Enforce that current_user is either an admin or the strict userId owner of the application.
    Rejects any mismatch with HTTP 403 Forbidden.
    """
    if current_user.get("role") == "admin":
        return
    user_id = str(current_user.get("_id") or current_user.get("id"))
    if app.get("userId") != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: access denied. Not authorized.",
        )
