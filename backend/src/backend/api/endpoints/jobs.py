"""Generic jobs API (blueprint §18 — Jobs section).

Only single-job polling is implemented for now; list/cancel/retry land
together with their UI consumers.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from backend.database.session import get_session
from backend.models import Job

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("/{job_id}")
def get_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found.")
    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "progress": job.progress,
        "result_json": job.result_json,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "completed_at": job.completed_at,
    }