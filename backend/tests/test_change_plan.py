"""Change plan tests (TV2-024, blueprint §15): pure data, dry-run, no FS writes."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from backend.main import app
from backend.models import File, MetadataProvenance
from backend.organization.change_plan import build_change_plan, preview_plans


@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="seeded")
def seeded_fixture(engine):
    with Session(engine) as session:
        file = File(
            filepath="/music/01.mp3",
            filename="01.mp3",
            extension=".flac",
            sha256="a" * 64,
            file_size=10,
            modified_at=datetime.now(UTC),
            duration_ms=187_000,
            scan_state="indexed",
        )
        session.add(file)
        session.commit()

        # What the file's own tags report (pre-change side of the §15 diff).
        for field, value in [("artist", "Unknown"), ("title", "01")]:
            session.add(
                MetadataProvenance(
                    file_id=file.id,
                    field_name=field,
                    value_text=value,
                    source="existing_tag",
                    confidence=Decimal("1.0"),
                )
            )

        # Accepted candidate + provenance = identification applied (§9).
        for field, value in [
            ("artist", "Pink Floyd"),
            ("title", "Time"),
            ("album", "The Dark Side of the Moon"),
            ("year", "1973"),
            ("track_number", "4"),
        ]:
            session.add(
                MetadataProvenance(
                    file_id=file.id,
                    field_name=field,
                    value_text=value,
                    source="musicbrainz",
                    confidence=Decimal("98.7"),
                )
            )
        session.commit()
        return file.id


def test_build_change_plan_matches_blueprint_shape(engine, seeded):
    with Session(engine) as session:
        file = session.get(File, seeded)
        plan = build_change_plan(session, file)

    assert plan is not None
    assert plan["file_id"] == seeded
    assert plan["old_path"] == "/music/01.mp3"
    assert "Pink Floyd" in plan["new_path"]
    assert "1973" in plan["new_path"]
    assert "The Dark Side of the Moon" in plan["new_path"]
    assert plan["metadata_changes"]["artist"] == ["Unknown", "Pink Floyd"]
    assert plan["metadata_changes"]["title"] == ["01", "Time"]
    assert plan["metadata_changes"]["album"][1] == "The Dark Side of the Moon"
    assert plan["confidence"] > 0
    assert plan["dry_run"] is True


def test_preview_is_read_only(engine, seeded, tmp_path):
    """Building/previewing plans must not touch the filesystem at all."""
    with Session(engine) as session:
        result = preview_plans(session, [seeded])
    assert len(result["plans"]) == 1
    assert result["dry_run"] is True
    # No files created anywhere by a preview (dry-run contract §15).
    assert list(tmp_path.iterdir()) == []


def test_preview_skips_unidentified_file(engine, seeded):
    with Session(engine) as session:
        blank = File(
            filepath="/music/blank.mp3",
            filename="blank.mp3",
            extension=".mp3",
            sha256="b" * 64,
            file_size=1,
            modified_at=datetime.now(UTC),
        )
        session.add(blank)
        session.commit()
        blank_id = blank.id

        result = preview_plans(session, [blank_id])
    assert result["plans"][0].get("skipped") is not None


def test_preview_reports_missing_file(engine, seeded):
    with Session(engine) as session:
        result = preview_plans(session, [999999])
    assert result["plans"][0] == {"file_id": 999999, "error": "file not found"}


def test_organization_preview_endpoint(engine, seeded):
    from backend.database.session import get_session

    def get_test_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    try:
        with TestClient(app) as client:
            res = client.post("/api/organization/preview", json={"file_ids": [seeded]})
            assert res.status_code == 200
            body = res.json()
            assert body["dry_run"] is True
            plan = body["plans"][0]
            assert "Pink Floyd" in plan["new_path"]

            res = client.post("/api/organization/preview", json={})
            assert res.status_code == 400

            res = client.post("/api/organization/preview", json={"song_ids": [999999]})
            assert res.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_naming_sanitizes_unsafe_components():
    from backend.organization.naming import sanitize_component

    assert sanitize_component('AC/DC: Back In Black?') == "AC_DC_ Back In Black_"
    assert sanitize_component("CON") == "Unknown"
    assert sanitize_component("trailing dots... ") == "trailing dots"
    assert sanitize_component(None, fallback="X") == "X"