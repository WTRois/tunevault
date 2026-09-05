"""SSE progress events tests (TV2-035, blueprint §19).

Running jobs produce an endless stream (the generator polls the jobs
table until a terminal status), so only terminal jobs are read
end-to-end here; the running / no-item-list shapes are covered by
direct unit tests of the event mapper instead.
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from backend.api.endpoints.events import _progress_event
from backend.main import app
from backend.models import Job


@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _seed_job(engine, **kwargs) -> int:
    defaults = {"job_type": "identify", "status": "completed", "progress": 100.0, "payload_json": {}}
    defaults.update(kwargs)
    with Session(engine) as session:
        job = Job(**defaults)
        session.add(job)
        session.commit()
        return job.id


def _client(engine, monkeypatch):
    from backend.api.endpoints import events as events_mod
    from backend.database.session import get_session

    monkeypatch.setattr(events_mod, "engine", engine)

    def get_test_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    return TestClient(app)


def _parse_events(lines: list[str]) -> list[dict]:
    return [json.loads(line.removeprefix("data: ")) for line in lines if line.startswith("data: ")]


def test_sse_unknown_job_is_404(engine, monkeypatch):
    try:
        with _client(engine, monkeypatch) as client:
            res = client.get("/api/jobs/999/events")
            assert res.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_sse_completed_job_emits_progress_then_completed(engine, monkeypatch):
    job_id = _seed_job(
        engine,
        payload_json={"file_ids": [1, 2, 3, 4], "current_file": "b.flac"},
    )
    try:
        with _client(engine, monkeypatch) as client, client.stream(
            "GET", f"/api/jobs/{job_id}/events"
        ) as res:
            assert res.status_code == 200
            assert res.headers["content-type"].startswith("text/event-stream")
            events = _parse_events(list(res.iter_lines()))
    finally:
        app.dependency_overrides.clear()

    assert events[0] == {
        "type": "job.progress",
        "job_id": job_id,
        "status": "completed",
        "completed": 4,
        "total": 4,
        "percent": 100.0,
        "current_file": "b.flac",
    }
    assert events[1]["type"] == "job.completed"
    assert events[1]["status"] == "completed"
    assert len(events) == 2


def test_progress_event_running_job_fields():
    """§19 shape on a mid-flight job: progress % maps onto completed/total."""
    job = Job(
        id=7,
        job_type="identify",
        status="running",
        progress=50.0,
        payload_json={"file_ids": [1, 2, 3, 4], "current_file": "Pink Floyd - Time.flac"},
    )
    assert _progress_event(job) == {
        "type": "job.progress",
        "job_id": 7,
        "status": "running",
        "completed": 2,
        "total": 4,
        "percent": 50.0,
        "current_file": "Pink Floyd - Time.flac",
    }


def test_progress_event_without_item_list_uses_nulls():
    """Organize jobs have no file_ids — completed/total stay null (§19 tolerant)."""
    job = Job(
        id=8,
        job_type="organize",
        status="running",
        progress=42.0,
        payload_json={"change_set_id": 7},
    )
    event = _progress_event(job)
    assert event["total"] is None
    assert event["completed"] is None
    assert event["percent"] == 42.0
    assert event["current_file"] is None