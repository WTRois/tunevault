from datetime import datetime
from decimal import Decimal

# (release_id, disc_number, track_number, recording_id) unique — declared via UniqueConstraint
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from backend.core.time import now_utc


class ReleaseGroup(SQLModel, table=True):
    """Album-level grouping entity (blueprint §5.4)."""

    __tablename__ = "release_groups"

    id: int | None = Field(default=None, primary_key=True)
    musicbrainz_release_group_id: str | None = Field(default=None, unique=True)
    title: str = Field(index=True)
    primary_type: str | None = Field(default=None)
    secondary_types_json: str | None = Field(default=None)


class Release(SQLModel, table=True):
    """Concrete release/pressing (blueprint §5.5)."""

    __tablename__ = "releases"

    id: int | None = Field(default=None, primary_key=True)
    release_group_id: int = Field(foreign_key="release_groups.id", index=True)
    musicbrainz_release_id: str | None = Field(default=None, unique=True)
    title: str
    date: str | None = Field(default=None)
    country: str | None = Field(default=None)
    barcode: str | None = Field(default=None)
    media_json: str | None = Field(default=None)


class ReleaseTrack(SQLModel, table=True):
    """Track position on a release (blueprint §5.6)."""

    __tablename__ = "release_tracks"
    __table_args__ = (
        UniqueConstraint(
            "release_id",
            "disc_number",
            "track_number",
            "recording_id",
            name="uq_release_track_position",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    release_id: int = Field(foreign_key="releases.id", index=True)
    recording_id: int = Field(foreign_key="recordings.id", index=True)
    disc_number: int
    track_number: int
    position: int
    title: str | None = Field(default=None)
    length_ms: int | None = Field(default=None)


class Artwork(SQLModel, table=True):
    """Artwork per release/file (blueprint §5.10)."""

    __tablename__ = "artworks"

    id: int | None = Field(default=None, primary_key=True)
    release_id: int | None = Field(default=None, foreign_key="releases.id", index=True)
    file_id: int | None = Field(default=None, foreign_key="files.id", index=True)
    source: str
    source_id: str | None = Field(default=None)
    url: str | None = Field(default=None)
    local_path: str | None = Field(default=None)
    sha256: str | None = Field(default=None)
    mime_type: str | None = Field(default=None)
    width: int | None = Field(default=None)
    height: int | None = Field(default=None)
    type: str = Field(default="front")
    is_embedded: bool = Field(default=False)
    quality_score: Decimal | None = Field(default=None)
    created_at: datetime = Field(default_factory=now_utc)