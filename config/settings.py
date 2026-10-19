"""Central application configuration.

Values come from environment variables (prefix ``CAREERMATCH_``) or a local
``.env`` file. Secrets must never be hardcoded here.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


class ScoringWeights(BaseModel):
    """Match-score component weights, expressed in percent (must sum to 100)."""

    ats: float = Field(20, ge=0)
    required_skills: float = Field(25, ge=0)
    experience: float = Field(20, ge=0)
    responsibilities: float = Field(15, ge=0)
    education: float = Field(10, ge=0)
    keywords: float = Field(10, ge=0)

    @model_validator(mode="after")
    def _sum_to_100(self) -> "ScoringWeights":
        total = sum(self.as_dict().values())
        if abs(total - 100) > 1e-6:
            raise ValueError(f"Scoring weights must sum to 100 (got {total:g}).")
        return self

    def as_dict(self) -> dict[str, float]:
        return self.model_dump()


class RecommendationThresholds(BaseModel):
    """Score boundaries for recommendation labels (prioritisation guidance only)."""

    apply: float = Field(80, ge=0, le=100)
    improve: float = Field(70, ge=0, le=100)

    @model_validator(mode="after")
    def _ordered(self) -> "RecommendationThresholds":
        if self.improve > self.apply:
            raise ValueError("The 'improve' threshold cannot exceed the 'apply' threshold.")
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CAREERMATCH_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "CareerMatch AI"
    database_url: str = f"sqlite:///{(DATA_DIR / 'careermatch.db').as_posix()}"
    max_upload_mb: float = Field(5, gt=0, le=50)

    threshold_apply: float = 80
    threshold_improve: float = 70

    weight_ats: float = 20
    weight_required_skills: float = 25
    weight_experience: float = 20
    weight_responsibilities: float = 15
    weight_education: float = 10
    weight_keywords: float = 10

    # Job sources
    offline_mode: bool = False  # when true, no external requests are made at all
    http_timeout_s: float = Field(15, gt=0, le=60)
    remotive_enabled: bool = True
    # Remotive asks for at most ~4 requests per day; these bounds keep configuration within its terms.
    remotive_daily_limit: int = Field(4, ge=1, le=4)
    remotive_cache_hours: float = Field(6, ge=6, le=48)
    himalayas_enabled: bool = True
    jobicy_enabled: bool = True
    remoteok_enabled: bool = True
    adzuna_enabled: bool = True
    adzuna_app_id: str | None = None
    adzuna_app_key: SecretStr | None = None
    adzuna_default_country: str | None = Field(None, pattern=r"^[a-z]{2}$")
    adzuna_daily_limit: int = Field(250, ge=1, le=250)

    # --- Backend API (accounts, used by the browser extension) -------------
    api_database_url: str = f"sqlite:///{(DATA_DIR / 'careermatch_api.db').as_posix()}"
    api_host: str = "127.0.0.1"  # loopback only unless you deliberately change it (see SECURITY.md)
    api_port: int = Field(8600, ge=1024, le=65535)
    api_token_days: int = Field(30, ge=1, le=365)
    api_max_failed_logins: int = Field(5, ge=3, le=20)
    api_lockout_minutes: int = Field(15, ge=1, le=1440)
    # Extra browser origins allowed to call the API (comma-separated), e.g. a web front end.
    api_cors_origins: str = ""

    @property
    def api_cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    @property
    def scoring_weights(self) -> ScoringWeights:
        return ScoringWeights(
            ats=self.weight_ats,
            required_skills=self.weight_required_skills,
            experience=self.weight_experience,
            responsibilities=self.weight_responsibilities,
            education=self.weight_education,
            keywords=self.weight_keywords,
        )

    @property
    def thresholds(self) -> RecommendationThresholds:
        return RecommendationThresholds(apply=self.threshold_apply, improve=self.threshold_improve)

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    @model_validator(mode="after")
    def _validate_groups(self) -> "Settings":
        # Fail fast on invalid weight/threshold configuration.
        _ = self.scoring_weights
        _ = self.thresholds
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
