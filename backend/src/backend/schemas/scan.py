from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ScanJobCreate(BaseModel):
    directory_path: str = Field(description="Target directory path to scan for audio files")
    perform_audio_analysis: bool = Field(
        default=True,
        description="Enable Librosa BPM and Key estimation",
    )


class ScanJobRead(BaseModel):
    id: int
    directory_path: str
    status: str
    scanned_files: int
    total_files: int
    added_count: int
    updated_count: int
    error_count: int
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
