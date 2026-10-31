from pathlib import Path
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Smart Enroll Backend"
    ENV: str = "development"
    ENABLE_DEV_SEED: bool = False
    API_V1_STR: str = "/api/v1"
    MONGODB_URI: str = "mongodb://localhost:27017"
    DATABASE_NAME: str = "smartenroll"
    TEST_DATABASE_NAME: str = "smartenroll_test"
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    STORAGE_DIR: str = "storage/documents"
    TESSERACT_CMD: str | None = None
    OCR_LANGUAGES: str = "eng+tam+hin"

    # LLM Settings (Increment 15, Task 15.3)
    LLM_PROVIDER: str = "disabled"
    LLM_API_KEY: str | None = None
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_API_BASE: str = "https://api.openai.com/v1"
    LLM_TIMEOUT_SECONDS: float = 15.0
    LLM_TEMPERATURE: float = 0.0
    LLM_FALLBACK_TO_DETERMINISTIC: bool = True
    LLM_ALLOW_LOCAL_ENDPOINTS: bool = False
    ORCHESTRATION_MAX_SECONDS: float = 120.0

    # API Hardening & Rate Limiting (Hardening Phase 4)
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    RATE_LIMIT_ENABLED: bool = True
    TRUSTED_PROXIES: list[str] = ["127.0.0.1", "::1"]
    MAX_CONCURRENT_OCR_WORKERS: int = 4

    # Data Retention & Upload Security (Hardening Requirement M5)
    # Retention period in days for abandoned draft applications and unlinked temporary files
    # Encryption-at-Rest Notice: STORAGE_DIR must be hosted on an encrypted volume (e.g., LUKS, BitLocker, or AWS EBS KMS).
    RETENTION_DAYS: int = 30
    UPLOAD_SCANNER: str = "noop"

    @field_validator("ENV")
    @classmethod
    def validate_env(cls, v: str) -> str:
        valid_envs = {"development", "staging", "production", "test"}
        normalized = v.strip().lower()
        if normalized not in valid_envs:
            raise ValueError(
                f"Invalid ENV '{v}'. Must be one of: {', '.join(sorted(valid_envs))}"
            )
        return normalized

    @field_validator("TRUSTED_PROXIES", mode="before")
    @classmethod
    def parse_trusted_proxies(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [ip.strip() for ip in v.split(",") if ip.strip()]
        if isinstance(v, (list, tuple, set)):
            return [str(ip).strip() for ip in v if str(ip).strip()]
        return ["127.0.0.1", "::1"]

    @model_validator(mode="after")
    def validate_production_safety(self) -> "Settings":
        env = self.ENV.lower()
        is_dev = env == "development"

        # Default-deny dev seed outside development
        if not is_dev and self.ENABLE_DEV_SEED:
            raise ValueError(
                f"ENABLE_DEV_SEED is strictly forbidden when ENV is '{self.ENV}'."
            )

        # Enforce strong SECRET_KEY outside development
        if not is_dev:
            key = self.SECRET_KEY.strip() if self.SECRET_KEY else ""
            insecure_keys = {
                "your-secret-key-change-in-production",
                "secret",
                "secretkey",
                "changeme",
                "default",
                "development",
                "admin",
                "password",
            }
            if len(key) < 32:
                raise ValueError(
                    f"SECRET_KEY must be at least 32 characters long when ENV is '{self.ENV}'."
                )
            if key.lower() in insecure_keys:
                raise ValueError(
                    f"Insecure placeholder SECRET_KEY is not allowed when ENV is '{self.ENV}'."
                )

        # Enforce upload scanner configuration safety
        scanner = (self.UPLOAD_SCANNER or "").strip().lower()
        valid_scanners = {"noop", "clamav"}
        if not scanner:
            raise ValueError(
                f"UPLOAD_SCANNER cannot be missing or empty. Valid options: {', '.join(sorted(valid_scanners))}."
            )
        if scanner not in valid_scanners:
            raise ValueError(
                f"Unrecognized UPLOAD_SCANNER '{self.UPLOAD_SCANNER}'. Valid options: {', '.join(sorted(valid_scanners))}."
            )
        if env in ("staging", "production") and scanner == "noop":
            raise ValueError(
                f"UPLOAD_SCANNER 'noop' is strictly forbidden when ENV is '{self.ENV}'. A real scanner (e.g. 'clamav') is required."
            )

        return self

    @property
    def storage_path(self) -> Path:
        p = Path(self.STORAGE_DIR)
        if not p.is_absolute():
            backend_root = Path(__file__).resolve().parent.parent.parent
            p = (backend_root / p).resolve()
        return p.resolve()

    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
