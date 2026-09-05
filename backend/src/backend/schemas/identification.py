from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class IdentificationJobCreate(BaseModel):
    song_ids: list[int] = Field(default_factory=list, description="V1 song ids to identify")
    file_ids: list[int] = Field(default_factory=list, description="V2 file ids to identify")


class CandidateRead(BaseModel):
    id: int
    file_id: int
    source: str
    score: Decimal
    confidence_level: str
    status: str
    recording_mbid: str | None = None
    title: str | None = None
    artist: str | None = None
    release_title: str | None = None

    model_config = ConfigDict(from_attributes=False)


class IdentificationJobRead(BaseModel):
    id: int
    job_type: str
    status: str
    progress: float
    result_json: dict | list | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ReleaseMatchRead(BaseModel):
    release_id: int
    release_mbid: str | None = None
    release_title: str | None = None
    track_number: int | None = None
    disc_number: int | None = None


class AcceptResponse(BaseModel):
    accepted: bool
    file_id: int
    resolved: dict[str, str | None] | None = None
    recording_id: int | None = None
    release: ReleaseMatchRead | None = None


class ReviewCandidateRead(BaseModel):
    """Pending candidate joined with its file for the review queue (§22)."""

    id: int
    file_id: int
    filename: str
    filepath: str
    source: str
    score: Decimal
    confidence_level: str
    status: str
    recording_mbid: str | None = None
    title: str | None = None
    artist: str | None = None
    release_title: str | None = None


class BulkAcceptRequest(BaseModel):
    """Either explicit candidate ids, or a filter accepting the best pending
candidate per file (§22 bulk review)."""

    candidate_ids: list[int] = Field(default_factory=list)
    confidence_level: str | None = None
    min_score: float | None = None


class BulkAcceptResponse(BaseModel):
    accepted: list[AcceptResponse]
    skipped: int = 0
    errors: list[str] = Field(default_factory=list)


class ReleasePreferences(BaseModel):
    preference: str
    country: str = ""
    label: str = ""