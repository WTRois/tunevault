"""Organization API E2E (TV2-027, blueprint §18): preview → apply (worker) → undo."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mutagen.id3 import ID3
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from backend.core.config import settings
from backend.database.session import get_session
from backend.main import app
from backend.models import File, MetadataProvenance
from backend.services.scanner import calculate_sha256
from backend.workers import worker


def _dummy_mp3(path) -> None:
    with open(path, "wb") as f:
        f.write((b"\xff\xfb\x90\x44" + b"\x00" * 417) * 5)
    ID3().save(str(path))


@pytest.fixture(name="client")
def client_fixture(tmp_path, monkeypatch):
    music = tmp_path / "music"
    storage = tmp_path / "storage"
    music.mkdir()
    storage.mkdir()
    monkeypatch.setattr(settings, "MUSIC_DIR", str(music))
    monkeypatch.setattr(settings, "STORAGE_DIR", str(storage))
    monkeypatch.setattr(settings, "ORGANIZE_DRY_RUN", False)

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(worker, "engine", engine)

    source = music / "messy_name.mp3"
    _dummy_mp3(source)

    with Session(engine) as session:
        session.add(
            File(
                filepath=str(source),
                filename="messy_name.mp3",
                extension=".mp3",
                sha256=calculate_sha256(str(source)),
                file_size=source.stat().st_size,
                modified_at=datetime.now(UTC),
                scan_state="indexed",
            )
        )
        session.commit()
        # Identified metadata (musicbrainz) drives the §15 plan.
        for field, value in [
            ("artist", "Pink Floyd"),
            ("title", "Time"),
            ("album", "The Dark Side of the Moon"),
            ("year", "1973"),
            ("track_number", "4"),
        ]:
            session.add(
                MetadataProvenance(
                    file_id=1,
                    field_name=field,
                    value_text=value,
                    source="musicbrainz",
                    confidence=Decimal("98.0"),
                )
            )
        session.commit()

    def get_test_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_organization_e2e_apply_and_undo(client: TestClient):
    original_sha = calculate_sha256(str(Path(settings.MUSIC_DIR) / "messy_name.mp3"))

    # 1. Preview: pure data, no FS writes.
    res_preview = client.post("/api/organization/preview", json={"all": True})
    assert res_preview.status_code == 200
    plans = res_preview.json()["plans"]
    assert len(plans) == 1
    assert "Pink Floyd" in plans[0]["new_path"]
    assert plans[0]["dry_run"] is False

    # 2. Apply: change set + job enqueued; the worker performs the move.
    res_apply = client.post("/api/organization/apply", json={"all": True, "name": "e2e"})
    assert res_apply.status_code == 202
    apply_body = res_apply.json()
    change_set_id = apply_body["change_set_id"]
    job_id = apply_body["job_id"]

    assert worker.process_one_job() is True

    res_job = client.get(f"/api/organization/jobs/{job_id}")
    assert res_job.status_code == 200
    job = res_job.json()
    assert job["status"] == "completed"
    assert job["result_json"]["applied"] == 1

    moved = Path(settings.MUSIC_DIR) / (
        "Pink Floyd/[1973] The Dark Side of the Moon/04 - Time.mp3"
    )
    assert moved.exists()
    assert not (Path(settings.MUSIC_DIR) / "messy_name.mp3").exists()

    # 3. History listing + detail.
    res_sets = client.get("/api/change-sets")
    assert res_sets.status_code == 200
    assert res_sets.json()[0]["status"] == "applied"

    res_detail = client.get(f"/api/change-sets/{change_set_id}")
    assert res_detail.status_code == 200
    assert res_detail.json()["changes"][0]["verification_status"] == "verified"

    # 4. Undo: rollback restores the original byte-identically.
    res_undo = client.post(f"/api/organization/undo/{change_set_id}")
    assert res_undo.status_code == 202
    assert worker.process_one_job() is True

    original = Path(settings.MUSIC_DIR) / "messy_name.mp3"
    assert original.exists()
    assert calculate_sha256(str(original)) == original_sha
    assert not moved.exists()

    res_sets_after = client.get("/api/change-sets")
    assert res_sets_after.json()[0]["status"] == "rolled_back"


def test_apply_requires_actionable_plans(client: TestClient):
    """Unknown file ids resolve to error plans — apply refuses the empty set."""
    res = client.post("/api/organization/apply", json={"file_ids": [999]})
    assert res.status_code == 400


def test_undo_rejects_unknown_or_unapplied_sets(client: TestClient):
    assert client.post("/api/organization/undo/999").status_code == 404

    # A preview-only change set is pending — undo must refuse it (409).
    res_apply = client.post("/api/organization/apply", json={"all": True, "name": "pending-set"})
    assert res_apply.status_code == 202
    change_set_id = res_apply.json()["change_set_id"]
    res_undo = client.post(f"/api/organization/undo/{change_set_id}")
    assert res_undo.status_code == 409