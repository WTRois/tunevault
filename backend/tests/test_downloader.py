from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from backend.database.session import get_session
from backend.main import app
from backend.models.job import Job
from backend.services.downloader import (
    create_download_job,
    delete_download_job,
    get_download_job,
    sanitize_filename,
)


@pytest.fixture(name="client")
def client_fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def get_test_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_sanitize_filename():
    assert sanitize_filename("Artist / Title?") == "Artist  Title"
    assert sanitize_filename('Track: "Cool" <Song>|') == "Track Cool Song"
    assert sanitize_filename("") == "downloaded_track"


def test_download_preview_validation(client: TestClient):
    with patch("backend.api.endpoints.downloader.fetch_url_preview") as mock_preview:
        mock_preview.return_value = MagicMock(
            url="https://youtube.com/watch?v=dQw4w9WgXcQ",
            title="Sample Track",
            artist="Sample Artist",
            album="Sample Album",
            duration=180.0,
            thumbnail_url="https://img.youtube.com/vi/dQw4w9WgXcQ/0.jpg",
            source_bitrate_estimate=192,
        )
        res = client.post(
            "/api/download/preview", json={"url": "https://youtube.com/watch?v=dQw4w9WgXcQ"}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["title"] == "Sample Track"
        assert data["artist"] == "Sample Artist"


def test_download_job_creation_and_status(client: TestClient):
    # Test invalid bitrate
    res_bad_bitrate = client.post(
        "/api/download",
        json={"url": "https://music.youtube.com/watch?v=abc", "bitrate": 500},
    )
    assert res_bad_bitrate.status_code == 400

    # Test invalid scheme
    res_bad_scheme = client.post(
        "/api/download",
        json={"url": "ftp://invalid-url.com", "bitrate": 192},
    )
    assert res_bad_scheme.status_code == 400

    # Test successful creation
    with patch("backend.services.downloader.process_download_job"):
        res = client.post(
            "/api/download",
            json={
                "url": "https://music.youtube.com/watch?v=xyz123",
                "bitrate": 320,
                "title_override": "Custom Title",
                "artist_override": "Custom Artist",
                "auto_import": False,
            },
        )
        assert res.status_code == 202
        data = res.json()
        assert "job_id" in data
        assert data["bitrate"] == 320
        job_id = data["job_id"]

        # Check job status endpoint
        res_job = client.get(f"/api/download/jobs/{job_id}")
        assert res_job.status_code == 200
        assert res_job.json()["job_id"] == job_id

        # Delete job
        res_del = client.delete(f"/api/download/jobs/{job_id}")
        assert res_del.status_code == 204

        # Verify job deleted (API contract: GET now returns 404)
        assert client.get(f"/api/download/jobs/{job_id}").status_code == 404


def test_download_job_store_lifecycle():
    from backend.schemas.downloader import DownloadJobCreate

    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)

    req = DownloadJobCreate(
        url="https://youtube.com/watch?v=test",
        bitrate=256,
        title_override="Test Title",
        artist_override="Test Artist",
    )
    job_id = create_download_job(req, db_engine=test_engine)
    assert job_id.startswith("job_")

    job = get_download_job(job_id, db_engine=test_engine)
    assert job is not None
    assert job["url"] == "https://youtube.com/watch?v=test"
    assert job["bitrate"] == 256
    assert job["status"] == "pending"
    assert job["progress_percent"] == 0.0

    deleted = delete_download_job(job_id, db_engine=test_engine)
    assert deleted is True
    assert get_download_job(job_id, db_engine=test_engine) is None


def test_download_job_survives_restart(tmp_path):
    """TV2-008 acceptance: a backend restart must not lose download job status."""
    from backend.schemas.downloader import DownloadJobCreate

    db_url = f"sqlite:///{tmp_path / 'restart.db'}"
    engine1 = create_engine(db_url)
    SQLModel.metadata.create_all(engine1)

    req = DownloadJobCreate(url="https://youtube.com/watch?v=test", bitrate=192)
    job_id = create_download_job(req, db_engine=engine1)

    # Simulate a backend restart: a brand-new engine on the same DB file
    engine2 = create_engine(db_url)
    job = get_download_job(job_id, db_engine=engine2)
    assert job is not None
    assert job["job_id"] == job_id
    assert job["status"] == "pending"
    assert job["url"] == "https://youtube.com/watch?v=test"
    assert job["bitrate"] == 192

    assert delete_download_job(job_id, db_engine=engine2) is True


def test_worker_never_claims_download_jobs():
    """Download rows stay pending: they are owned by BackgroundTasks, not the worker (§23)."""
    from sqlmodel import Session

    from backend.repositories.job_repository import JobRepository

    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)

    with Session(test_engine) as session:
        download_row = JobRepository.enqueue(session, "download", {"url": "https://x"})
        scan_row = JobRepository.enqueue(session, "scan", {})

        # A worker handling only scan/identify claims the scan row first (older id)
        claimed = JobRepository.claim_next_pending(session, ["scan", "identify"])
        assert claimed is not None
        assert claimed.id == scan_row.id

        # The download row is untouched and still pending
        assert JobRepository.claim_next_pending(session, ["scan", "identify"]) is None
        refreshed = session.get(Job, download_row.id)
        assert refreshed.status == "pending"
