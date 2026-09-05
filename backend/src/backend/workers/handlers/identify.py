"""Identification job handler (blueprint §7, Sprint 1 = recording-level).

For every file in scope: gather evidence (tags → filename → fingerprint) →
query providers (§26 cache) → score (§8) → persist candidates (§5.12).
Nothing is written to files or tags — accept flow only persists DB state.
"""

import asyncio
import time

from loguru import logger
from sqlmodel import Session

from backend.fingerprint.fpcalc import FpcalcUnavailable, compute_fingerprint
from backend.identification.candidates import generate_candidates, rank_candidates
from backend.identification.resolver import save_candidates
from backend.models import File
from backend.services.extractor import extract_metadata


def _tag_payload(session: Session, file: File) -> dict:
    """Current tag evidence for a file; missing/unreadable files fall back
    to filename-only evidence (identification must still proceed)."""
    try:
        meta = extract_metadata(file.filepath)
    except Exception:  # noqa: BLE001
        return {}
    return {
        "title": meta.get("title"),
        "artist": meta.get("artist"),
        "album": meta.get("album"),
        "track_number": meta.get("track_number"),
        "disc_number": meta.get("disc_number"),
        "musicbrainz_recording_id": meta.get("musicbrainz_recording_id"),
    }


def identify_file(session: Session, file: File) -> dict:
    """Identify one file (recording level). Returns the job item summary."""
    started = time.perf_counter()
    tags = _tag_payload(session, file)

    fingerprint = None
    try:
        result = compute_fingerprint(file.filepath)
        fingerprint = result.fingerprint
    except FpcalcUnavailable:
        logger.info(f"fpcalc unavailable — skipping fingerprint for {file.filepath}")
    except Exception as err:  # noqa: BLE001
        logger.warning(f"Fingerprint failed for {file.filepath}: {err}")

    identification, candidates = asyncio.run(
        generate_candidates(
            session,
            file,
            tags=tags,
            fingerprint=fingerprint,
        )
    )
    ranked = rank_candidates(identification, candidates)
    saved = save_candidates(session, file.id or 0, ranked)

    # §36 identification decision — one structured line per file, no PII.
    best = ranked[0] if ranked else None
    logger.bind(
        operation="identify",
        file_id=file.id,
        provider=best[3].source if best else "none",
        status="matched" if best else "no_match",
        score=round(float(best[0]), 1) if best else None,
        duration_ms=round((time.perf_counter() - started) * 1000),
    ).info(f"identify file_id={file.id} status={'matched' if best else 'no_match'}")

    return {
        "file_id": file.id,
        "candidates": len(saved),
        "best_score": float(ranked[0][0]) if ranked else None,
        "best_outcome": ranked[0][1] if ranked else None,
    }


def handle_identify(session: Session, job) -> dict:
    """Worker entry: identify files by file_id (song ids are files.id since TV2-011b)."""
    payload = dict(job.payload_json or {})
    file_ids = payload.get("file_ids") or []
    results = []
    for index, file_id in enumerate(file_ids):
        file = session.get(File, file_id)
        if file is None:
            results.append({"file_id": file_id, "error": "file not found"})
        else:
            results.append(identify_file(session, file))
        # §19 progress: percent + current file for the SSE stream (TV2-035).
        if file_ids:
            job.progress = min(99.0, (index + 1) / len(file_ids) * 100.0)
        payload["current_file"] = file.filename if file is not None else None
        job.payload_json = payload
        session.add(job)
        session.commit()
    return {"items": results}