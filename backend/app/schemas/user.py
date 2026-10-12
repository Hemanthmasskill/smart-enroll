from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


class UserCreate(BaseModel):
    fullName: str
    email: EmailStr
    mobile: str
    dob: str
    password: str

    model_config = ConfigDict(extra="ignore")

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class UserLogin(BaseModel):
    email: EmailStr
    password: str
    role: str

    model_config = ConfigDict(extra="ignore")

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class AuthResponse(BaseModel):
    role: str
    name: str
    email: EmailStr
    applicantId: str | None = None
    token: str
