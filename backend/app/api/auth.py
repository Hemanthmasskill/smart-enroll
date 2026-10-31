from fastapi import APIRouter, Depends, Request, status
from app.core.rate_limit import enforce_rate_limit
from pymongo.database import Database

from app.core.database import get_db
from app.api.deps import get_current_user
from app.core.security import create_access_token
from app.schemas.user import AuthResponse, UserCreate, UserLogin
from app.services.user import (
    ROLE_BACKEND_TO_FRONTEND,
    authenticate_user,
    create_user,
)

router = APIRouter()


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(user_in: UserCreate, request: Request, db: Database = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    enforce_rate_limit(f"register:{ip}", max_requests=3, window_seconds=60, action_description="registration attempts")
    """
    Public registration endpoint.
    Creates a new applicant, generates an access token, and returns
    a flat session response conforming to the frozen frontend contract.
    """
    user = create_user(db, user_in)
    token = create_access_token(
        subject=str(user["_id"]),
        role=user["role"],
        token_version=user.get("tokenVersion", 1),
    )

    frontend_role = ROLE_BACKEND_TO_FRONTEND.get(user["role"], "user")

    return AuthResponse(
        role=frontend_role,
        name=user["full_name"],
        email=user["email"],
        applicantId=user.get("applicant_id"),
        token=token,
    )


@router.post(
    "/login",
    response_model=AuthResponse,
    status_code=status.HTTP_200_OK,
)
def login(login_in: UserLogin, request: Request, db: Database = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    normalized_email = login_in.email.strip().lower()
    enforce_rate_limit(f"login:{ip}:{normalized_email}", max_requests=5, window_seconds=60, action_description="login attempts")
    """
    User/Admin login endpoint.
    Authenticates against credentials and requested role, generates an
    access token, and returns a flat session response.
    """
    user = authenticate_user(db, login_in.email, login_in.password, login_in.role)
    token = create_access_token(
        subject=str(user["_id"]),
        role=user["role"],
        token_version=user.get("tokenVersion", 1),
    )

    frontend_role = ROLE_BACKEND_TO_FRONTEND.get(user["role"], login_in.role)

    return AuthResponse(
        role=frontend_role,
        name=user["full_name"],
        email=user["email"],
        applicantId=user.get("applicant_id"),
        token=token,
    )


@router.get(
    "/me",
    response_model=dict,
    tags=["Authentication"],
)
def get_current_authenticated_user(current_user: dict = Depends(get_current_user)):
    """
    Retrieve current authenticated user context.
    """
    user_copy = current_user.copy()
    user_copy["_id"] = str(user_copy["_id"])
    return user_copy
