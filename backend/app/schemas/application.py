import re
from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

VALID_PROGRAMMES = {"mca", "mba", "msc-cs", "mtech-cs"}
VALID_GENDERS = {"female", "male", "other", "prefer not to say"}


def validate_programme_value(v: str | None) -> str | None:
    if v is not None:
        clean = v.strip().lower()
        if clean not in VALID_PROGRAMMES:
            raise ValueError(
                f"Unsupported programme '{v}'. Supported programmes: {', '.join(sorted(VALID_PROGRAMMES))}"
            )
        return clean
    return v


def validate_mobile_value(v: str | None) -> str | None:
    if v is not None and v != "":
        clean = re.sub(r"[\s\-]", "", str(v))
        if not re.match(r"^\d{10}$", clean):
            raise ValueError("Mobile number must be a 10-digit number")
        return clean
    return v


def validate_pin_value(v: str | None) -> str | None:
    if v is not None and v != "":
        clean = str(v).strip()
        if not re.match(r"^\d{6}$", clean):
            raise ValueError("PIN code must be a 6-digit number")
        return clean
    return v


def validate_percentage_value(v: float | int | str | None) -> str | None:
    if v is not None and v != "":
        s_val = str(v).strip().rstrip("%").strip()
        try:
            val = float(s_val)
        except ValueError:
            raise ValueError("Percentage must be a valid number")
        if val < 0.0 or val > 100.0:
            raise ValueError("Percentage must be between 0 and 100")
        return str(v).strip()
    return v


def validate_cgpa_value(v: float | int | str | None) -> str | None:
    if v is not None and v != "":
        s_val = str(v).strip()
        if "/" in s_val:
            s_val = s_val.split("/")[0].strip()
        try:
            val = float(s_val)
        except ValueError:
            raise ValueError("CGPA must be a valid number")
        if val < 0.0 or val > 10.0:
            raise ValueError("CGPA must be between 0.0 and 10.0")
        return str(v).strip()
    return v


def validate_graduation_year_value(v: int | str | None) -> int | None:
    if v is not None and v != "":
        try:
            val = int(str(v).strip())
        except (ValueError, TypeError):
            raise ValueError("Graduation year must be a valid 4-digit year")
        if val < 1970 or val > 2035:
            raise ValueError("Graduation year must be between 1970 and 2035")
        return val
    return v


def validate_gender_value(v: str | None) -> str | None:
    if v is not None and v != "":
        clean = v.strip().lower()
        if clean not in VALID_GENDERS:
            raise ValueError("Invalid gender. Allowed values: Female, Male, Other, Prefer not to say")
        for orig in ["Female", "Male", "Other", "Prefer not to say"]:
            if orig.lower() == clean:
                return orig
    return v


class ApplicationBase(BaseModel):
    programmeId: str
    applicationMode: str = "Regular"
    fullName: str | None = None
    dob: str | None = None
    gender: str | None = None
    nationality: str | None = None
    email: EmailStr | None = None
    mobile: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    pinCode: str | None = None
    tenthBoard: str | None = None
    tenthPercentage: float | int | str | None = None
    twelfthBoard: str | None = None
    twelfthPercentage: float | int | str | None = None
    ugDegree: str | None = None
    university: str | None = None
    graduationYear: int | str | None = None
    cgpa: float | int | str | None = None

    model_config = ConfigDict(extra="ignore")


class ApplicationCreate(ApplicationBase):
    @field_validator("programmeId", mode="after")
    @classmethod
    def check_programme(cls, v: str) -> str:
        res = validate_programme_value(v)
        if not res:
            raise ValueError("programmeId is required")
        return res

    @field_validator("mobile", mode="after")
    @classmethod
    def check_mobile(cls, v: str | None) -> str | None:
        return validate_mobile_value(v)

    @field_validator("pinCode", mode="after")
    @classmethod
    def check_pin(cls, v: str | None) -> str | None:
        return validate_pin_value(v)

    @field_validator("tenthPercentage", mode="after")
    @classmethod
    def check_tenth_pct(cls, v: float | int | str | None) -> str | None:
        return validate_percentage_value(v)

    @field_validator("twelfthPercentage", mode="after")
    @classmethod
    def check_twelfth_pct(cls, v: float | int | str | None) -> str | None:
        return validate_percentage_value(v)

    @field_validator("cgpa", mode="after")
    @classmethod
    def check_cgpa(cls, v: float | int | str | None) -> str | None:
        return validate_cgpa_value(v)

    @field_validator("graduationYear", mode="after")
    @classmethod
    def check_grad_year(cls, v: int | str | None) -> int | None:
        return validate_graduation_year_value(v)

    @field_validator("gender", mode="after")
    @classmethod
    def check_gender(cls, v: str | None) -> str | None:
        return validate_gender_value(v)


class ApplicationUpdate(BaseModel):
    programmeId: str | None = None
    applicationMode: str | None = None
    fullName: str | None = None
    dob: str | None = None
    gender: str | None = None
    nationality: str | None = None
    email: EmailStr | None = None
    mobile: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    pinCode: str | None = None
    tenthBoard: str | None = None
    tenthPercentage: float | int | str | None = None
    twelfthBoard: str | None = None
    twelfthPercentage: float | int | str | None = None
    ugDegree: str | None = None
    university: str | None = None
    graduationYear: int | str | None = None
    cgpa: float | int | str | None = None

    model_config = ConfigDict(extra="ignore")

    @field_validator("programmeId", mode="after")
    @classmethod
    def check_programme(cls, v: str | None) -> str | None:
        return validate_programme_value(v)

    @field_validator("mobile", mode="after")
    @classmethod
    def check_mobile(cls, v: str | None) -> str | None:
        return validate_mobile_value(v)

    @field_validator("pinCode", mode="after")
    @classmethod
    def check_pin(cls, v: str | None) -> str | None:
        return validate_pin_value(v)

    @field_validator("tenthPercentage", mode="after")
    @classmethod
    def check_tenth_pct(cls, v: float | int | str | None) -> str | None:
        return validate_percentage_value(v)

    @field_validator("twelfthPercentage", mode="after")
    @classmethod
    def check_twelfth_pct(cls, v: float | int | str | None) -> str | None:
        return validate_percentage_value(v)

    @field_validator("cgpa", mode="after")
    @classmethod
    def check_cgpa(cls, v: float | int | str | None) -> str | None:
        return validate_cgpa_value(v)

    @field_validator("graduationYear", mode="after")
    @classmethod
    def check_grad_year(cls, v: int | str | None) -> int | None:
        return validate_graduation_year_value(v)

    @field_validator("gender", mode="after")
    @classmethod
    def check_gender(cls, v: str | None) -> str | None:
        return validate_gender_value(v)


class ApplicationResponse(BaseModel):
    applicationId: str
    applicantId: str
    userId: str | None = None
    programmeId: str
    applicationMode: str = "Regular"
    fullName: str | None = None
    dob: str | None = None
    gender: str | None = None
    nationality: str | None = None
    email: str | None = None
    mobile: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    pinCode: str | None = None
    tenthBoard: str | None = None
    tenthPercentage: float | int | str | None = None
    twelfthBoard: str | None = None
    twelfthPercentage: float | int | str | None = None
    ugDegree: str | None = None
    university: str | None = None
    graduationYear: int | str | None = None
    cgpa: float | int | str | None = None
    status: str
    submittedAt: str | None = None
    createdAt: str | None = None
    updatedAt: str | None = None

    model_config = ConfigDict(extra="ignore")


class ApplicationSummaryResponse(BaseModel):
    applicationId: str
    applicantId: str
    applicantName: str | None = None
    fullName: str | None = None
    email: str | None = None
    programmeId: str
    status: str
    submittedAt: str | None = None
    createdAt: str | None = None

    model_config = ConfigDict(extra="ignore")
