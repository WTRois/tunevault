from datetime import datetime
from decimal import Decimal

from sqlmodel import Field, SQLModel

from backend.core.time import now_utc

CANDIDATE_STATUSES = ("pending", "accepted", "rejected", "expired")

PROVENANCE_SOURCES = (
    "existing_tag",
    "filename",
    "folder",
    "musicbrainz",
    "acoustid",
    "youtube",
    "user",
    "llm",
)

# §9 resolution priority: a value from a higher-priority source wins over
# any other row for the same (file_id, field_name), regardless of insertion order.
PROVENANCE_PRIORITY = {
    "user": 100,
    "musicbrainz": 80,
    "acoustid": 70,
    "youtube": 60,
    "llm": 50,
    "existing_tag": 40,
    "filename": 30,
    "folder": 20,
}

CHANGE_OPERATIONS = ("metadata_update", "artwork_update", "rename", "move")


class MetadataCandidate(SQLModel, table=True):
    """Identification candidate before apply (blueprint §5.12)."""

    __tablename__ = "metadata_candidates"

    id: int | None = Field(default=None, primary_key=True)
    file_id: int = Field(foreign_key="files.id", index=True)
    source: str
    recording_id: int | None = Field(default=None, foreign_key="recordings.id")
    release_id: int | None = Field(default=None, foreign_key="releases.id")
    payload_json: str
    score: Decimal
    confidence_level: str
    reasoning_json: str | None = Field(default=None)
    status: str = Field(default="pending", index=True)
    created_at: datetime = Field(default_factory=now_utc)


class MetadataProvenance(SQLModel, table=True):
    """Origin record for every canonical field value (blueprint §5.13)."""

    __tablename__ = "metadata_provenance"

    id: int | None = Field(default=None, primary_key=True)
    file_id: int = Field(foreign_key="files.id", index=True)
    field_name: str
    value_text: str
    source: str
    confidence: Decimal
    candidate_id: int | None = Field(default=None, foreign_key="metadata_candidates.id")
    updated_at: datetime = Field(default_factory=now_utc)


class ChangeSet(SQLModel, table=True):
    """One undoable logical transaction (blueprint §5.14)."""

    __tablename__ = "change_sets"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    status: str = Field(default="pending", index=True)
    created_by: str = Field(default="system")
    created_at: datetime = Field(default_factory=now_utc)
    applied_at: datetime | None = Field(default=None)
    rolled_back_at: datetime | None = Field(default=None)


class Change(SQLModel, table=True):
    """Individual change inside a change set (blueprint §5.15)."""

    __tablename__ = "changes"

    id: int | None = Field(default=None, primary_key=True)
    change_set_id: int = Field(foreign_key="change_sets.id", index=True)
    file_id: int = Field(foreign_key="files.id", index=True)
    operation: str
    old_value_json: str | None = Field(default=None)
    new_value_json: str | None = Field(default=None)
    old_path: str | None = Field(default=None)
    new_path: str | None = Field(default=None)
    backup_path: str | None = Field(default=None)
    verification_status: str | None = Field(default=None)