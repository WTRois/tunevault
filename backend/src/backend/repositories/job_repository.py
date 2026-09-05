"""Job queue repository — atomic claim per blueprint §23, retry policy per §24."""

from typing import Any

from sqlmodel import Session, select, update

from backend.core.time import now_utc
from backend.models.job import Job, JobItem


class JobRepository:
    @staticmethod
    def enqueue(
        session: Session,
        job_type: str,
        payload: dict[str, Any] | None = None,
        priority: int = 0,
        max_attempts: int = 3,
    ) -> Job:
        """Insert a pending job row (worker processes it asynchronously)."""
        job = Job(
            job_type=job_type,
            status="pending",
            priority=priority,
            payload_json=payload or {},
            max_attempts=max_attempts,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return job

    @staticmethod
    def claim_next_pending(session: Session, job_types: list[str] | None = None) -> Job | None:
        """Atomically claim the oldest highest-priority pending job (§23).

        The guarded UPDATE (``WHERE id=? AND status='pending'``) ensures two
        workers can never claim the same job; a rowcount of 0 means another
        worker won the race. ``job_types`` restricts the claim to types the
        caller has handlers for (e.g. in-process ``download`` jobs owned by
        BackgroundTasks must never be claimed by the worker).
        """
        query = (
            select(Job.id)
            .where(Job.status == "pending")
            .order_by(Job.priority.desc(), Job.id)
            .limit(20)
        )
        if job_types is not None:
            query = query.where(Job.job_type.in_(job_types))
        pending = session.exec(query).all()
        for job_id in pending:
            result = session.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == "pending")
                .values(status="running", started_at=now_utc(), attempts=Job.attempts + 1)
            )
            if result.rowcount == 1:
                session.commit()
                return session.get(Job, job_id)
        return None

    @staticmethod
    def mark_completed(session: Session, job_id: int, result: dict[str, Any] | None = None) -> None:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = "completed"
        job.progress = 100.0
        job.result_json = result or {}
        job.completed_at = now_utc()
        session.add(job)
        session.commit()

    @staticmethod
    def mark_failed(session: Session, job_id: int, error: str) -> None:
        """Mark a job failed, or requeue it for retry while attempts remain (§24)."""
        job = session.get(Job, job_id)
        if job is None:
            return
        if job.attempts < job.max_attempts:
            job.status = "pending"
            job.error_message = error
        else:
            job.status = "failed"
            job.error_message = error
            job.completed_at = now_utc()
        session.add(job)
        session.commit()


def claim_next_pending(session: Session, job_types: list[str] | None = None) -> Job | None:
    """Module-level convenience wrapper for the worker loop."""
    return JobRepository.claim_next_pending(session, job_types)


__all__ = ["Job", "JobItem", "JobRepository", "claim_next_pending"]