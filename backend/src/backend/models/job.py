from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from backend.core.time import now_utc

JOB_TYPES = (
    "scan",
    "extract",
    "fingerprint",
    "identify",
    "enrich",
    "artwork",
    "analyze_audio",
    "duplicate_scan",
    "organize",
    "export",
    "download",
)

JOB_STATUSES = ("pending", "running", "completed", "failed", "cancelled")


class Job(SQLModel, table=True):
    """Generic persistent job (blueprint §5.16). Claimed atomically per §23."""

    __tablename__ = "jobs"

    id: int | None = Field(default=None, primary_key=True)
    job_type: str = Field(index=True)
    status: str = Field(default="pending", index=True)
    priority: int = Field(default=0, index=True)
    progress: float = Field(default=0.0)
    payload_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    result_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    error_message: str | None = Field(default=None)
    attempts: int = Field(default=0)
    max_attempts: int = Field(default=3)

    created_at: datetime = Field(default_factory=now_utc)
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)


class JobItem(SQLModel, table=True):
    """Per-file granular progress for a job (blueprint §5.17)."""

    __tablename__ = "job_items"

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", index=True)
    # FK to files.id is added once the files table lands (TV2-009 migration);
    # SQLAlchemy cannot resolve the FK while `files` is absent from metadata.
    file_id: int | None = Field(default=None, index=True)
    status: str = Field(default="pending", index=True)
    progress: float = Field(default=0.0)
    error_message: str | None = Field(default=None)

    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)