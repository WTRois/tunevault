"""Organization API (blueprint §18 — Organization section, TV2-027).

    POST /api/organization/preview          — pure-data §15 plans
    POST /api/organization/apply            — persist change set + enqueue job
    POST /api/organization/undo/{id}         — enqueue rollback job (§16)
    GET  /api/change-sets                    — history listing
    GET  /api/change-sets/{id}              — detail with changes
    GET  /api/organization/jobs/{job_id}    — apply/undo progress polling
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from backend.database.session import get_session
from backend.models import Change, ChangeSet, File, MetadataProvenance
from backend.organization.change_plan import persist_change_set, preview_plans
from backend.repositories.job_repository import JobRepository

router = APIRouter(prefix="/organization", tags=["Organization"])
change_sets_router = APIRouter(prefix="/change-sets", tags=["Organization"])


class OrganizationRequest(BaseModel):
    song_ids: list[int] = Field(default_factory=list, description="V1 song ids (= files.id)")
    file_ids: list[int] = Field(default_factory=list, description="V2 file ids")
    all: bool = Field(default=False, description="Preview/apply every identified file")
    name: str | None = Field(default=None, description="Change set name (apply only)")


class ChangeSetRead(BaseModel):
    id: int
    name: str
    status: str
    created_by: str = "system"
    created_at: datetime
    applied_at: datetime | None = None
    rolled_back_at: datetime | None = None


class ChangeRead(BaseModel):
    id: int
    file_id: int
    operation: str
    old_path: str | None
    new_path: str | None
    verification_status: str | None
    backup_path: str | None = None


def _resolve_file_ids(session: Session, request: OrganizationRequest) -> list[int]:
    """Post TV2-011b: song ids ARE file ids; ``all`` widens to every
    identified file (files with provenance rows)."""
    resolved = list(request.file_ids)
    for song_id in request.song_ids:
        if session.get(File, song_id) is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail=f"Song with ID {song_id} not found."
            )
        resolved.append(song_id)
    if request.all:
        rows = session.exec(
            select(MetadataProvenance.file_id).distinct()
        ).all()
        resolved.extend(row for row in rows if row not in resolved)
    return resolved


@router.post("/preview")
def preview(request: OrganizationRequest, session: Session = Depends(get_session)):
    """Build change plans (§15). Pure data — no filesystem access."""
    file_ids = _resolve_file_ids(session, request)
    if not file_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="No files to preview.")
    return preview_plans(session, file_ids)


@router.post("/apply", status_code=status.HTTP_202_ACCEPTED)
def apply(request: OrganizationRequest, session: Session = Depends(get_session)):
    """Persist a change set from §15 plans and enqueue the apply job.

    The worker performs the copy-first apply; ORGANIZE_DRY_RUN=true keeps
    every filesystem write refused (§15).
    """
    file_ids = _resolve_file_ids(session, request)
    if not file_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="No files to apply.")

    result = preview_plans(session, file_ids)
    plans = result["plans"]
    actionable = [p for p in plans if "error" not in p and "skipped" not in p]
    if not actionable:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Nothing to apply — no identified files in scope.",
        )

    name = request.name or f"organize-{len(actionable)}-files"
    change_set = persist_change_set(session, plans, name)
    job = JobRepository.enqueue(
        session,
        "organize",
        payload={"change_set_id": change_set.id},
    )
    return {
        "change_set_id": change_set.id,
        "name": change_set.name,
        "job_id": job.id,
        "dry_run": result["dry_run"],
        "queued_files": len(actionable),
    }


@router.post("/undo/{change_set_id}", status_code=status.HTTP_202_ACCEPTED)
def undo(change_set_id: int, session: Session = Depends(get_session)):
    """Enqueue an undo job for an applied change set (§16 rollback)."""
    change_set = session.get(ChangeSet, change_set_id)
    if change_set is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"Change set {change_set_id} not found."
        )
    if change_set.status not in ("applied", "partial", "failed"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Change set status is '{change_set.status}' — nothing to undo.",
        )
    job = JobRepository.enqueue(
        session,
        "organize",
        payload={"change_set_id": change_set_id, "undo": True},
    )
    return {"change_set_id": change_set_id, "job_id": job.id}


@router.get("/jobs/{job_id}")
def get_organize_job(job_id: int, session: Session = Depends(get_session)):
    """Poll apply/undo progress (mirror of the identification job read)."""
    from backend.models import Job

    job = session.get(Job, job_id)
    if job is None or job.job_type != "organize":
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


@change_sets_router.get("")
def list_change_sets(session: Session = Depends(get_session)):
    rows = session.exec(
        select(ChangeSet).order_by(ChangeSet.id.desc())
    ).all()
    return [
        ChangeSetRead(
            id=row.id or 0,
            name=row.name,
            status=row.status,
            created_by=row.created_by,
            created_at=row.created_at,
            applied_at=row.applied_at,
            rolled_back_at=row.rolled_back_at,
        )
        for row in rows
    ]


@change_sets_router.get("/{change_set_id}")
def get_change_set(change_set_id: int, session: Session = Depends(get_session)):
    change_set = session.get(ChangeSet, change_set_id)
    if change_set is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"Change set {change_set_id} not found."
        )
    changes = session.exec(
        select(Change).where(Change.change_set_id == change_set_id).order_by(Change.id)
    ).all()
    return {
        **ChangeSetRead(
            id=change_set.id or 0,
            name=change_set.name,
            status=change_set.status,
            created_by=change_set.created_by,
            created_at=change_set.created_at,
            applied_at=change_set.applied_at,
            rolled_back_at=change_set.rolled_back_at,
        ).model_dump(),
        "changes": [
            ChangeRead(
                id=c.id or 0,
                file_id=c.file_id,
                operation=c.operation,
                old_path=c.old_path,
                new_path=c.new_path,
                verification_status=c.verification_status,
                backup_path=c.backup_path,
            ).model_dump()
            for c in changes
        ],
    }