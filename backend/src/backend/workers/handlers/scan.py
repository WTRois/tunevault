"""Scan job handler — bridges the generic job queue to the V1 scan worker logic."""

from sqlmodel import Session

from backend.models.job import Job
from backend.models.scan_job import ScanJob
from backend.workers.scan_worker import run_scan_job


def handle_scan(session: Session, job: Job) -> dict:
    """Run a directory scan; granular progress is reported via the legacy
    ``scan_jobs`` row so the V1 polling contract (``/api/scan/status/{id}``)
    stays intact."""
    payload = job.payload_json or {}
    scan_job_id = payload.get("scan_job_id")
    run_scan_job(
        job_id=scan_job_id,
        directory_path=payload["directory_path"],
        perform_audio_analysis=payload.get("perform_audio_analysis", True),
    )

    scan_job = session.get(ScanJob, scan_job_id) if scan_job_id else None
    return {
        "scan_job_id": scan_job_id,
        "added_count": scan_job.added_count if scan_job else None,
        "updated_count": scan_job.updated_count if scan_job else None,
        "error_count": scan_job.error_count if scan_job else None,
    }