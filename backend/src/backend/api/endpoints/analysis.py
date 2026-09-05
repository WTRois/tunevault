"""Audio analysis API (blueprint §18 — Audio analysis, TV2-031).

    POST /api/files/{id}/analysis   — enqueue the full analyze job (§12)
    GET  /api/files/{id}/analysis   — technical metadata + features + the
                                      WARNING-ONLY upsample verdict (§12.3)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from backend.audio.ffmpeg import classify_lossless
from backend.audio.spectral import classify_upsample
from backend.database.session import get_session
from backend.models import AudioFeature, File
from backend.repositories.job_repository import JobRepository

router = APIRouter(prefix="/files", tags=["Analysis"])


def _resolve_file(session: Session, file_id: int) -> File:
    file = session.get(File, file_id)
    if file is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"File with ID {file_id} not found.")
    return file


@router.post("/{file_id}/analysis", status_code=status.HTTP_202_ACCEPTED)
def create_analysis(file_id: int, session: Session = Depends(get_session)):
    """Enqueue the full analysis job; the worker performs it (§12/§23)."""
    _resolve_file(session, file_id)
    job = JobRepository.enqueue(session, "analyze_audio", {"file_ids": [file_id]})
    return {"file_id": file_id, "job_id": job.id, "status": "queued"}


@router.get("/{file_id}/analysis")
def get_analysis(file_id: int, session: Session = Depends(get_session)):
    """Analysis state for one file. ``analyzed`` false until a full run
    has stamped the row (§37)."""
    file = _resolve_file(session, file_id)
    row = session.exec(
        select(AudioFeature).where(AudioFeature.file_id == file_id)
    ).first()

    features = None
    upsample = None
    if row is not None:
        features = {
            "bpm": row.bpm,
            "musical_key": row.musical_key,
            "integrated_lufs": row.integrated_lufs,
            "true_peak_db": row.true_peak_db,
            "replaygain_track_db": row.replaygain_track_db,
            "replaygain_album_db": row.replaygain_album_db,
            "dynamic_range": row.dynamic_range,
            "spectral_centroid": row.spectral_centroid,
            "frequency_ceiling_hz": row.frequency_ceiling_hz,
        }
        upsample = classify_upsample(
            file.sample_rate,
            float(row.frequency_ceiling_hz) if row.frequency_ceiling_hz is not None else None,
        )

    return {
        "file_id": file_id,
        "analyzed": row is not None,
        "technical": {
            "container": file.container,
            "codec": file.codec,
            "bitrate": file.bitrate,
            "sample_rate": file.sample_rate,
            "bit_depth": file.bit_depth,
            "channels": file.channels,
            "channel_layout": file.channel_layout,
            "duration_ms": file.duration_ms,
            "lossless": classify_lossless(file.codec),
        },
        "features": features,
        "upsample": upsample,
        "analysis_version": row.analysis_version if row else None,
        "analyzed_at": row.analyzed_at if row else None,
    }