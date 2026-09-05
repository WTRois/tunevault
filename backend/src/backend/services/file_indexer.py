"""Fast-pass indexer: filesystem → files/recordings (blueprint §33, §34).

Heavy analysis (librosa, loudness, spectral) is deferred out of the scan;
unchanged files (same size + mtime) skip extraction and hashing entirely.
"""

import mimetypes
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from backend.core.time import now_utc
from backend.core.versions import ANALYSIS_VERSION
from backend.models import (
    Artwork,
    AudioFeature,
    File,
    FileRecording,
    MetadataProvenance,
    Recording,
)
from backend.services.extractor import extract_metadata

# Canonical text fields persisted to metadata_provenance when indexing tags (§5.13).
PROVENANCE_TAG_FIELDS = (
    "album",
    "album_artist",
    "composer",
    "genre",
    "year",
    "track_number",
    "disc_number",
    "lyrics",
)


def _utc(dt: datetime) -> datetime:
    """SQLite round-trips UTC datetimes as naive — restore the UTC assumption."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _upsert_recording(session: Session, meta: dict) -> Recording | None:
    """Find-or-create the logical Recording described by the file's own tags."""
    title = (meta.get("title") or "").strip() or None
    if not title:
        return None
    artist = (meta.get("artist") or "").strip() or None
    duration = meta.get("duration")
    duration_ms = int(duration * 1000) if duration else None

    recording = session.exec(
        select(Recording).where(Recording.title == title, Recording.artist_credit == artist)
    ).first()
    if recording is None:
        recording = Recording(title=title, artist_credit=artist, duration_ms=duration_ms)
        session.add(recording)
        session.commit()
        session.refresh(recording)
    return recording


def _link_file_recording(session: Session, file_id: int, recording_id: int) -> None:
    """Self-reported file→recording link (source=existing_tag, confidence 1.0)."""
    link = session.exec(
        select(FileRecording).where(FileRecording.file_id == file_id)
    ).first()
    if link is None:
        session.add(
            FileRecording(
                file_id=file_id,
                recording_id=recording_id,
                confidence=Decimal("1.0"),
                source="existing_tag",
            )
        )
    elif link.recording_id != recording_id:
        link.recording_id = recording_id
        link.confidence = Decimal("1.0")
        link.source = "existing_tag"
        link.matched_at = now_utc()
        session.add(link)
    session.commit()


def upsert_provenance(
    session: Session,
    file_id: int,
    field_name: str,
    value: Any,
    source: str,
    confidence: Decimal = Decimal("1.0"),
    candidate_id: int | None = None,
) -> None:
    """§9-aware canonical field write.

    One row per (file, field, source): same-source rows update in place;
    a row from a different source is left untouched (reads resolve by
    PROVENANCE_PRIORITY, so stronger evidence wins without data loss).
    """
    value = str(value)
    row = session.exec(
        select(MetadataProvenance).where(
            MetadataProvenance.file_id == file_id,
            MetadataProvenance.field_name == field_name,
            MetadataProvenance.source == source,
        )
    ).first()
    if row is None:
        session.add(
            MetadataProvenance(
                file_id=file_id,
                field_name=field_name,
                value_text=value,
                source=source,
                confidence=confidence,
                candidate_id=candidate_id,
                updated_at=now_utc(),
            )
        )
    else:
        row.value_text = value
        row.confidence = confidence
        row.updated_at = now_utc()
        session.add(row)
    session.commit()


def save_tag_provenance(
    session: Session, file_id: int, values: dict, source: str = "existing_tag"
) -> None:
    """Persist canonical text fields (album, genre, year, ...) from a metadata dict."""
    for field in PROVENANCE_TAG_FIELDS:
        value = values.get(field)
        if value is not None and value != "":
            upsert_provenance(session, file_id, field, value, source)


def set_embedded_artwork(session: Session, file_id: int, has_cover: bool) -> None:
    """Track embedded cover art presence as an artworks row (V1 has_cover flag)."""
    rows = session.exec(
        select(Artwork).where(Artwork.file_id == file_id, Artwork.is_embedded == True)
    ).all()
    if has_cover and not rows:
        session.add(Artwork(file_id=file_id, source="existing_tag", is_embedded=True))
        session.commit()
    elif not has_cover and rows:
        for row in rows:
            session.delete(row)
        session.commit()


def index_file(session: Session, filepath: str) -> tuple[File, dict, bool, bool]:
    """Upsert one audio file into the V2 domain schema.

    Fast pass (§34): when size + mtime are unchanged since the last index,
    extraction and SHA-256 are skipped entirely.

    Returns ``(file, metadata, changed, created)``; ``metadata`` is empty when skipped.
    """
    filepath = os.path.abspath(filepath)
    stat = os.stat(filepath)
    existing = session.exec(select(File).where(File.filepath == filepath)).first()
    if (
        existing is not None
        and existing.file_size == stat.st_size
        and _utc(existing.modified_at) == datetime.fromtimestamp(stat.st_mtime, tz=UTC)
        and existing.scan_state != "error"
    ):
        return existing, {}, False, False

    meta = extract_metadata(filepath)

    created = existing is None
    file = existing or File(filepath=filepath, filename="", extension="", sha256="", file_size=0,
                           modified_at=datetime.now(UTC))
    file.filename = meta.get("filename") or Path(filepath).name
    file.extension = Path(filepath).suffix.lower()
    file.mime_type = mimetypes.guess_type(filepath)[0]
    file.sha256 = meta.get("sha256") or ""
    file.file_size = stat.st_size
    file.modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
    duration = meta.get("duration")
    file.duration_ms = int(duration * 1000) if duration else None
    file.codec = meta.get("codec")
    file.container = file.extension.lstrip(".") or None
    file.bitrate = meta.get("bitrate")
    file.sample_rate = meta.get("sample_rate")
    file.channels = meta.get("channels")
    file.scan_state = "indexed"
    file.updated_at = now_utc()
    session.add(file)
    session.commit()
    session.refresh(file)

    recording = _upsert_recording(session, meta)
    if recording is not None:
        _link_file_recording(session, file.id, recording.id)

    save_tag_provenance(session, file.id, meta, source="existing_tag")
    if meta.get("has_cover"):
        set_embedded_artwork(session, file.id, True)

    return file, meta, True, created


# §5.11 decimal feature columns — partial feature dicts update only the
# keys they carry, so the scan's fast pass never clobbers a full analysis.
_FEATURE_DECIMAL_FIELDS = (
    "bpm",
    "integrated_lufs",
    "true_peak_db",
    "replaygain_track_db",
    "replaygain_album_db",
    "dynamic_range",
    "spectral_centroid",
    "frequency_ceiling_hz",
)


def save_audio_features(session: Session, file_id: int, features: dict) -> None:
    """Persist analysis results into audio_features, versioned per §37."""
    row = session.exec(
        select(AudioFeature).where(AudioFeature.file_id == file_id)
    ).first()
    row = row or AudioFeature(file_id=file_id)
    for field in _FEATURE_DECIMAL_FIELDS:
        if field not in features:
            continue
        value = features.get(field)
        setattr(row, field, Decimal(str(value)) if value is not None else None)
    if "musical_key" in features:
        row.musical_key = features.get("musical_key")
    row.analysis_version = ANALYSIS_VERSION
    row.analyzed_at = now_utc()
    session.add(row)
    session.commit()