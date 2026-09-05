"""V1-compatible song repository over the V2 domain schema (TV2-011b, §40 Option B).

Reads: files LEFT JOIN recordings (via file_recordings) + metadata_provenance
+ audio_features + artworks. ``song_id`` is now ``files.id``.
Writes: routed into the V2 schema only — the legacy ``songs`` table is no
longer written (data stays untouched per §2.4 Never Destroy).
"""

import mimetypes
import os
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from sqlalchemy import case, cast, func, or_
from sqlalchemy.types import Integer
from sqlmodel import Session, col, select

from backend.core.time import now_utc
from backend.models import (
    Artwork,
    AudioFeature,
    File,
    FileRecording,
    MetadataCandidate,
    MetadataProvenance,
    Recording,
)
from backend.models.file import Fingerprint
from backend.models.metadata import PROVENANCE_PRIORITY
from backend.services.file_indexer import (
    _link_file_recording,
    _upsert_recording,
    save_audio_features,
    save_tag_provenance,
    set_embedded_artwork,
)

# Provenance-backed fields served with the V1 Song shape.
TEXT_FIELDS = (
    "album",
    "album_artist",
    "composer",
    "genre",
    "year",
    "track_number",
    "disc_number",
    "lyrics",
)
INT_TEXT_FIELDS = ("year", "track_number", "disc_number")


class SongView(BaseModel):
    """V1 SongRead shape served from the V2 schema."""

    model_config = ConfigDict(from_attributes=True)

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


def _source_priority(source: str) -> int:
    return PROVENANCE_PRIORITY.get(source, 0)


def _provenance_map(session: Session, file_ids: list[int]) -> dict[int, dict[str, str]]:
    """file_id → {field: value} resolved by §9 priority (latest row wins ties)."""
    if not file_ids:
        return {}
    rows = session.exec(
        select(MetadataProvenance).where(col(MetadataProvenance.file_id).in_(file_ids))
    ).all()
    best: dict[int, dict[str, tuple[int, int, str]]] = {}
    for row in rows:  # ordered by id → later rows of equal priority win
        current = best.setdefault(row.file_id, {}).get(row.field_name)
        key = (_source_priority(row.source), row.id or 0)
        if current is None or key > (current[0], current[1]):
            best[row.file_id][row.field_name] = (*key, row.value_text)
    return {fid: {f: v[2] for f, v in fields.items()} for fid, fields in best.items()}


def _as_int(prov: dict[str, str], field: str) -> int | None:
    try:
        return int(prov[field])
    except (KeyError, TypeError, ValueError):
        return None


def _assemble(
    file: File,
    recording: Recording | None,
    prov: dict[str, str],
    audio_feature: AudioFeature | None,
    has_cover: bool,
) -> SongView:
    return SongView(
        id=file.id or 0,
        filename=file.filename,
        filepath=file.filepath,
        sha256=file.sha256,
        title=recording.title if recording else None,
        artist=recording.artist_credit if recording else None,
        album=prov.get("album"),
        album_artist=prov.get("album_artist"),
        composer=prov.get("composer"),
        genre=prov.get("genre"),
        year=_as_int(prov, "year"),
        track_number=_as_int(prov, "track_number"),
        disc_number=_as_int(prov, "disc_number"),
        duration=(file.duration_ms / 1000) if file.duration_ms else None,
        bitrate=file.bitrate,
        codec=file.codec,
        sample_rate=file.sample_rate,
        channels=file.channels,
        file_size=file.file_size,
        bpm=float(audio_feature.bpm) if audio_feature and audio_feature.bpm is not None else None,
        musical_key=audio_feature.musical_key if audio_feature else None,
        lyrics=prov.get("lyrics"),
        has_cover=has_cover,
        created_at=file.created_at,
        updated_at=file.updated_at,
    )


def _recordings_by_file(session: Session, file_ids: list[int]) -> dict[int, Recording]:
    if not file_ids:
        return {}
    links = session.exec(
        select(FileRecording).where(col(FileRecording.file_id).in_(file_ids))
    ).all()
    if not links:
        return {}
    recs = session.exec(
        select(Recording).where(col(Recording.id).in_([l.recording_id for l in links]))
    ).all()
    rec_map = {r.id: r for r in recs}
    return {l.file_id: rec_map[l.recording_id] for l in links if l.recording_id in rec_map}


def _covers_by_file(session: Session, file_ids: list[int]) -> set[int]:
    if not file_ids:
        return set()
    rows = session.exec(
        select(Artwork.file_id).where(
            col(Artwork.file_id).in_(file_ids),
            Artwork.is_embedded == True,
        )
    ).all()
    return {r for r in rows}


def _features_by_file(session: Session, file_ids: list[int]) -> dict[int, AudioFeature]:
    if not file_ids:
        return {}
    rows = session.exec(
        select(AudioFeature).where(col(AudioFeature.file_id).in_(file_ids))
    ).all()
    return {r.file_id: r for r in rows}


def _batch_assemble(session: Session, rows: list[tuple[File, Recording | None]]) -> list[SongView]:
    files = [file for file, _recording in rows]
    recordings: dict[int, Recording | None] = {
        (file.id or 0): recording for file, recording in rows
    }
    file_ids = [f.id for f in files if f.id is not None]
    prov_map = _provenance_map(session, file_ids)
    feature_map = _features_by_file(session, file_ids)
    cover_ids = _covers_by_file(session, file_ids)
    return [
        _assemble(file, recordings.get(file.id), prov_map.get(file.id or 0, {}), feature_map.get(file.id or 0), (file.id or 0) in cover_ids)
        for file in files
    ]


def _base_query():
    """files LEFT JOIN recordings — one row per file (file_recordings.file_id is unique)."""
    return (
        select(File, Recording)
        .join(FileRecording, FileRecording.file_id == File.id, isouter=True)
        .join(Recording, Recording.id == FileRecording.recording_id, isouter=True)
    )


class SongRepository:
    """Serves the V1 song API from the V2 domain schema (§40 Option B)."""

    @staticmethod
    def get_by_id(session: Session, song_id: int) -> SongView | None:
        """Fetch a song view by files.id."""
        rows = session.exec(_base_query().where(File.id == song_id)).all()
        return _batch_assemble(session, list(rows))[0] if rows else None

    @staticmethod
    def get_by_filepath(session: Session, filepath: str) -> SongView | None:
        """Fetch a song view by exact filepath."""
        rows = session.exec(_base_query().where(File.filepath == filepath)).all()
        return _batch_assemble(session, list(rows))[0] if rows else None

    @staticmethod
    def get_by_sha256(session: Session, sha256_hash: str) -> SongView | None:
        """Fetch a song view by SHA-256 hash."""
        rows = session.exec(_base_query().where(File.sha256 == sha256_hash)).all()
        return _batch_assemble(session, list(rows))[0] if rows else None

    @staticmethod
    def upsert_song(
        session: Session,
        song_data: dict,
        source: str = "user",
    ) -> tuple[SongView, bool]:
        """Insert or update a file + its domain rows from a metadata dict.

        The physical file is untouched here — callers write tags first.
        ``source`` feeds metadata_provenance (§9): default ``user`` for V1
        endpoint edits, ``existing_tag`` for scan/download imports.
        """
        filepath = song_data["filepath"]
        file = session.exec(select(File).where(File.filepath == filepath)).first()
        sha256_hash = song_data.get("sha256")
        if file is None and sha256_hash:
            file = session.exec(select(File).where(File.sha256 == sha256_hash)).first()

        created = file is None
        if created:
            file = File(
                filepath=filepath,
                filename="",
                extension="",
                sha256="",
                file_size=0,
                modified_at=now_utc(),
            )
            session.add(file)
            session.commit()
            session.refresh(file)

        if sha256_hash:
            file.sha256 = sha256_hash
        file.filename = song_data.get("filename") or Path(filepath).name
        file.extension = Path(filepath).suffix.lower()
        duration = song_data.get("duration")
        if duration:
            file.duration_ms = int(duration * 1000)
        for key in ("bitrate", "codec", "sample_rate", "channels"):
            if song_data.get(key) is not None:
                setattr(file, key, song_data[key])
        if song_data.get("file_size"):
            file.file_size = song_data["file_size"]
        if os.path.exists(filepath):
            file.file_size = os.path.getsize(filepath)
            file.modified_at = datetime.fromtimestamp(os.path.getmtime(filepath), tz=UTC)
            file.mime_type = mimetypes.guess_type(filepath)[0]
        file.scan_state = "indexed"
        file.updated_at = now_utc()
        session.add(file)
        session.commit()
        session.refresh(file)

        # Keep the current artist when only the title changes (V1 semantics).
        meta_for_recording = dict(song_data)
        if not meta_for_recording.get("artist"):
            link = session.exec(
                select(FileRecording).where(FileRecording.file_id == file.id)
            ).first()
            if link is not None:
                previous = session.get(Recording, link.recording_id)
                meta_for_recording["artist"] = previous.artist_credit if previous else None

        recording = _upsert_recording(session, meta_for_recording)
        if recording is not None:
            _link_file_recording(session, file.id, recording.id)

        save_tag_provenance(session, file.id, song_data, source=source)

        if "has_cover" in song_data:
            set_embedded_artwork(session, file.id, bool(song_data["has_cover"]))

        if song_data.get("bpm") is not None or song_data.get("musical_key") is not None:
            save_audio_features(
                session, file.id, {"bpm": song_data.get("bpm"), "musical_key": song_data.get("musical_key")}
            )

        view = SongRepository.get_by_id(session, file.id or 0)
        assert view is not None  # the row was just committed
        return view, created

    @staticmethod
    def list_songs(
        session: Session,
        page: int = 1,
        limit: int = 50,
        search: str | None = None,
        artist: str | None = None,
        album: str | None = None,
        genre: str | None = None,
        sort_by: str = "id",
        order: str = "asc",
    ) -> tuple[list[SongView], int]:
        """List songs with search, filtering, sorting and pagination (V1 contract)."""
        query = _base_query()

        if search:
            term = f"%{search}%"
            query = query.where(
                or_(
                    col(Recording.title).ilike(term),
                    col(Recording.artist_credit).ilike(term),
                    col(File.filename).ilike(term),
                )
            )
        if artist:
            query = query.where(col(Recording.artist_credit).ilike(f"%{artist}%"))
        if album:
            query = query.where(
                col(File.id).in_(
                    select(MetadataProvenance.file_id).where(
                        MetadataProvenance.field_name == "album",
                        col(MetadataProvenance.value_text).ilike(f"%{album}%"),
                    )
                )
            )
        if genre:
            query = query.where(
                col(File.id).in_(
                    select(MetadataProvenance.file_id).where(
                        MetadataProvenance.field_name == "genre",
                        col(MetadataProvenance.value_text).ilike(f"%{genre}%"),
                    )
                )
            )

        total_count = session.exec(select(func.count()).select_from(query.subquery())).one()

        def _prov_value(field: str):
            """Canonical provenance value for a field, §9 priority-aware."""
            priority_case = case(
                *[(MetadataProvenance.source == src, pri) for src, pri in PROVENANCE_PRIORITY.items()],
                else_=0,
            )
            return (
                select(MetadataProvenance.value_text)
                .where(
                    MetadataProvenance.file_id == File.id,
                    MetadataProvenance.field_name == field,
                )
                .order_by(priority_case.desc(), MetadataProvenance.id.desc())
                .limit(1)
                .correlate(File)
                .scalar_subquery()
            )

        sort_map = {
            "id": File.id,
            "title": Recording.title,
            "artist": Recording.artist_credit,
            "album": _prov_value("album"),
            "genre": _prov_value("genre"),
            "year": cast(_prov_value("year"), Integer),
            "duration": File.duration_ms,
            "bpm": select(AudioFeature.bpm)
            .where(AudioFeature.file_id == File.id)
            .correlate(File)
            .scalar_subquery(),
            "created_at": File.created_at,
        }
        sort_column = sort_map.get(sort_by, File.id)
        query = query.order_by(sort_column.desc() if order.lower() == "desc" else sort_column.asc())

        offset = (page - 1) * limit
        rows = session.exec(query.offset(offset).limit(limit)).all()
        return _batch_assemble(session, list(rows)), total_count

    @staticmethod
    def delete_song(session: Session, song_id: int) -> bool:
        """Delete a file record and its dependents (the physical file stays)."""
        file = session.get(File, song_id)
        if file is None:
            return False
        for model in (FileRecording, MetadataProvenance, Artwork, AudioFeature, MetadataCandidate, Fingerprint):
            for row in session.exec(select(model).where(model.file_id == file.id)).all():
                session.delete(row)
        session.delete(file)
        session.commit()
        return True