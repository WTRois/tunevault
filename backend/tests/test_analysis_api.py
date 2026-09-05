"""Audio analysis API E2E (TV2-031, blueprint §18): POST → worker → GET."""

import subprocess
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from backend.core.config import settings
from backend.core.versions import ANALYSIS_VERSION
from backend.database.session import get_session
from backend.main import app
from backend.models import AudioFeature, File
from backend.services.scanner import calculate_sha256
from backend.workers import worker

FFMPEG = settings.FFMPEG_PATH


def _ffmpeg_available() -> bool:
    try:
        subprocess.run([FFMPEG, "-version"], capture_output=True, timeout=10, check=False)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


pytestmark = pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg binary not available")


@pytest.fixture(name="client")
def client_fixture(tmp_path, monkeypatch):
    music = tmp_path / "music"
    music.mkdir()
    source = music / "tone.flac"
    subprocess.run(
        [
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "aevalsrc=0.5*sin(2*PI*1000*t):s=48000:d=2",
            "-c:a", "flac", str(source),
        ],
        check=True,
    )

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(worker, "engine", engine)

    with Session(engine) as session:
        session.add(
            File(
                filepath=str(source),
                filename="tone.flac",
                extension=".flac",
                sha256=calculate_sha256(str(source)),
                file_size=source.stat().st_size,
                modified_at=datetime.now(UTC),
                scan_state="indexed",
            )
        )
        session.commit()

    def get_test_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_analysis_e2e(client: TestClient):
    # 1. Before: not analyzed, technical columns still empty.
    res = client.get("/api/files/1/analysis")
    assert res.status_code == 200
    body = res.json()
    assert body["analyzed"] is False
    assert body["features"] is None
    assert body["technical"]["sample_rate"] is None

    # 2. Enqueue the full analysis job.
    res = client.post("/api/files/1/analysis")
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    # 3. Worker processes it; the generic jobs endpoint reports completion.
    assert worker.process_one_job() is True
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "completed"
    assert job["result_json"]["items"][0]["status"] == "analyzed"

    # 4. Full analysis is now visible (§12.1/§12.2/§12.3 + §37 versioning).
    body = client.get("/api/files/1/analysis").json()
    assert body["analyzed"] is True
    assert body["analysis_version"] == ANALYSIS_VERSION
    assert body["technical"]["sample_rate"] == 48000  # enriched via ffprobe
    # aevalsrc outputs float32 → the FLAC encoder stores it as 24-bit.
    assert body["technical"]["bit_depth"] == 24
    assert body["technical"]["lossless"] is True
    assert body["features"]["integrated_lufs"] is not None
    assert body["features"]["true_peak_db"] is not None
    assert body["features"]["spectral_centroid"] is not None
    # 48 kHz container → standard-res → never a hi-res suspicion.
    assert body["upsample"]["status"] == "normal"


def test_analysis_idempotent(client: TestClient):
    client.post("/api/files/1/analysis")
    assert worker.process_one_job() is True
    before = client.get("/api/files/1/analysis").json()

    # Second run: enqueued fine, but the worker skips — nothing re-analyzed.
    client.post("/api/files/1/analysis")
    assert worker.process_one_job() is True
    job = client.get("/api/jobs/2").json()
    assert job["result_json"]["items"][0] == {
        "file_id": 1,
        "status": "skipped",
        "reason": "up_to_date",
    }

    after = client.get("/api/files/1/analysis").json()
    assert after["analyzed_at"] == before["analyzed_at"]


def test_version_bump_forces_reanalysis(client: TestClient):
    client.post("/api/files/1/analysis")
    assert worker.process_one_job() is True

    # Simulate an algorithm change (§37): the stored row is now outdated.
    with Session(worker.engine) as session:
        row = session.exec(
            select(AudioFeature).where(AudioFeature.file_id == 1)
        ).one()
        row.analysis_version = "1.0.0"
        session.add(row)
        session.commit()

    client.post("/api/files/1/analysis")
    assert worker.process_one_job() is True
    job = client.get("/api/jobs/2").json()
    assert job["result_json"]["items"][0]["status"] == "analyzed"
    assert client.get("/api/files/1/analysis").json()["analysis_version"] == ANALYSIS_VERSION


def test_unknown_file_404(client: TestClient):
    assert client.get("/api/files/999/analysis").status_code == 404
    assert client.post("/api/files/999/analysis").status_code == 404
    assert client.get("/api/jobs/9999").status_code == 404