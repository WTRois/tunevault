import hashlib
import os
from pathlib import Path

SUPPORTED_EXTENSIONS: set[str] = {
    ".mp3",
    ".wav",
    ".flac",
    ".ogg",
    ".aac",
    ".m4a",
    ".wma",
    ".aiff",
    ".opus",
}


def is_supported_audio_file(filepath: str) -> bool:
    """Check if the file extension is supported."""
    ext = Path(filepath).suffix.lower()
    return ext in SUPPORTED_EXTENSIONS


def scan_directory(directory_path: str) -> list[str]:
    """Recursively scan directory for supported audio files."""
    audio_files: list[str] = []

    if not os.path.exists(directory_path) or not os.path.isdir(directory_path):
        return audio_files

    for root, _, files in os.walk(directory_path):
        for file in files:
            full_path = os.path.join(root, file)
            if is_supported_audio_file(full_path):
                audio_files.append(os.path.abspath(full_path))

    return sorted(audio_files)


def calculate_sha256(filepath: str, block_size: int = 65536) -> str:
    """Calculate SHA-256 hash of a file in chunks for memory efficiency."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(block_size), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_file_system_metadata(filepath: str) -> dict[str, str | int]:
    """Retrieve system-level file metadata."""
    stat = os.stat(filepath)
    return {
        "filename": os.path.basename(filepath),
        "filepath": os.path.abspath(filepath),
        "file_size": stat.st_size,
        "created_at": stat.st_ctime,
        "modified_at": stat.st_mtime,
    }
