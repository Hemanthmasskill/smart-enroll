from datetime import datetime, timedelta, timezone
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
import jwt

from app.core.config import settings

import logging
import re
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

pwd_hasher = PasswordHasher()

# Pre-hashed dummy value for constant-time authentication against non-existent accounts
DUMMY_HASH = pwd_hasher.hash("dummy_constant_time_password_check")

COMMON_PASSWORDS = {
    "password",
    "password123",
    "password1234",
    "admin123",
    "admin12345",
    "1234567890",
    "qwerty1234",
    "Welcome@123",
    "Password@123",
    "AdminPass123",
}


def validate_password_strength(password: str) -> None:
    if password.lower() in {p.lower() for p in COMMON_PASSWORDS}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password is too common or easily guessable. Please choose a stronger password.",
        )
    """
    Enforce enterprise password complexity:
    - 10 to 128 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character
    - Reject common passwords
    """
    if len(password) < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 10 characters in length.",
        )
    if len(password) > 128:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must not exceed 128 characters in length.",
        )
    if not re.search(r"[A-Z]", password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one uppercase letter.",
        )
    if not re.search(r"[a-z]", password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one lowercase letter.",
        )
    if not re.search(r"[0-9]", password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one numerical digit.",
        )
    if not re.search(r'[!@#$%^&*(),.?":{}|<>\-_]', password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one special character.",
        )
    if password.lower() in {p.lower() for p in COMMON_PASSWORDS}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password is too common or easily guessable. Please choose a stronger password.",
        )


def validate_secret_key() -> None:
    """
    Verify SECRET_KEY length and reject insecure default credentials.
    """
    key = settings.SECRET_KEY
    if len(key) < 32:
        msg = f"Insecure SECRET_KEY: length must be at least 32 characters (currently {len(key)})."
        if settings.ENV == "production":
            raise RuntimeError(msg)
        else:
            logger.warning(msg)
    insecure_defaults = {
        "your-secure-random-secret-key-here",
        "secret",
        "changeme",
        "12345678901234567890123456789012",
    }
    if key in insecure_defaults:
        msg = "Insecure default SECRET_KEY detected in configuration."
        if settings.ENV == "production":
            raise RuntimeError(msg)
        else:
            logger.warning(msg)


def get_password_hash(password: str) -> str:
    """Hash a plaintext password using Argon2id."""
    return pwd_hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against an Argon2id hash."""
    try:
        return pwd_hasher.verify(hashed_password, plain_password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def create_access_token(
    subject: str,
    role: str,
    token_version: int = 1,
    expires_delta: timedelta | None = None,
) -> str:
    """
    Generate JWT access token using PyJWT with HS256 algorithm.
    Includes subject, role, exp, tokenVersion, iss, and aud claims.
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    payload = {
        "sub": str(subject),
        "role": str(role),
        "tokenVersion": int(token_version),
        "iss": "smart-enroll",
        "aud": "smart-enroll-api",
        "exp": expire,
    }

    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
