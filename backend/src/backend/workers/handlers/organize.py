"""Organize job handler — applies/undoes change sets via the worker (§23).

Progress is reported on the generic Job row so the UI can poll it.
"""

from loguru import logger
from sqlmodel import Session

from backend.models import Job
from backend.organization.apply import apply_change_set, undo_change_set


def handle_organize(session: Session, job: Job) -> dict:
    payload = job.payload_json or {}
    change_set_id = payload.get("change_set_id")
    if not change_set_id:
        raise ValueError("organize job payload requires change_set_id")

    def report(done: int, total: int, outcome: str) -> None:
        if total > 0:
            job.progress = min(99.0, done / total * 100.0)
        session.add(job)
        session.commit()

    if payload.get("undo"):
        result = undo_change_set(session, change_set_id, progress_cb=report)
    else:
        result = apply_change_set(session, change_set_id, progress_cb=report)
    logger.info(f"Organize job {job.id}: {result}")
    return result