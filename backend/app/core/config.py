from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Smart Enroll Backend"
    API_V1_STR: str = "/api/v1"
    MONGODB_URI: str = "mongodb://localhost:27017"
    DATABASE_NAME: str = "smartenroll"
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()