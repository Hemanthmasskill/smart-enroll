from datetime import datetime, timedelta, timezone
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
import jwt

from app.core.config import settings

pwd_hasher = PasswordHasher()


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
    expires_delta: timedelta | None = None,
) -> str:
    """
    Generate JWT access token using PyJWT with HS256 algorithm.
    Explicitly whitelists allowed claims: ONLY 'sub', 'role', and 'exp'.
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
        "exp": expire,
    }

    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
