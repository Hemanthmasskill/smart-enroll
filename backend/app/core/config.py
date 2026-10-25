from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Smart Enroll Backend"
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