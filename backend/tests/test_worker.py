"""Integration tests for the worker process (TV2-007, blueprint §23)."""


import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from backend.models.job import Job
from backend.models.scan_job import ScanJob
from backend.repositories.job_repository import JobRepository
from backend.workers import scan_worker, worker


@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="music_dir")
def music_dir_fixture(tmp_path, monkeypatch):
    music = tmp_path / "music"
    music.mkdir()
    monkeypatch.setattr(worker, "engine", None)  # replaced per-test below
    return music


def test_scan_job_flows_through_worker(engine, tmp_path, monkeypatch):
    music = tmp_path / "music"
    music.mkdir()
    audio = music / "track.mp3"
    audio.write_bytes(b"\xff\xfb\x90\x44" + b"\x00" * 417)

    # Point both the worker loop and the scan logic at the test DB.
    monkeypatch.setattr(worker, "engine", engine)
    monkeypatch.setattr(scan_worker, "engine", engine)

    with Session(engine) as session:
        scan_job = ScanJob(directory_path=str(music), status="pending")
        session.add(scan_job)
        session.commit()
        session.refresh(scan_job)
        scan_job_id = scan_job.id

        JobRepository.enqueue(
            session,
            "scan",
            payload={
                "directory_path": str(music),
                "perform_audio_analysis": False,
                "scan_job_id": scan_job.id,
            },
        )

    assert worker.process_one_job() is True

    with Session(engine) as session:
        job = session.exec(select(Job)).one()
        assert job.status == "completed"
        assert job.result_json["scan_job_id"] == scan_job_id

        scan = session.get(ScanJob, scan_job_id)
        assert scan.status == "completed"
        assert scan.scanned_files == 1
        assert scan.added_count == 1

        # TV2-011b: the scan writes ONLY the V2 domain schema; no songs rows.
        from backend.models import File, FileRecording, Song

        file_row = session.exec(select(File)).one()
        assert file_row.filename == "track.mp3"
        assert file_row.filepath == str(music / "track.mp3")
        assert file_row.scan_state == "indexed"
        assert session.exec(select(Song)).all() == []
        link = session.exec(select(FileRecording)).first()
        assert link is None or link.file_id == file_row.id


def test_worker_returns_false_when_queue_empty(engine, monkeypatch):
    monkeypatch.setattr(worker, "engine", engine)
    assert worker.process_one_job() is False


def test_unknown_job_type_is_never_claimed(engine, monkeypatch):
    """The worker only claims job types with registered handlers (TV2-008);
    rows like 'download' (owned by BackgroundTasks) or unknown types stay pending."""
    monkeypatch.setattr(worker, "engine", engine)
    with Session(engine) as session:
        JobRepository.enqueue(session, "nonexistent_type", max_attempts=1)

    assert worker.process_one_job() is False

    with Session(engine) as session:
        job = session.exec(select(Job)).one()
        assert job.status == "pending"
        assert job.attempts == 0
        assert job.error_message is None