"""SSE job progress events (blueprint §19, TV2-035).

The backend and worker run as separate processes (§30), so progress is
transported through the ``jobs`` table: this endpoint polls the row and
streams ``job.progress`` events until the job reaches a terminal status,
then emits ``job.completed`` / ``job.failed`` and closes the stream.

Event shape (§19)::

    {"type": "job.progress", "job_id": 42, "completed": 152, "total": 1000,
     "percent": 15.2, "current_file": "Pink Floyd - Time.flac"}

The frontend treats SSE as primary and polling as fallback (§19); the
plain ``GET /api/jobs/{job_id}`` endpoint remains the safety net.
"""

import asyncio
import json
import math
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from backend.database import session as _engine_module
from backend.database.session import get_session
from backend.models import Job

# Resolved at call time so tests can point the stream at their own engine;
# production always uses the app-wide engine (worker is a separate process).
engine = _engine_module.engine

router = APIRouter(prefix="/jobs", tags=["Jobs"])

POLL_INTERVAL_SECONDS = 1.0
TERMINAL_STATUSES = ("completed", "failed", "cancelled")


def _progress_event(job: Job) -> dict[str, Any]:
    """Map a Job row onto the §19 event payload."""
    payload = job.payload_json or {}
    file_ids = payload.get("file_ids") or []
    total: int | None = len(file_ids) if file_ids else None
    completed: int | None = (
        min(len(file_ids), math.floor(job.progress / 100.0 * len(file_ids)))
        if file_ids
        else None
    )
    return {
        "type": "job.progress",
        "job_id": job.id,
        "status": job.status,
        "completed": completed,
        "total": total,
        "percent": round(job.progress, 1),
        "current_file": payload.get("current_file"),
    }


async def _stream_events(job_id: int) -> AsyncGenerator[str, None]:
    """Poll the job row and yield SSE frames until terminal status."""
    while True:
        with Session(engine) as session:
            job = session.get(Job, job_id)
        if job is None:
            # Deleted between the 404 check and a later poll: report and stop.
            yield _sse_frame({"type": "job.failed", "job_id": job_id, "status": "not_found"})
            return
        yield _sse_frame(_progress_event(job))
        if job.status in TERMINAL_STATUSES:
            yield _sse_frame(
                {
                    "type": "job.completed" if job.status == "completed" else "job.failed",
                    "job_id": job_id,
                    "status": job.status,
                    "error_message": job.error_message,
                }
            )
            return
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


def _sse_frame(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@router.get("/{job_id}/events")
def stream_job_events(job_id: int, _session: Session = Depends(get_session)):
    """SSE stream of §19 progress events for one job."""
    if _session.get(Job, job_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found.")
    return StreamingResponse(
        _stream_events(job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )