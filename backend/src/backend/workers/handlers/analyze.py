"""Analyze job handler — full audiophile analysis (blueprint §12, TV2-031).

The scan keeps its fast pass (BPM/key); this is the separate full
analysis job (§12): ffprobe technical metadata → ebur128 loudness →
ReplayGain → spectral/upsample, stamped with ANALYSIS_VERSION (§37).

Idempotency (§24): a file whose features are current — matching version
AND already loudness-analyzed — is skipped, so running the job twice
analyses nothing the second time.
"""

from loguru import logger
from sqlmodel import Session, select

from backend.audio.ffmpeg import FFmpegToolError, probe_technical_metadata
from backend.audio.loudness import analyze_loudness
from backend.audio.spectral import analyze_spectral
from backend.core.versions import ANALYSIS_VERSION
from backend.models import AudioFeature, File
from backend.services.analyzer import analyze_audio_features
from backend.services.file_indexer import save_audio_features

# File columns enriched from ffprobe output (§12.1).
_TECHNICAL_COLUMNS = (
    "container",
    "codec",
    "bitrate",
    "sample_rate",
    "bit_depth",
    "channels",
    "channel_layout",
)


def _features_current(session: Session, file_id: int) -> bool:
    row = session.exec(
        select(AudioFeature).where(AudioFeature.file_id == file_id)
    ).first()
    if row is None:
        return False
    # Current version AND the full analysis actually ran (loudness filled).
    return row.analysis_version == ANALYSIS_VERSION and row.integrated_lufs is not None


def analyze_file(session: Session, file: File) -> dict:
    """Full §12 analysis for one file: technical + loudness + spectral."""
    technical = probe_technical_metadata(file.filepath)

    for column in _TECHNICAL_COLUMNS:
        value = technical.get(column)
        if value is not None:
            setattr(file, column, value)
    duration = technical.get("duration")
    if duration is not None:
        file.duration_ms = round(duration * 1000)
    session.add(file)

    features: dict = analyze_audio_features(file.filepath, duration)
    features.update(analyze_loudness(file.filepath))
    features.update(analyze_spectral(file.filepath, duration))
    save_audio_features(session, file.id or 0, features)
    return {"file_id": file.id, "status": "analyzed", "lossless": technical.get("lossless")}


def handle_analyze(session: Session, job) -> dict:
    """Worker entry: full analysis for file_ids, idempotent per file."""
    payload = dict(job.payload_json or {})
    file_ids = payload.get("file_ids") or []
    items = []
    for index, file_id in enumerate(file_ids):
        file = session.get(File, file_id)
        if file is None:
            items.append({"file_id": file_id, "status": "skipped", "reason": "file not found"})
        elif _features_current(session, file_id):
            items.append({"file_id": file_id, "status": "skipped", "reason": "up_to_date"})
        else:
            try:
                items.append(analyze_file(session, file))
            except FFmpegToolError as err:
                logger.warning(f"Analysis failed for file {file_id}: {err}")
                items.append({"file_id": file_id, "status": "error", "error": str(err)})
        # §19 progress: percent + current file for the SSE stream (TV2-035).
        job.progress = min(99.0, (index + 1) / len(file_ids) * 100.0)
        payload["current_file"] = file.filename if file is not None else None
        job.payload_json = payload
        session.add(job)
        session.commit()
    return {"items": items}