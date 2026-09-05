"""Tests for the persistent job queue: atomic claim + retry (TV2-006, §23/§24)."""

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from backend.models.job import Job
from backend.repositories.job_repository import JobRepository


@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def test_enqueue_and_claim(engine):
    with Session(engine) as session:
        job = JobRepository.enqueue(session, "scan", {"directory_path": "/music"})
        assert job.id is not None
        assert job.status == "pending"

        claimed = JobRepository.claim_next_pending(session)
        assert claimed is not None
        assert claimed.id == job.id
        assert claimed.status == "running"
        assert claimed.attempts == 1
        assert claimed.started_at is not None


def test_claim_respects_priority_order(engine):
    with Session(engine) as session:
        low = JobRepository.enqueue(session, "scan", priority=0)
        high = JobRepository.enqueue(session, "identify", priority=10)

        claimed = JobRepository.claim_next_pending(session)
        assert claimed.id == high.id

        claimed2 = JobRepository.claim_next_pending(session)
        assert claimed2.id == low.id


def test_two_workers_never_claim_same_job(engine):
    """Two concurrent workers claiming from one job must get distinct jobs (§23)."""
    with Session(engine) as session:
        JobRepository.enqueue(session, "scan")
        JobRepository.enqueue(session, "scan")

    with Session(engine) as worker1, Session(engine) as worker2:
        claim1 = JobRepository.claim_next_pending(worker1)
        claim2 = JobRepository.claim_next_pending(worker2)
        assert claim1 is not None and claim2 is not None
        assert claim1.id != claim2.id


def test_second_claim_of_running_job_returns_none(engine):
    with Session(engine) as session:
        JobRepository.enqueue(session, "scan")

    with Session(engine) as worker1, Session(engine) as worker2:
        first = JobRepository.claim_next_pending(worker1)
        assert first is not None
        # Job is now running — the second worker must not get it.
        second = JobRepository.claim_next_pending(worker2)
        assert second is None


def test_mark_completed_and_failed(engine):
    with Session(engine) as session:
        job = JobRepository.enqueue(session, "scan")
        JobRepository.claim_next_pending(session)

        JobRepository.mark_completed(session, job.id, {"scanned": 5})
        done = session.get(Job, job.id)
        assert done.status == "completed"
        assert done.result_json == {"scanned": 5}
        assert done.progress == 100.0

        # A completed job is never re-claimed.
        assert JobRepository.claim_next_pending(session) is None


def test_failed_job_retries_until_max_attempts(engine):
    with Session(engine) as session:
        job = JobRepository.enqueue(session, "identify", max_attempts=2)

        # First failure → requeued (pending).
        JobRepository.claim_next_pending(session)
        JobRepository.mark_failed(session, job.id, "network error")
        requeued = session.get(Job, job.id)
        assert requeued.status == "pending"
        assert requeued.attempts == 1

        # Second failure → attempts (2) reached max (2) → failed.
        JobRepository.claim_next_pending(session)
        JobRepository.mark_failed(session, job.id, "network error")
        failed = session.get(Job, job.id)
        assert failed.status == "failed"
        assert failed.attempts == 2
        assert failed.error_message == "network error"
        assert failed.completed_at is not None