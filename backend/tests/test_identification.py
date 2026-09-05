"""End-to-end identification tests (TV2-019, mocked providers, §35)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from backend.main import app
from backend.models import File, Job, MetadataCandidate, MetadataProvenance, Recording
from backend.providers.base import MetadataQuery, ProviderMatch
from backend.workers.handlers.identify import handle_identify


class StubMB:
    name = "musicbrainz"

    def __init__(self):
        self.calls = 0

    async def search(self, query: MetadataQuery) -> list[ProviderMatch]:
        self.calls += 1
        return [
            ProviderMatch(
                source="musicbrainz",
                title="Numb",
                artist="Linkin Park",
                release_title="Meteora",
                duration_ms=187_000,
                recording_mbid="mbid-1",
            ),
            ProviderMatch(
                source="musicbrainz",
                title="Numb (Live)",
                artist="Linkin Park",
                duration_ms=210_000,
            ),
        ]


class StubAcoustID:
    name = "acoustid"

    def enabled(self):
        return False

    async def search(self, query):
        return []


@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="seed")
def seed_fixture(engine):
    with Session(engine) as session:
        file = File(
            filepath="/music/track.mp3",
            filename="Linkin.Park - 01 - Numb [320kbps].mp3",
            extension=".mp3",
            sha256="a" * 64,
            file_size=10,
            modified_at=datetime.now(UTC),
            duration_ms=187_000,
            scan_state="indexed",
        )
        session.add(file)
        session.commit()
        return file.id, file.id


def _identify(engine, file_id, song_id):
    """Run the identify handler with stubbed providers and fingerprint.

    The handler reports progress on the Job row (§19), so tests pass a real
    Job instead of a stub object.
    """
    with Session(engine) as session:
        job = Job(job_type="identify", payload_json={"file_ids": [file_id]})
        session.add(job)
        session.commit()
        result = handle_identify(session, job)
    return result


def _skip_fingerprint(path):
    """Raise FpcalcUnavailable — simulates a machine without fpcalc."""
    from backend.fingerprint.fpcalc import FpcalcUnavailable

    raise FpcalcUnavailable("skip in tests")


def test_identify_job_produces_scored_candidates(engine, seed, monkeypatch):
    from backend.identification import candidates as candidates_mod
    from backend.workers.handlers import identify as identify_mod

    song_id, file_id = seed
    monkeypatch.setattr(identify_mod, "compute_fingerprint", _skip_fingerprint)
    monkeypatch.setattr(candidates_mod, "MusicBrainzProvider", StubMB)
    monkeypatch.setattr(candidates_mod, "AcoustIDProvider", StubAcoustID)

    result = _identify(engine, file_id, song_id)
    assert result["items"][0]["candidates"] == 2
    # Filename-only evidence scores ~37 (title 15 + artist 15 + duration 7):
    # per §8.4 this is NO_MATCH — nothing is auto-applied without strong evidence.
    assert result["items"][0]["best_outcome"] == "no_match"
    assert result["items"][0]["best_score"] == 37.0

    with Session(engine) as session:
        rows = session.exec(select(MetadataCandidate)).all()
        assert len(rows) == 2
        assert rows[0].status == "pending"
        assert rows[0].source == "musicbrainz"


def test_accept_candidate_writes_provenance_and_recording_link(engine, seed, monkeypatch):
    from backend.identification import candidates as candidates_mod
    from backend.workers.handlers import identify as identify_mod

    song_id, file_id = seed
    monkeypatch.setattr(identify_mod, "compute_fingerprint", _skip_fingerprint)
    monkeypatch.setattr(candidates_mod, "MusicBrainzProvider", StubMB)
    monkeypatch.setattr(candidates_mod, "AcoustIDProvider", StubAcoustID)
    _identify(engine, file_id, song_id)

    with Session(engine) as session:
        best = session.exec(
            select(MetadataCandidate).order_by(MetadataCandidate.score.desc())
        ).first()
        assert best is not None
        candidate_id = best.id

    # Accept flow via resolver directly (endpoint test follows).
    with Session(engine) as session:
        file = session.get(File, file_id)
        row = session.get(MetadataCandidate, candidate_id)
        import json

        from backend.identification.resolver import resolve_recording, write_recording_link
        from backend.providers.base import ProviderMatch

        match = ProviderMatch.from_dict(json.loads(row.payload_json))
        resolved = resolve_recording(session, file, row, user_confirmed=True)
        recording_id = write_recording_link(session, file_id, match, Decimal("0.9"))

        assert resolved["title"] == "Numb"
        assert resolved["artist"] == "Linkin Park"
        assert row.status == "accepted"

        provenance = session.exec(select(MetadataProvenance)).all()
        assert len(provenance) >= 2
        assert all(p.candidate_id == candidate_id for p in provenance)

        recording = session.get(Recording, recording_id)
        assert recording is not None
        assert recording.musicbrainz_recording_id == "mbid-1"


def test_identification_endpoints_contract(engine, seed):
    _song_id, _file_id = seed
    song_id = _song_id  # named for clarity in the request bodies below

    def get_test_session():
        with Session(engine) as session:
            yield session

    from backend.database.session import get_session

    app.dependency_overrides[get_session] = get_test_session
    try:
        with TestClient(app) as client:
            # Enqueue identification job.
            res = client.post("/api/identification/jobs", json={"song_ids": [song_id]})
            assert res.status_code == 202
            job = res.json()
            assert job["job_type"] == "identify"
            job_id = job["id"]

            res = client.get(f"/api/identification/jobs/{job_id}")
            assert res.status_code == 200
            assert res.json()["status"] == "pending"

            # Empty payload → 400.
            res = client.post("/api/identification/jobs", json={})
            assert res.status_code == 400

            # Unknown song → 404.
            res = client.post("/api/identification/jobs", json={"song_ids": [9999]})
            assert res.status_code == 404

            # Identify single song endpoint enqueues too.
            res = client.post(f"/api/identification/songs/{song_id}/identify")
            assert res.status_code == 202

            # Candidates list is empty before identification runs.
            res = client.get(f"/api/identification/songs/{song_id}/candidates")
            assert res.status_code == 200
            assert res.json() == []
    finally:
        app.dependency_overrides.clear()


def test_worker_dispatches_identify(engine, seed, monkeypatch):
    _song_id, file_id = seed
    from backend.identification import candidates as candidates_mod
    from backend.workers import worker
    from backend.workers.handlers import identify as identify_mod

    monkeypatch.setattr(worker, "engine", engine)
    monkeypatch.setattr(identify_mod, "compute_fingerprint", _skip_fingerprint)
    monkeypatch.setattr(candidates_mod, "MusicBrainzProvider", StubMB)
    monkeypatch.setattr(candidates_mod, "AcoustIDProvider", StubAcoustID)

    with Session(engine) as session:
        from backend.repositories.job_repository import JobRepository

        JobRepository.enqueue(session, "identify", payload={"file_ids": [file_id]})

    assert worker.process_one_job() is True

    with Session(engine) as session:
        job = session.exec(select(Job)).one()
        assert job.status == "completed"
        assert job.result_json["items"][0]["candidates"] == 2


def test_fingerprint_yields_acoustid_candidates(engine, seed, monkeypatch):
    """§44 DoD — Identification: a fingerprint can produce candidates (the
    AcoustID branch of the §7 evidence pipeline is wired end-to-end)."""
    from types import SimpleNamespace

    from backend.providers.base import ProviderMatch

    class StubAcoustIDEnabled:
        name = "acoustid"

        def enabled(self):
            return True

        async def search(self, query):
            return [
                ProviderMatch(
                    source="acoustid",
                    title="Numb",
                    artist="Linkin Park",
                    duration_ms=187_000,
                    recording_mbid="mbid-aid-1",
                )
            ]

    _song_id, file_id = seed
    from backend.identification import candidates as candidates_mod
    from backend.workers.handlers import identify as identify_mod

    monkeypatch.setattr(
        identify_mod,
        "compute_fingerprint",
        lambda path: SimpleNamespace(fingerprint="fp-abc"),
    )
    monkeypatch.setattr(candidates_mod, "MusicBrainzProvider", StubMB)
    monkeypatch.setattr(candidates_mod, "AcoustIDProvider", StubAcoustIDEnabled)
    _identify(engine, file_id, _song_id)

    with Session(engine) as session:
        rows = session.exec(select(MetadataCandidate)).all()
        sources = {row.source for row in rows}
        assert "acoustid" in sources  # fingerprint produced a candidate
        aid_rows = [row for row in rows if row.source == "acoustid"]
        assert aid_rows[0].score > 0