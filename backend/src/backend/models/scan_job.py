from datetime import datetime

from sqlmodel import Field, SQLModel

from backend.core.time import now_utc


class ScanJob(SQLModel, table=True):
    __tablename__ = "scan_jobs"

    id: int | None = Field(default=None, primary_key=True)
    directory_path: str
    status: str = Field(default="pending", index=True)  # pending, running, completed, failed

    scanned_files: int = Field(default=0)
    total_files: int = Field(default=0)
    added_count: int = Field(default=0)
    updated_count: int = Field(default=0)
    error_count: int = Field(default=0)
    error_message: str | None = Field(default=None)

    created_at: datetime = Field(default_factory=now_utc)
    completed_at: datetime | None = Field(default=None)
