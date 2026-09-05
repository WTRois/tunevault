from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LyricsCandidate(BaseModel):
    lrclib_id: int | None = None
    track_name: str
    artist_name: str
    album_name: str | None = None
    duration: float | None = None
    plain_lyrics: str | None = None
    synced_lyrics: str | None = None
    instrumental: bool = False


class LyricsFetchResponse(BaseModel):
    status: str
    lyrics: LyricsCandidate | None = None
    candidates: list[LyricsCandidate] = Field(default_factory=list)


class LyricsEmbedRequest(BaseModel):
    lyrics: str = Field(min_length=1, max_length=100_000)
    source: str | None = None
    lrclib_id: int | None = None

    @field_validator("lyrics")
    @classmethod
    def validate_lyrics(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Lyrics cannot be empty")
        return value


class YouTubeMetadataCandidate(BaseModel):
    video_id: str
    video_url: str
    title: str
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    genre: str | None = None
    year: int | None = None
    track_number: int | None = None
    disc_number: int | None = None
    composer: str | None = None
    duration: float | None = None
    thumbnail_url: str | None = None
    channel: str | None = None
    match_score: float = Field(ge=0, le=1)


class MetadataMatchSearchResponse(BaseModel):
    query: str
    candidates: list[YouTubeMetadataCandidate]


class MetadataMatchEmbedRequest(BaseModel):
    video_id: str = Field(min_length=11, max_length=11, pattern=r"^[A-Za-z0-9_-]{11}$")
    metadata: dict[str, str | int] = Field(min_length=1)

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, str | int]) -> dict[str, str | int]:
        allowed = {
            "title",
            "artist",
            "album",
            "album_artist",
            "composer",
            "genre",
            "year",
            "track_number",
            "disc_number",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"Unsupported metadata fields: {sorted(unknown)}")
        if not any(str(item).strip() for item in value.values()):
            raise ValueError("At least one metadata value is required")
        for key, item in value.items():
            if isinstance(item, str) and len(item.strip()) > 500:
                raise ValueError(f"{key} exceeds 500 characters")
            if key == "year" and (not isinstance(item, int) or not 1000 <= item <= 9999):
                raise ValueError("year must be between 1000 and 9999")
            if key in {"track_number", "disc_number"} and (not isinstance(item, int) or item < 1):
                raise ValueError(f"{key} must be a positive integer")
        return value


class SongUpdate(BaseModel):
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    composer: str | None = None
    genre: str | None = None
    year: int | None = None
    track_number: int | None = None
    disc_number: int | None = None
    lyrics: str | None = None


class SongRead(BaseModel):
    id: int
    filename: str
    filepath: str
    sha256: str

    title: str | None = None
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    composer: str | None = None
    genre: str | None = None
    year: int | None = None
    track_number: int | None = None
    disc_number: int | None = None

    duration: float | None = None
    bitrate: int | None = None
    codec: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    file_size: int | None = None

    bpm: float | None = None
    musical_key: str | None = None
    lyrics: str | None = None
    has_cover: bool = False

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedSongsResponse(BaseModel):
    items: list[SongRead]
    total: int
    page: int
    limit: int
    pages: int
