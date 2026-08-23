"""
Typed application settings, read from environment variables.

See docs/SECURITY-REQUIREMENTS.md for the authoritative values of every
security-relevant default below (bcrypt cost, JWT TTLs, rate limits, risk
thresholds). Do not change these defaults without checking that doc first.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Required secrets / connection strings -----------------------------
    DATABASE_URL: str = "postgresql://saiv:saiv_password@localhost:5434/saiv"
    REDIS_URL: str = "redis://localhost:6380/0"
    SECRET_KEY: str = "dev-only-secret-change-me-32-characters-minimum"
    FACE_SERVICE_URL: str = "http://localhost:8001"

    # --- JWT (SECURITY-REQUIREMENTS.md: HS256, 1h access / 7d refresh) -----
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # --- Password hashing (bcrypt, cost >= 10) ------------------------------
    BCRYPT_ROUNDS: int = 12

    # --- Risk scoring defaults (overridable per course/session) ------------
    RISK_SCORE_THRESHOLD: float = 0.5
    LIVENESS_THRESHOLD: float = 0.6
    FACE_MATCH_THRESHOLD: float = 0.7
    DEFAULT_GEOFENCE_RADIUS_METERS: float = 100.0

    # --- Data retention ------------------------------------------------------
    PII_RETENTION_DAYS: int = 30

    # --- Rate limiting (Redis-based; see SECURITY-REQUIREMENTS.md) ---------
    RATE_LIMIT_LOGIN_PER_HOUR: int = 60
    RATE_LIMIT_API_PER_HOUR: int = 1000
    RATE_LIMIT_CHECKIN_PER_MINUTE: int = 10
    RATE_LIMIT_REGISTRATION_PER_HOUR: int = 10

    # --- CORS ----------------------------------------------------------------
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",  # Frontend
        "http://localhost:8501",  # Dashboard
    ]

    # --- Observability (optional) --------------------------------------------
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton — env vars are read once per process."""
    return Settings()
