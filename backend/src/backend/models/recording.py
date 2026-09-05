from datetime import datetime

from sqlmodel import Field, SQLModel

from backend.core.time import now_utc


class Artist(SQLModel, table=True):
    """Canonical artist entity (blueprint §5.3)."""

    __tablename__ = "artists"

    id: int | None = Field(default=None, primary_key=True)
    musicbrainz_artist_id: str | None = Field(default=None, unique=True)
    name: str = Field(index=True)
    sort_name: str | None = Field(default=None)
    disambiguation: str | None = Field(default=None)


class Recording(SQLModel, table=True):
    """Logical recording/performance identity (blueprint §5.2)."""

    __tablename__ = "recordings"

    id: int | None = Field(default=None, primary_key=True)
    musicbrainz_recording_id: str | None = Field(default=None, unique=True)
    title: str = Field(index=True)
    artist_credit: str | None = Field(default=None)
    duration_ms: int | None = Field(default=None)
    isrc: str | None = Field(default=None)
    disambiguation: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)