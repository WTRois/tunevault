from datetime import datetime

from sqlmodel import Field, SQLModel

from backend.core.time import now_utc


class Song(SQLModel, table=True):
    __tablename__ = "songs"

    id: int | None = Field(default=None, primary_key=True)
    filename: str = Field(index=True)
    filepath: str = Field(unique=True, index=True)
    sha256: str = Field(index=True)

    # Basic metadata
    title: str | None = Field(default=None, index=True)
    artist: str | None = Field(default=None, index=True)
    album: str | None = Field(default=None, index=True)
    album_artist: str | None = Field(default=None)
    composer: str | None = Field(default=None)
    genre: str | None = Field(default=None, index=True)
    year: int | None = Field(default=None)
    track_number: int | None = Field(default=None)
    disc_number: int | None = Field(default=None)

    # Technical metadata
    duration: float | None = Field(default=None)
    bitrate: int | None = Field(default=None)
    codec: str | None = Field(default=None)
    sample_rate: int | None = Field(default=None)
    channels: int | None = Field(default=None)
    file_size: int | None = Field(default=None)

    # Extended metadata
    bpm: float | None = Field(default=None)
    musical_key: str | None = Field(default=None)
    lyrics: str | None = Field(default=None)
    has_cover: bool = Field(default=False)

    # System metadata
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)
