from datetime import datetime
from decimal import Decimal

from sqlmodel import Field, SQLModel

from backend.core.time import now_utc

SCAN_STATES = ("discovered", "extracted", "indexed", "error")


class File(SQLModel, table=True):
    """Physical file representation (blueprint §5.1)."""

    __tablename__ = "files"

    id: int | None = Field(default=None, primary_key=True)
    filepath: str = Field(unique=True, index=True)
    filename: str
    extension: str
    mime_type: str | None = Field(default=None)
    sha256: str = Field(index=True)
    file_size: int
    modified_at: datetime
    duration_ms: int | None = Field(default=None)
    codec: str | None = Field(default=None)
    container: str | None = Field(default=None)
    bitrate: int | None = Field(default=None)
    sample_rate: int | None = Field(default=None)
    bit_depth: int | None = Field(default=None)
    channels: int | None = Field(default=None)
    channel_layout: str | None = Field(default=None)
    scan_state: str = Field(default="discovered", index=True)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class FileRecording(SQLModel, table=True):
    """Mapping physical file → recording (blueprint §5.7)."""

    __tablename__ = "file_recordings"

    id: int | None = Field(default=None, primary_key=True)
    file_id: int = Field(foreign_key="files.id", unique=True, index=True)
    recording_id: int = Field(foreign_key="recordings.id", index=True)
    confidence: Decimal
    source: str
    matched_at: datetime = Field(default_factory=now_utc)


class FileRelease(SQLModel, table=True):
    """Mapping physical file → release track (blueprint §5.8)."""

    __tablename__ = "file_releases"

    id: int | None = Field(default=None, primary_key=True)
    file_id: int = Field(foreign_key="files.id", unique=True, index=True)
    release_id: int = Field(foreign_key="releases.id", index=True)
    release_track_id: int = Field(foreign_key="release_tracks.id", index=True)
    confidence: Decimal
    source: str
    matched_at: datetime = Field(default_factory=now_utc)


class Fingerprint(SQLModel, table=True):
    """Acoustic fingerprint per file (blueprint §5.9)."""

    __tablename__ = "fingerprints"

    id: int | None = Field(default=None, primary_key=True)
    file_id: int = Field(foreign_key="files.id", unique=True, index=True)
    provider: str
    fingerprint: str
    duration_ms: int
    fingerprint_version: str
    created_at: datetime = Field(default_factory=now_utc)


class AudioFeature(SQLModel, table=True):
    """Audiophile audio analysis per file (blueprint §5.11)."""

    __tablename__ = "audio_features"

    id: int | None = Field(default=None, primary_key=True)
    file_id: int = Field(foreign_key="files.id", unique=True, index=True)
    bpm: Decimal | None = Field(default=None)
    musical_key: str | None = Field(default=None)
    integrated_lufs: Decimal | None = Field(default=None)
    true_peak_db: Decimal | None = Field(default=None)
    replaygain_track_db: Decimal | None = Field(default=None)
    replaygain_album_db: Decimal | None = Field(default=None)
    dynamic_range: Decimal | None = Field(default=None)
    spectral_centroid: Decimal | None = Field(default=None)
    frequency_ceiling_hz: Decimal | None = Field(default=None)
    analysis_version: str
    analyzed_at: datetime = Field(default_factory=now_utc)