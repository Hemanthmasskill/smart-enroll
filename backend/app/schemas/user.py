from datetime import datetime
import re
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

VALID_LOGIN_ROLES = {"user", "admin", "applicant"}


class UserCreate(BaseModel):
    fullName: str = Field(..., min_length=1, max_length=100)
    email: EmailStr = Field(..., max_length=254)
    mobile: str = Field(..., min_length=10, max_length=15)
    dob: str = Field(..., min_length=10, max_length=10)
    password: str = Field(..., min_length=10, max_length=128)

    model_config = ConfigDict(extra="ignore")

    @field_validator("fullName", mode="after")
    @classmethod
    def validate_full_name(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Full name cannot be blank")
        return clean

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("mobile", mode="after")
    @classmethod
    def validate_mobile(cls, v: str) -> str:
        clean = re.sub(r"[\s\-]", "", v)
        if not re.match(r"^\d{10}$", clean):
            raise ValueError("Mobile number must be a 10-digit number")
        return clean

    @field_validator("dob", mode="after")
    @classmethod
    def validate_dob(cls, v: str) -> str:
        clean = v.strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", clean):
            raise ValueError("Date of birth must be in YYYY-MM-DD format")
        try:
            datetime.strptime(clean, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Date of birth must be a valid calendar date")
        return clean


class UserLogin(BaseModel):
    email: EmailStr = Field(..., max_length=254)
    password: str = Field(..., min_length=1, max_length=128)
    role: str = Field(..., min_length=1, max_length=20)

    model_config = ConfigDict(extra="ignore")

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("role", mode="after")
    @classmethod
    def validate_role(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in VALID_LOGIN_ROLES:
            raise ValueError(
                f"Invalid role '{v}'. Must be one of: {', '.join(sorted(VALID_LOGIN_ROLES))}"
            )
        return clean


class AuthResponse(BaseModel):
    role: str
    name: str
    email: EmailStr
    applicantId: str | None = None
    token: str
