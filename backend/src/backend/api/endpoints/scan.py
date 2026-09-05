from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from backend.core.paths import PathNotFoundError, PathPolicyError, validate_scan_directory
from backend.database.session import get_session
from backend.models.scan_job import ScanJob
from backend.repositories.job_repository import JobRepository
from backend.schemas.scan import ScanJobCreate, ScanJobRead

router = APIRouter(prefix="/scan", tags=["Scan"])


@router.post("", response_model=ScanJobRead, status_code=status.HTTP_202_ACCEPTED)
def start_directory_scan(
    payload: ScanJobCreate,
    session: Session = Depends(get_session),
):
    """Enqueue a directory scan job for the worker process (§23).

    The V1 response and polling contract (``/api/scan/status/{id}``) are
    unchanged; the legacy ``scan_jobs`` row remains the progress record.
    """
    try:
        dir_path = str(validate_scan_directory(payload.directory_path.strip()))
    except PathNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err
    except PathPolicyError as err:
        # Outside MUSIC_DIR (§27.1) — includes ``..``/symlink escapes.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(err),
        ) from err

    scan_job = ScanJob(directory_path=dir_path, status="pending")
    session.add(scan_job)
    session.commit()
    session.refresh(scan_job)

    JobRepository.enqueue(
        session,
        "scan",
        payload={
            "directory_path": dir_path,
            "perform_audio_analysis": payload.perform_audio_analysis,
            "scan_job_id": scan_job.id,
        },
    )

    return scan_job


@router.get("/status/{job_id}", response_model=ScanJobRead)
def get_scan_status(job_id: int, session: Session = Depends(get_session)):
    """Retrieve real-time status of a scan job."""
    job = session.get(ScanJob, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scan job with ID {job_id} not found.",
        )
    return job


@router.get("/jobs", response_model=list[ScanJobRead])
def list_scan_jobs(limit: int = 10, session: Session = Depends(get_session)):
    """List recent scan jobs."""
    query = select(ScanJob).order_by(ScanJob.id.desc()).limit(limit)
    jobs = session.exec(query).all()
    return list(jobs)
