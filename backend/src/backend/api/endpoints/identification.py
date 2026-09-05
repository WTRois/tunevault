"""Identification API (blueprint §18 — Identification section).

Since the compat repository flip (TV2-011b), ``song_id`` IS ``files.id``;
V1 clients keep working because the repository serves the same id space.
"""

import asyncio
import json
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from backend.database.session import get_session
from backend.identification.release_match import (
    RELEASE_PREFERENCES,
    match_release,
    release_preferences,
)
from backend.identification.resolver import resolve_recording, write_recording_link
from backend.models import AppSetting, File, Job, MetadataCandidate
from backend.providers.base import ProviderMatch
from backend.providers.musicbrainz import MusicBrainzProvider
from backend.repositories.job_repository import JobRepository
from backend.schemas.identification import (
    AcceptResponse,
    BulkAcceptRequest,
    BulkAcceptResponse,
    CandidateRead,
    IdentificationJobCreate,
    IdentificationJobRead,
    ReleasePreferences,
    ReviewCandidateRead,
)

router = APIRouter(prefix="/identification", tags=["Identification"])


def _release_provider() -> MusicBrainzProvider | None:
    """Provider used for release matching; tests may stub this (TV2-018)."""
    return MusicBrainzProvider()


def _resolve_file(session: Session, song_id: int) -> File:
    """V1 song id → V2 file row. Post TV2-011b: song ids are files.id."""
    file = session.get(File, song_id)
    if file is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Song with ID {song_id} not found.")
    return file


@router.post("/jobs", response_model=IdentificationJobRead, status_code=status.HTTP_202_ACCEPTED)
def create_identification_job(
    payload: IdentificationJobCreate,
    session: Session = Depends(get_session),
):
    """Enqueue an identification job (recording-level, §7)."""
    file_ids = list(payload.file_ids)
    for song_id in payload.song_ids:
        file = _resolve_file(session, song_id)
        file_ids.append(file.id)

    if not file_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="No files to identify.")

    job = JobRepository.enqueue(session, "identify", payload={"file_ids": file_ids})
    return job


@router.get("/jobs/{job_id}", response_model=IdentificationJobRead)
def get_identification_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if job is None or job.job_type != "identify":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Identification job {job_id} not found.")
    return job


@router.get("/songs/{song_id}/candidates", response_model=list[CandidateRead])
def list_candidates(song_id: int, session: Session = Depends(get_session)):
    file = _resolve_file(session, song_id)
    rows = session.exec(
        select(MetadataCandidate)
        .where(MetadataCandidate.file_id == file.id)
        .order_by(MetadataCandidate.score.desc())
    ).all()
    return [_candidate_read(row) for row in rows]


@router.post("/songs/{song_id}/identify", response_model=IdentificationJobRead,
             status_code=status.HTTP_202_ACCEPTED)
def identify_song(song_id: int, session: Session = Depends(get_session)):
    """Enqueue identification for a single V1 song."""
    file = _resolve_file(session, song_id)
    job = JobRepository.enqueue(session, "identify", payload={"file_ids": [file.id]})
    return job


@router.post("/songs/{song_id}/candidates/{candidate_id}/accept", response_model=AcceptResponse)
def accept_candidate(song_id: int, candidate_id: int, session: Session = Depends(get_session)):
    """Accept a candidate: persist resolution + provenance + recording link.

    Never touches the filesystem or tags (Change Plan lands with TV2-026).
    """
    file = _resolve_file(session, song_id)
    row = session.get(MetadataCandidate, candidate_id)
    if row is None or row.file_id != file.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Candidate {candidate_id} not found.")
    return _accept_row(session, file, row)


def _accept_row(session: Session, file: File, row: MetadataCandidate) -> AcceptResponse:
    """Shared accept flow for single + bulk review (§22): resolve recording,
    write the file link, then best-effort §10 release matching."""
    match = ProviderMatch.from_dict(json.loads(row.payload_json))
    resolved = resolve_recording(session, file, row, user_confirmed=True)
    recording_id = write_recording_link(
        session, file.id or 0, match, confidence=Decimal(str(row.score))
    )

    # §10: after the recording, resolve the release (TV2-018). Best effort —
    # release rows land when the provider tracklist confirms the recording.
    try:
        release_info = asyncio.run(
            match_release(
                session,
                file,
                match,
                provider=_release_provider(),
                recording_row_id=recording_id,
                source=row.source,
                confidence=Decimal(str(row.score)),
            )
        )
    except Exception as err:  # noqa: BLE001
        release_info = None
        from loguru import logger

        logger.warning(f"Release matching skipped for file {file.id}: {err}")

    return AcceptResponse(
        accepted=True,
        file_id=file.id or 0,
        resolved=resolved,
        recording_id=recording_id,
        release=release_info,
    )


@router.post("/songs/{song_id}/candidates/{candidate_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
def reject_candidate(song_id: int, candidate_id: int, session: Session = Depends(get_session)):
    file = _resolve_file(session, song_id)
    row = session.get(MetadataCandidate, candidate_id)
    if row is None or row.file_id != file.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Candidate {candidate_id} not found.")
    row.status = "rejected"
    session.add(row)
    session.commit()


def _candidate_read(row: MetadataCandidate) -> CandidateRead:
    payload = json.loads(row.payload_json)
    return CandidateRead(
        id=row.id or 0,
        file_id=row.file_id,
        source=row.source,
        score=row.score,
        confidence_level=row.confidence_level,
        status=row.status,
        recording_mbid=payload.get("recording_mbid"),
        title=payload.get("title"),
        artist=payload.get("artist"),
        release_title=payload.get("release_title"),
    )


@router.get("/review", response_model=list[ReviewCandidateRead])
def list_review_queue(
    confidence_level: str | None = None,
    source: str | None = None,
    min_score: float | None = None,
    session: Session = Depends(get_session),
):
    """Pending candidates across all files (§22 review queue), best first."""
    query = select(MetadataCandidate).where(MetadataCandidate.status == "pending")
    if confidence_level:
        query = query.where(MetadataCandidate.confidence_level == confidence_level)
    if source:
        query = query.where(MetadataCandidate.source == source)
    if min_score is not None:
        query = query.where(MetadataCandidate.score >= min_score)
    query = query.order_by(MetadataCandidate.score.desc(), MetadataCandidate.id)

    items: list[ReviewCandidateRead] = []
    for row in session.exec(query).all():
        file = session.get(File, row.file_id)
        if file is None:
            continue
        payload = json.loads(row.payload_json)
        items.append(
            ReviewCandidateRead(
                id=row.id or 0,
                file_id=row.file_id,
                filename=file.filename,
                filepath=file.filepath,
                source=row.source,
                score=row.score,
                confidence_level=row.confidence_level,
                status=row.status,
                recording_mbid=payload.get("recording_mbid"),
                title=payload.get("title"),
                artist=payload.get("artist"),
                release_title=payload.get("release_title"),
            )
        )
    return items


@router.post("/review/bulk-accept", response_model=BulkAcceptResponse)
def bulk_accept(payload: BulkAcceptRequest, session: Session = Depends(get_session)):
    """Accept pending candidates in bulk (§22).

    Explicit ``candidate_ids`` are accepted as given (non-pending rows are
    skipped); otherwise the filter picks the best pending candidate per file —
    the other candidates stay pending for manual review.
    """
    accepted: list[AcceptResponse] = []
    errors: list[str] = []
    skipped = 0

    if payload.candidate_ids:
        for candidate_id in payload.candidate_ids:
            row = session.get(MetadataCandidate, candidate_id)
            if row is None or row.status != "pending":
                skipped += 1
                continue
            file = session.get(File, row.file_id)
            if file is None:
                skipped += 1
                continue
            try:
                accepted.append(_accept_row(session, file, row))
            except Exception as err:  # noqa: BLE001
                errors.append(f"Candidate {candidate_id}: {err}")
        return BulkAcceptResponse(accepted=accepted, skipped=skipped, errors=errors)

    query = select(MetadataCandidate).where(MetadataCandidate.status == "pending")
    if payload.confidence_level:
        query = query.where(MetadataCandidate.confidence_level == payload.confidence_level)
    if payload.min_score is not None:
        query = query.where(MetadataCandidate.score >= payload.min_score)
    rows = session.exec(query.order_by(MetadataCandidate.score.desc())).all()

    best_per_file: dict[int, MetadataCandidate] = {}
    for row in rows:  # highest score per file wins (rows are score-ordered)
        best_per_file.setdefault(row.file_id, row)

    for row in best_per_file.values():
        file = session.get(File, row.file_id)
        if file is None:
            skipped += 1
            continue
        try:
            accepted.append(_accept_row(session, file, row))
        except Exception as err:  # noqa: BLE001
            errors.append(f"Candidate {row.id}: {err}")
    skipped += len(rows) - len(accepted)
    return BulkAcceptResponse(accepted=accepted, skipped=skipped, errors=errors)


@router.get("/release-preferences", response_model=ReleasePreferences)
def get_release_preferences(session: Session = Depends(get_session)):
    """Effective §10 release preferences (app_settings overrides → config)."""
    return ReleasePreferences(**release_preferences(session))


@router.put("/release-preferences", response_model=ReleasePreferences)
def update_release_preferences(
    payload: ReleasePreferences, session: Session = Depends(get_session)
):
    """Persist §10 release preferences as app_settings overrides (TV2-036)."""
    if payload.preference not in RELEASE_PREFERENCES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"preference must be one of: {', '.join(RELEASE_PREFERENCES)}",
        )
    for key, value in (
        ("release_preference", payload.preference),
        ("release_preference_country", payload.country),
        ("release_preference_label", payload.label),
    ):
        row = session.get(AppSetting, key)
        if row is None:
            row = AppSetting(key=key, value=value)
        else:
            row.value = value
        session.add(row)
    session.commit()
    return ReleasePreferences(**release_preferences(session))