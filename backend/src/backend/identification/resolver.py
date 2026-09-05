"""Metadata resolution policy (blueprint §9) + provenance (§5.13).

Priority: user confirmed > trusted provider > fingerprint-derived >
metadata search > filename parser > heuristic guess. Conflicting values
without strong evidence are NEVER auto-changed (§9 DO NOT AUTO-CHANGE).

Fields a user has explicitly edited are protected from auto-resolution.
"""

import json
from decimal import Decimal

from sqlmodel import Session

from backend.core.time import now_utc
from backend.core.versions import SCORING_VERSION
from backend.identification.constants import AUTO_APPLY
from backend.models import File, MetadataCandidate, MetadataProvenance

# Sources ranked by §9 general priority (lower number = stronger).
SOURCE_PRIORITY: dict[str, int] = {
    "user": 0,
    "musicbrainz": 1,
    "acoustid": 2,
    "youtube": 3,
    "llm": 4,
    "filename": 5,
    "folder": 6,
    "existing_tag": 7,
    "heuristic": 8,
}

# §9: fields resolved only via user confirmation (DO NOT AUTO-CHANGE).
USER_OWNED_FIELDS = {"lyrics", "comment", "rating", "play_count"}

RESOLVABLE_FIELDS = ("title", "artist", "album", "album_artist", "year", "track_number", "disc_number")


def source_rank(source: str) -> int:
    """Rank a source per §9; unknown sources sit between filename and tags."""
    return SOURCE_PRIORITY.get(source, SOURCE_PRIORITY["existing_tag"])


def save_candidates(
    session: Session,
    file_id: int,
    scored_candidates: list[tuple],
    keep: int = 5,
) -> list[MetadataCandidate]:
    """Persist scored candidates (§5.12) — best first; duplicates replaced."""
    rows: list[MetadataCandidate] = []
    for score, outcome, details, candidate in scored_candidates[:keep]:
        row = MetadataCandidate(
            file_id=file_id,
            source=candidate.source,
            recording_id=None,  # release-level link lands with TV2-018
            payload_json=json.dumps(candidate.to_dict(), default=str),
            score=Decimal(str(round(score, 4))),
            confidence_level=outcome,
            reasoning_json=json.dumps(details, default=str),
            status="pending",
        )
        session.add(row)
        rows.append(row)
    session.commit()
    return rows


def resolve_recording(
    session: Session,
    file: File,
    candidate_row: MetadataCandidate,
    *,
    user_confirmed: bool = False,
) -> dict[str, str | None]:
    """Resolve canonical fields from an accepted candidate (§9).

    Returns the resolved field values. Never touches the filesystem or the
    file's tags — writing is a Change Plan operation (TV2-026).
    """
    from backend.providers.base import ProviderMatch

    match = ProviderMatch.from_dict(json.loads(candidate_row.payload_json))
    source = match.source if match.source in SOURCE_PRIORITY else "musicbrainz"

    resolved: dict[str, str | None] = {}
    for field in RESOLVABLE_FIELDS:
        value = getattr(match, field, None) if field != "artist" else match.artist
        if field == "artist" and not value:
            continue
        if field == "title":
            value = match.title
        if value is None:
            continue
        if field in USER_OWNED_FIELDS and not user_confirmed:
            continue  # DO NOT AUTO-CHANGE (§9)
        resolved[field] = str(value)

    candidate_row.status = "accepted" if user_confirmed or candidate_row.confidence_level == AUTO_APPLY else "pending"
    session.add(candidate_row)

    for field, value in resolved.items():
        provenance = MetadataProvenance(
            file_id=file.id or 0,
            field_name=field,
            value_text=value,
            source=source,
            confidence=candidate_row.score,
            candidate_id=candidate_row.id,
            updated_at=now_utc(),
        )
        session.add(provenance)
    session.commit()

    resolved["scoring_version"] = SCORING_VERSION
    return resolved


def write_recording_link(
    session: Session,
    file_id: int,
    match,
    confidence: Decimal,
) -> int | None:
    """Upsert the file→recording link for an accepted MusicBrainz match."""
    from backend.models import FileRecording, Recording

    recording = None
    if getattr(match, "recording_mbid", None):
        recording = session.exec(
            select_by_mbid(match.recording_mbid)
        ).first()
    if recording is None:
        recording = Recording(
            musicbrainz_recording_id=match.recording_mbid,
            title=match.title,
            artist_credit=match.artist,
            duration_ms=match.duration_ms,
        )
        session.add(recording)
        session.commit()
        session.refresh(recording)

    link = session.exec(
        select_link_by_file(file_id)
    ).first()
    if link is None:
        link = FileRecording(file_id=file_id, recording_id=recording.id, confidence=confidence, source=match.source)
        session.add(link)
        session.commit()
    else:
        link.recording_id = recording.id
        link.confidence = confidence
        link.source = match.source
        link.matched_at = now_utc()
        session.add(link)
        session.commit()
    return recording.id


def select_by_mbid(mbid: str):
    from sqlmodel import select

    from backend.models import Recording

    return select(Recording).where(Recording.musicbrainz_recording_id == mbid)


def select_link_by_file(file_id: int):
    from sqlmodel import select

    from backend.models import FileRecording

    return select(FileRecording).where(FileRecording.file_id == file_id)