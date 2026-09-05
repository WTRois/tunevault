import os

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
VALID_LOG_FORMATS = ("json", "pretty")


class Settings(BaseSettings):
    PROJECT_NAME: str = "TuneVault"
    VERSION: str = "2.0.0"
    API_V1_STR: str = "/api"

    # Path configurations (blueprint §38)
    DATABASE_URL: str = "sqlite:///./data/tunevault.db"
    STORAGE_DIR: str = "./storage"
    COVERS_DIR: str = "./storage/covers"
    DOWNLOADS_DIR: str = "./storage/downloads"
    MUSIC_DIR: str = "/music"
    IMPORT_DIR: str = "/imports"

    # Security / CORS (§27.3) — env accepts a comma-separated string or a JSON list.
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
    ]

    # External providers (blueprint §25/§26)
    PROVIDER_CONTACT_EMAIL: str | None = None  # MusicBrainz User-Agent contact
    MUSICBRAINZ_BASE_URL: str = "https://musicbrainz.org/ws/2"
    MUSICBRAINZ_USER_AGENT: str | None = None  # full UA override; else built from PROJECT_NAME/VERSION
    ACOUSTID_API_KEY: str = ""  # empty → fingerprint identification disabled

    # Identification decision thresholds (§8.4) — wired into scoring constants.
    IDENTIFICATION_AUTO_APPLY_THRESHOLD: float = 95.0
    IDENTIFICATION_REVIEW_THRESHOLD: float = 85.0
    IDENTIFICATION_REJECT_THRESHOLD: float = 70.0

    # Job queue (§23) — poll interval drives the worker loop; concurrency is
    # reserved for scaling worker replicas (§30 scale: worker).
    MAX_WORKER_CONCURRENCY: int = 2
    JOB_POLL_INTERVAL_MS: int = 500

    # Observability (§36) — LOG_FORMAT=json emits one JSON object per line.
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    # Release matching preferences (blueprint §10, TV2-018)
    RELEASE_PREFERENCE: str = "prefer_original"
    RELEASE_PREFERENCE_COUNTRY: str = ""
    RELEASE_PREFERENCE_LABEL: str = ""

    # Organization safety (blueprint §15/§16)
    ORGANIZE_DRY_RUN: bool = True  # apply engine refuses FS writes while true
    CREATE_BACKUPS: bool = True  # false disables undo artifacts (§16 copy-first)

    # Organization templates (blueprint §17, TV2-025)
    ORGANIZATION_TEMPLATE: str = "{album_artist}/[{year}] {album}/{track:02} - {title}.{ext}"
    ORGANIZATION_MULTI_DISC_TEMPLATE: str = (
        "{album_artist}/[{year}] {album}/CD{disc}/{track:02} - {title}.{ext}"
    )

    # FFmpeg/FFprobe (blueprint §32, TV2-028) — explicit binary paths
    FFMPEG_PATH: str = "ffmpeg"
    FFPROBE_PATH: str = "ffprobe"
    FFMPEG_TIMEOUT_SECONDS: int = 300

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_cors_origins(cls, value):
        """Compose (§30) sets a plain string like ``http://a,http://b`` —
        pydantic-settings would try to parse it as JSON. Split commas instead."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("LOG_LEVEL")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        upper = value.upper()
        if upper not in VALID_LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of: {', '.join(VALID_LOG_LEVELS)}")
        return upper

    @field_validator("LOG_FORMAT")
    @classmethod
    def _validate_log_format(cls, value: str) -> str:
        if value not in VALID_LOG_FORMATS:
            raise ValueError(f"LOG_FORMAT must be one of: {', '.join(VALID_LOG_FORMATS)}")
        return value

    @model_validator(mode="after")
    def _validate_thresholds(self) -> "Settings":
        """§8.4 ordering: auto-apply is the strictest band, reject the loosest."""
        if not (
            self.IDENTIFICATION_AUTO_APPLY_THRESHOLD
            >= self.IDENTIFICATION_REVIEW_THRESHOLD
            >= self.IDENTIFICATION_REJECT_THRESHOLD
        ):
            raise ValueError(
                "Identification thresholds must satisfy "
                "AUTO_APPLY >= REVIEW >= REJECT (§8.4)"
            )
        return self

    @property
    def resolved_covers_dir(self) -> str:
        if self.COVERS_DIR.startswith("/app") and not os.access("/app", os.W_OK):
            return "./storage/covers"
        return self.COVERS_DIR

    @property
    def resolved_downloads_dir(self) -> str:
        if self.DOWNLOADS_DIR.startswith("/app") and not os.access("/app", os.W_OK):
            return "./storage/downloads"
        return self.DOWNLOADS_DIR

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def validate_startup() -> None:
    """Fail fast when required config (§38) is missing (TV2-038).

    Defaults cover the common case; an explicit empty value in the
    environment is an operator error the process must refuse to boot on.
    """
    missing = [
        name
        for name in ("DATABASE_URL", "MUSIC_DIR", "STORAGE_DIR", "COVERS_DIR")
        if not getattr(settings, name)
    ]
    if not settings.CORS_ORIGINS:
        missing.append("CORS_ORIGINS")
    if missing:
        raise RuntimeError(f"Missing required configuration: {', '.join(missing)}")


settings = Settings()