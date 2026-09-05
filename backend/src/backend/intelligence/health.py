"""Library health metrics (blueprint §14, TV2-033).

One code path per issue produces BOTH the §14 counts and the drill-down
lists — counts are just ``len()`` of the same data the UI reviews.

Definitions (documented, §14 metrics):
    - metadata completeness: files whose resolved metadata carries every
      core field (title, artist, album, year, track_number) — §9 priority;
    - identification coverage: files linked to a canonical recording;
    - artwork coverage: files with embedded art OR whose linked release
      has artwork;
    - audio analysis coverage: files with a current full analysis (§37
      version match + loudness measured);
    - duplicate rate: files in §13 redundant-audio pairs.
"""

from collections import defaultdict

from sqlmodel import Session, select

from backend.audio.spectral import classify_upsample
from backend.core.versions import ANALYSIS_VERSION
from backend.intelligence.duplicates import duplicate_file_ids
from backend.models import (
    Artwork,
    AudioFeature,
    File,
    FileRecording,
    FileRelease,
    MetadataProvenance,
)
from backend.models.metadata import PROVENANCE_PRIORITY

CORE_METADATA_FIELDS = ("title", "artist", "album", "year", "track_number")

ISSUE_TYPES = (
    "missing_artwork",
    "unidentified",
    "duplicates",
    "inconsistent_album_artist",
    "possible_upsample",
)


def resolved_metadata(session: Session) -> dict[int, dict[str, str | None]]:
    """Bulk §9 priority resolution — same rule as the organization plan:
    highest (PROVENANCE_PRIORITY, row id) wins per (file, field)."""
    rows = session.exec(select(MetadataProvenance)).all()
    best: dict[tuple[int, str], tuple[int, int, str | None]] = {}
    for row in rows:
        rank = (PROVENANCE_PRIORITY.get(row.source, 0), row.id or 0)
        current = best.get((row.file_id, row.field_name))
        if current is None or rank > (current[0], current[1]):
            best[(row.file_id, row.field_name)] = (*rank, row.value_text)
    resolved: dict[int, dict[str, str | None]] = defaultdict(dict)
    for (file_id, field), value in best.items():
        resolved[file_id][field] = value[2]
    return resolved


def _identified_ids(session: Session) -> set[int]:
    # select(single column) yields scalar ids directly.
    return set(session.exec(select(FileRecording.file_id)).all())


def _artwork_file_ids(session: Session) -> set[int]:
    """Files with embedded art or whose linked release has artwork."""
    embedded = {
        file_id
        for file_id in session.exec(select(Artwork.file_id)).all()
        if file_id
    }
    releases_with_art = {
        release_id
        for release_id in session.exec(select(Artwork.release_id)).all()
        if release_id
    }
    linked = {
        row.file_id: row.release_id
        for row in session.exec(select(FileRelease)).all()
    }
    return embedded | {
        file_id for file_id, release_id in linked.items()
        if release_id in releases_with_art
    }


def _fresh_analysis_ids(session: Session) -> set[int]:
    """Current full analysis per §37 — same freshness rule as the analyze
    job: matching version AND the full pass actually ran (loudness filled)."""
    return {
        row.file_id
        for row in session.exec(select(AudioFeature)).all()
        if row.analysis_version == ANALYSIS_VERSION and row.integrated_lufs is not None
    }


def _file_row(file: File, metadata: dict[str, str | None], **detail) -> dict:
    row = {
        "file_id": file.id,
        "filename": file.filename,
        "filepath": file.filepath,
        "title": metadata.get("title"),
    }
    row.update(detail)
    return row


def missing_artwork_files(session: Session) -> list[dict]:
    metadata = resolved_metadata(session)
    with_art = _artwork_file_ids(session)
    return [
        _file_row(file, metadata.get(file.id or 0, {}))
        for file in session.exec(select(File).order_by(File.id)).all()
        if file.id not in with_art
    ]


def unidentified_files(session: Session) -> list[dict]:
    metadata = resolved_metadata(session)
    identified = _identified_ids(session)
    return [
        _file_row(file, metadata.get(file.id or 0, {}))
        for file in session.exec(select(File).order_by(File.id)).all()
        if file.id not in identified
    ]


def inconsistent_album_artist_rows(session: Session) -> list[dict]:
    """Files whose album_artist deviates from their album's majority
    value (§14 inconsistent album artist). Files without an album or
    without any album_artist are missing-field cases, not inconsistencies."""
    metadata = resolved_metadata(session)
    albums: dict[str, list[tuple[File, str]]] = defaultdict(list)
    for file in session.exec(select(File).order_by(File.id)).all():
        fields = metadata.get(file.id or 0, {})
        album = (fields.get("album") or "").strip()
        album_artist = (fields.get("album_artist") or "").strip()
        if album and album_artist:
            albums[album.casefold()].append((file, album_artist))

    rows = []
    for tracks in albums.values():
        counts: dict[str, int] = defaultdict(int)
        for _, album_artist in tracks:
            counts[album_artist] += 1
        if len(counts) < 2:
            continue  # consistent album
        expected = max(sorted(counts), key=lambda value: counts[value])
        for file, album_artist in tracks:
            if album_artist != expected:
                rows.append(
                    _file_row(
                        file,
                        metadata.get(file.id or 0, {}),
                        album=metadata[file.id or 0].get("album"),
                        expected_album_artist=expected,
                        actual_album_artist=album_artist,
                    )
                )
    return rows


def possible_upsample_rows(session: Session) -> list[dict]:
    """Files whose spectral ceiling triggers the WARNING-ONLY upsample
    verdict (§12.3) — displayed, never acted upon."""
    metadata = resolved_metadata(session)
    files = {file.id: file for file in session.exec(select(File)).all()}
    rows = []
    for feature in session.exec(select(AudioFeature)).all():
        file = files.get(feature.file_id)
        if file is None or feature.frequency_ceiling_hz is None:
            continue
        verdict = classify_upsample(
            file.sample_rate, float(feature.frequency_ceiling_hz)
        )
        if verdict["status"] != "possible_upsample":
            continue
        rows.append(
            _file_row(
                file,
                metadata.get(file.id or 0, {}),
                sample_rate=file.sample_rate,
                frequency_ceiling_hz=float(feature.frequency_ceiling_hz),
                confidence=verdict["confidence"],
            )
        )
    return rows


def _pct(part: int, total: int) -> float:
    return round(part / total * 100.0, 1) if total else 100.0


def compute_library_health(session: Session) -> dict:
    """The §14 response shape: five 0-100 scores + issue counts."""
    files = session.exec(select(File.id)).all()
    total = len(files)
    metadata = resolved_metadata(session)
    complete = sum(
        1
        for fields in metadata.values()
        if all((fields.get(field) or "").strip() for field in CORE_METADATA_FIELDS)
    )
    identified = len(_identified_ids(session))
    with_art = len(_artwork_file_ids(session))
    fresh = len(_fresh_analysis_ids(session))
    duplicated = len(duplicate_file_ids(session))

    return {
        "metadata_health": _pct(complete, total),
        "identification_health": _pct(identified, total),
        "artwork_health": _pct(with_art, total),
        "audio_analysis_health": _pct(fresh, total),
        "duplicate_health": round(100.0 - _pct(duplicated, total), 1),
        "issues": {
            "missing_artwork": total - with_art,
            "unidentified": total - identified,
            "duplicates": duplicated,
            "inconsistent_album_artist": len(inconsistent_album_artist_rows(session)),
            "possible_upsample": len(possible_upsample_rows(session)),
        },
    }


def issue_rows(session: Session, issue_type: str) -> list[dict]:
    """Drill-down rows for one §14 issue type (§22 review lists)."""
    if issue_type == "missing_artwork":
        return missing_artwork_files(session)
    if issue_type == "unidentified":
        return unidentified_files(session)
    if issue_type == "duplicates":
        from backend.intelligence.duplicates import find_duplicates

        return find_duplicates(session)
    if issue_type == "inconsistent_album_artist":
        return inconsistent_album_artist_rows(session)
    if issue_type == "possible_upsample":
        return possible_upsample_rows(session)
    raise ValueError(
        f"Unknown issue type {issue_type!r}. Valid: {', '.join(ISSUE_TYPES)}"
    )


__all__ = [
    "ISSUE_TYPES",
    "compute_library_health",
    "issue_rows",
    "resolved_metadata",
]