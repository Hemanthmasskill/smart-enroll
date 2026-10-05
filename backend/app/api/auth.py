from fastapi import APIRouter, Depends, status
from pymongo.database import Database

from app.core.database import get_db
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
def register(user_in: UserCreate, db: Database = Depends(get_db)):
    """
    Public registration endpoint.
    Creates a new applicant, generates an access token, and returns
    a flat session response conforming to the frozen frontend contract.
    """
    user = create_user(db, user_in)
    token = create_access_token(subject=str(user["_id"]), role=user["role"])

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
def login(login_in: UserLogin, db: Database = Depends(get_db)):
    """
    User/Admin login endpoint.
    Authenticates against credentials and requested role, generates an
    access token, and returns a flat session response.
    """
    user = authenticate_user(db, login_in.email, login_in.password, login_in.role)
    token = create_access_token(subject=str(user["_id"]), role=user["role"])

    frontend_role = ROLE_BACKEND_TO_FRONTEND.get(user["role"], login_in.role)

    return AuthResponse(
        role=frontend_role,
        name=user["full_name"],
        email=user["email"],
        applicantId=user.get("applicant_id"),
        token=token,
    )
