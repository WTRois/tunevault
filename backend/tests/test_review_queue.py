"""Review queue + bulk accept + release preferences tests (TV2-036, §22/§10)."""

import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from backend.main import app
from backend.models import AppSetting, File, MetadataCandidate


@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _seed_file(session: Session, n: int) -> File:
    from datetime import UTC, datetime

    file = File(
        filepath=f"/music/track{n}.mp3",
        filename=f"Unknown Artist - track{n}.mp3",
        extension=".mp3",
        sha256=f"{n}" * 64,
        file_size=10,
        modified_at=datetime.now(UTC),
        scan_state="indexed",
    )
    session.add(file)
    session.commit()
    session.refresh(file)
    return file


def _seed_candidate(
    session: Session,
    file: File,
    *,
    source: str = "musicbrainz",
    score: float = 80.0,
    confidence_level: str = "auto_suggest_review",
    status: str = "pending",
    title: str = "Numb",
) -> int:
    payload = {
        "source": source,
        "title": title,
        "artist": "Linkin Park",
        "release_title": "Meteora",
        "recording_mbid": f"mbid-{file.id}-{score}",
    }
    row = MetadataCandidate(
        file_id=file.id or 0,
        source=source,
        payload_json=json.dumps(payload),
        score=Decimal(str(score)),
        confidence_level=confidence_level,
        status=status,
    )
    session.add(row)
    session.commit()
    return row.id or 0


def _client(engine):
    from backend.database.session import get_session

    def get_test_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    return TestClient(app)


@pytest.fixture(name="client")
def client_fixture(engine):
    client = _client(engine)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture(name="stub_release")
def stub_release_fixture(monkeypatch):
    """No release provider in accept flows — release match stays best-effort."""
    from backend.api.endpoints import identification as endpoints_mod

    monkeypatch.setattr(endpoints_mod, "_release_provider", lambda: None)


def test_review_queue_lists_pending_candidates_with_file(engine, client):
    with Session(engine) as session:
        f1 = _seed_file(session, 1)
        f2 = _seed_file(session, 2)
        good = _seed_candidate(session, f1, score=90.0)
        weak = _seed_candidate(session, f2, score=40.0, confidence_level="review_required")
        accepted = _seed_candidate(session, f1, score=85.0, status="accepted")
        f1_name, f1_path = f1.filename, f1.filepath

    res = client.get("/api/identification/review")
    assert res.status_code == 200
    items = res.json()
    ids = [item["id"] for item in items]
    assert set(ids) == {good, weak}
    assert accepted not in ids
    assert items[0]["id"] == good  # best score first
    assert items[0]["filename"] == f1_name
    assert items[0]["filepath"] == f1_path
    assert items[0]["title"] == "Numb"


def test_review_queue_filters(engine, client):
    with Session(engine) as session:
        f1 = _seed_file(session, 1)
        f2 = _seed_file(session, 2)
        strong = _seed_candidate(session, f1, score=92.0)
        weak = _seed_candidate(session, f2, score=45.0, confidence_level="review_required")

    res = client.get("/api/identification/review", params={"confidence_level": "review_required"})
    assert res.status_code == 200
    assert [item["id"] for item in res.json()] == [weak]

    res = client.get("/api/identification/review", params={"min_score": 50})
    assert [item["id"] for item in res.json()] == [strong]

    res = client.get(
        "/api/identification/review", params={"source": "acoustid"}
    )
    assert res.json() == []


def test_bulk_accept_explicit_ids_skips_non_pending(engine, client, stub_release):
    with Session(engine) as session:
        f1 = _seed_file(session, 1)
        f2 = _seed_file(session, 2)
        good = _seed_candidate(session, f1, score=90.0)
        already = _seed_candidate(session, f2, score=88.0, status="accepted")

    res = client.post(
        "/api/identification/review/bulk-accept",
        json={"candidate_ids": [good, already, 999]},
    )
    assert res.status_code == 200
    body = res.json()
    assert len(body["accepted"]) == 1
    assert body["accepted"][0]["accepted"] is True
    assert body["skipped"] == 2
    assert body["errors"] == []

    with Session(engine) as session:
        row = session.get(MetadataCandidate, good)
        assert row is not None and row.status == "accepted"


def test_bulk_accept_filter_takes_best_pending_per_file(engine, client, stub_release):
    with Session(engine) as session:
        f1 = _seed_file(session, 1)
        f2 = _seed_file(session, 2)
        best_f1 = _seed_candidate(session, f1, score=90.0)
        other_f1 = _seed_candidate(session, f1, score=70.0, title="Numb (Live)")
        best_f2 = _seed_candidate(session, f2, score=60.0, confidence_level="review_required")

    # min_score filter matches all three; only the best per file is accepted.
    res = client.post(
        "/api/identification/review/bulk-accept",
        json={"min_score": 50},
    )
    assert res.status_code == 200
    body = res.json()
    assert len(body["accepted"]) == 2
    assert body["skipped"] == 1
    assert body["errors"] == []

    with Session(engine) as session:
        rows = {
            row.id: row.status
            for row in session.exec(select(MetadataCandidate)).all()
        }
        assert rows[best_f1] == "accepted"
        assert rows[other_f1] == "pending"  # stays for manual review
        assert rows[best_f2] == "accepted"


def test_bulk_accept_confidence_level_filter(engine, client, stub_release):
    with Session(engine) as session:
        f1 = _seed_file(session, 1)
        f2 = _seed_file(session, 2)
        f1_id = f1.id
        suggest = _seed_candidate(session, f1, score=80.0)
        _seed_candidate(session, f2, score=75.0, confidence_level="review_required")

    res = client.post(
        "/api/identification/review/bulk-accept",
        json={"confidence_level": "auto_suggest_review"},
    )
    body = res.json()
    assert len(body["accepted"]) == 1
    assert body["accepted"][0]["file_id"] == f1_id
    with Session(engine) as session:
        row = session.get(MetadataCandidate, suggest)
        assert row is not None and row.status == "accepted"


def test_release_preferences_get_put_and_db_override(engine, client, monkeypatch):
    with Session(engine) as session:
        session.add(AppSetting(key="release_preference", value="prefer_remaster"))
        session.add(AppSetting(key="release_preference_country", value="JP"))
        session.commit()

    # GET reflects the DB overrides.
    res = client.get("/api/identification/release-preferences")
    assert res.status_code == 200
    prefs = res.json()
    assert prefs["preference"] == "prefer_remaster"
    assert prefs["country"] == "JP"
    assert prefs["label"] == ""

    # release_match reads the same effective preferences from the DB.
    from backend.identification.release_match import release_preferences

    with Session(engine) as session:
        assert release_preferences(session) == {
            "preference": "prefer_remaster",
            "country": "JP",
            "label": "",
        }

    # PUT persists all three keys and echoes the effective state.
    res = client.put(
        "/api/identification/release-preferences",
        json={"preference": "prefer_specific_label", "country": "US", "label": "Mobile Fidelity"},
    )
    assert res.status_code == 200
    assert res.json()["preference"] == "prefer_specific_label"
    assert res.json()["label"] == "Mobile Fidelity"

    with Session(engine) as session:
        stored = {row.key: row.value for row in session.exec(select(AppSetting)).all()}
    assert stored["release_preference"] == "prefer_specific_label"
    assert stored["release_preference_label"] == "Mobile Fidelity"

    # Invalid preference → 422.
    res = client.put(
        "/api/identification/release-preferences",
        json={"preference": "prefer_vinyl_noise"},
    )
    assert res.status_code == 422