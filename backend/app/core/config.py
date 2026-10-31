from pathlib import Path
from pydantic import field_validator
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

    @field_validator("TRUSTED_PROXIES", mode="before")
    @classmethod
    def parse_trusted_proxies(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [ip.strip() for ip in v.split(",") if ip.strip()]
        if isinstance(v, (list, tuple, set)):
            return [str(ip).strip() for ip in v if str(ip).strip()]
        return ["127.0.0.1", "::1"]

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
