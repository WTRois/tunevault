from datetime import datetime

from pydantic import BaseModel, Field


class DownloadPreviewRequest(BaseModel):
    url: str = Field(..., description="YouTube or YouTube Music URL")


class DownloadPreviewResponse(BaseModel):
    url: str
    title: str
    artist: str
    album: str | None = None
    duration: float | None = None
    thumbnail_url: str | None = None
    source_bitrate_estimate: int | None = None


class DownloadJobCreate(BaseModel):
    url: str = Field(..., description="YouTube or YouTube Music URL")
    bitrate: int = Field(default=192, description="Target bitrate (128, 192, 256, 320)")
    title_override: str | None = Field(default=None, description="Optional custom title")
    artist_override: str | None = Field(default=None, description="Optional custom artist")
    album_override: str | None = Field(default=None, description="Optional custom album")
    auto_import: bool = Field(
        default=True, description="Automatically import downloaded audio to /music library"
    )


class DownloadJobStatusResponse(BaseModel):
    job_id: str
    url: str
    bitrate: int
    status: str  # pending, downloading, converting, tagging, done, failed
    progress_percent: float = 0.0
    title: str | None = None
    artist: str | None = None
    file_path: str | None = None
    imported_song_id: int | None = None
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
