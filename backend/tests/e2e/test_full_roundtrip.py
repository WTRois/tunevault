"""E2E full roundtrip (TV2-039, blueprint §35): scan → identify → artwork →
organize → undo — through the real worker and API, fully offline.

Providers (MusicBrainz, AcoustID, Cover Art Archive) are stubbed; the audio
files are small synthetic MP3s. Covered §35 scenarios: bad filename, missing
metadata, same recording different file, wrong candidate, rename collision,
worker restart (queue drain + retry policy).
"""

import io
import os

import pytest
from fastapi.testclient import TestClient
from mutagen.id3 import ID3
from PIL import Image
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from backend.api.endpoints import artwork as artwork_module
from backend.api.endpoints import identification as identification_module
from backend.core.config import settings
from backend.database.session import get_session
from backend.fingerprint.fpcalc import FpcalcUnavailable
from backend.identification import candidates as candidates_mod
from backend.main import app
from backend.models import Artwork, File, FileRecording, Job
from backend.repositories.job_repository import JobRepository
from backend.services.scanner import calculate_sha256
from backend.workers import scan_worker, worker
from backend.workers.handlers import identify as identify_mod

RECORDING_MBID = "mbid-1"
RELEASE_MBID = "rel-mbid-1"


# ---------- offline provider stubs ----------


class StubMB:
    """Returns a correct studio candidate + a wrong live candidate (§35)."""

    name = "musicbrainz"

    async def search(self, query):
        from backend.providers.base import ProviderMatch

        return [
            ProviderMatch(
                source="musicbrainz",
                title="Numb",
                artist="Linkin Park",
                release_title="Meteora",
                recording_mbid=RECORDING_MBID,
                release_mbid=RELEASE_MBID,
            ),
            ProviderMatch(
                source="musicbrainz",
                title="Numb (Live)",
                artist="Linkin Park",
            ),
        ]


class StubAcoustID:
    name = "acoustid"

    def enabled(self):
        return False

    async def search(self, query):
        return []


class StubReleaseProvider:
    """lookup_release serves a tracklist containing the matched recording."""

    name = "musicbrainz"

    async def lookup_release(self, release_mbid):
        return {
            "id": release_mbid,
            "title": "Meteora",
            "media": [
                {
                    "position": 1,
                    "track-list": [
                        {"position": 6, "title": "Numb", "recording": {"id": RECORDING_MBID}},
                    ],
                }
            ],
        }


class StubImage:
    def __init__(self, url, front, type_):
        self.url = url
        self.front = front
        self.type = type_
        self.mime_type = "image/jpeg"


class StubCAA:
    name = "coverartarchive"

    @staticmethod
    def _front_bytes() -> bytes:
        buf = io.BytesIO()
        Image.new("RGB", (600, 600), color="purple").save(buf, format="JPEG")
        return buf.getvalue()

    async def release_covers(self, mbid):
        return [StubImage("https://caa.test/front.jpg", True, "Front")]

    async def download(self, url):
        return self._front_bytes()


def _raise_fpcalc(path):
    raise FpcalcUnavailable("offline e2e")


def _dummy_mp3(path) -> None:
    with open(path, "wb") as f:
        f.write((b"\xff\xfb\x90\x44" + b"\x00" * 417) * 5)
    ID3().save(str(path))


# ---------- environment ----------


@pytest.fixture(name="env")
def env_fixture(tmp_path, monkeypatch):
    music = tmp_path / "music"
    storage = tmp_path / "storage"
    covers = tmp_path / "covers"
    for d in (music, storage, covers):
        d.mkdir()
    monkeypatch.setattr(settings, "MUSIC_DIR", str(music))
    monkeypatch.setattr(settings, "STORAGE_DIR", str(storage))
    monkeypatch.setattr(settings, "COVERS_DIR", str(covers))
    monkeypatch.setattr(settings, "ORGANIZE_DRY_RUN", False)

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(worker, "engine", engine)
    monkeypatch.setattr(scan_worker, "engine", engine)

    # Two untagged files with bad filenames → same recording after identify
    # (§35: bad filename, missing metadata, same recording different file).
    _dummy_mp3(music / "Linkin Park - Numb [320kbps].mp3")
    _dummy_mp3(music / "01 - numb   (1).mp3")

    # Offline providers.
    monkeypatch.setattr(identify_mod, "compute_fingerprint", _raise_fpcalc)
    monkeypatch.setattr(candidates_mod, "MusicBrainzProvider", StubMB)
    monkeypatch.setattr(candidates_mod, "AcoustIDProvider", StubAcoustID)
    monkeypatch.setattr(identification_module, "_release_provider", lambda: StubReleaseProvider())
    monkeypatch.setattr(artwork_module, "_caa_provider", lambda: StubCAA())

    def get_test_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _song_ids(client: TestClient) -> list[int]:
    res = client.get("/api/songs?limit=50")
    assert res.status_code == 200
    return [song["id"] for song in res.json()["items"]]


def _scan_all(client: TestClient) -> None:
    res = client.post(
        "/api/scan",
        json={"directory_path": settings.MUSIC_DIR, "perform_audio_analysis": False},
    )
    assert res.status_code == 202
    scan_job_id = res.json()["id"]
    assert worker.process_one_job() is True
    res = client.get(f"/api/scan/status/{scan_job_id}")
    assert res.json()["status"] == "completed"


def _identify(client: TestClient, file_ids: list[int]) -> None:
    res = client.post("/api/identification/jobs", json={"file_ids": file_ids})
    assert res.status_code == 202
    assert worker.process_one_job() is True
    res = client.get(f"/api/jobs/{res.json()['id']}")
    assert res.json()["status"] == "completed"


def _accept_studio(client: TestClient, song_id: int) -> dict:
    res = client.get(f"/api/identification/songs/{song_id}/candidates")
    assert res.status_code == 200
    studio = next(
        c for c in res.json() if c["recording_mbid"] == RECORDING_MBID
    )
    res = client.post(f"/api/identification/songs/{song_id}/candidates/{studio['id']}/accept")
    assert res.status_code == 200
    return res.json()


# ---------- §35 scenarios ----------


def test_full_roundtrip_scan_identify_artwork_organize_undo(env: TestClient):
    # 1. SCAN — bad filenames, no tags: the fast pass must still index them.
    _scan_all(env)
    ids = _song_ids(env)
    assert len(ids) == 2

    # 2. IDENTIFY — filename evidence drives the (stubbed) providers.
    _identify(env, ids)

    recordings = []
    for song_id in ids:
        body = _accept_studio(env, song_id)
        assert body["accepted"] is True
        assert body["release"]["release_mbid"] == RELEASE_MBID
        recordings.append(body["recording_id"])

    # Same recording, different files (§35).
    assert recordings[0] == recordings[1]

    # 3. ARTWORK — search caches candidates; apply embeds the front cover.
    res = env.post(f"/api/files/{ids[0]}/artwork/search")
    assert res.status_code == 200
    artworks = res.json()
    assert len(artworks) == 1
    assert artworks[0]["type"] == "front"

    res = env.post(
        f"/api/files/{ids[0]}/artwork/apply", json={"artwork_id": artworks[0]["id"]}
    )
    assert res.status_code == 200
    with Session(worker.engine) as session:
        rows = session.exec(
            select(Artwork).where(Artwork.file_id == ids[0], Artwork.is_embedded == True)
        ).all()
        assert len(rows) == 1

    # 4. ORGANIZE — preview → apply via the worker.
    res = env.post("/api/organization/preview", json={"all": True})
    assert res.status_code == 200
    plans = res.json()["plans"]
    assert len(plans) == 2
    assert all(plan.get("new_path") for plan in plans)

    res = env.post("/api/organization/apply", json={"all": True})
    assert res.status_code == 202
    assert worker.process_one_job() is True

    res = env.get("/api/change-sets")
    change_sets = res.json()
    assert len(change_sets) == 1
    cs_id = change_sets[0]["id"]

    res = env.get(f"/api/change-sets/{cs_id}")
    changes = res.json()["changes"]
    assert len(changes) == 2
    assert all(c["verification_status"] == "verified" for c in changes)

    # Rename collision (§35): identical metadata → same target → §17 suffix
    # policy (never overwrite, never destroy).
    new_paths = [c["new_path"] for c in changes]
    assert len(set(new_paths)) == 2
    for path in new_paths:
        assert os.path.exists(path)
        assert not os.path.exists(settings.MUSIC_DIR + os.sep + "Linkin Park - Numb [320kbps].mp3")

    # File rows point at the moved files.
    with Session(worker.engine) as session:
        files = session.exec(select(File)).all()
        assert {f.filepath for f in files} == set(new_paths)

    # Canonical tags written to the moved files (§15).
    for path in new_paths:
        tags = ID3(path)
        assert str(tags.getall("TIT2")[0]) == "Numb"
        assert str(tags.getall("TPE1")[0]) == "Linkin Park"

    # 5. UNDO — byte-identical restore of both originals (§16).
    originals = {c["file_id"]: c for c in changes}
    for change in changes:
        originals[change["file_id"]] = calculate_sha256(change["backup_path"])

    res = env.post(f"/api/organization/undo/{cs_id}")
    assert res.status_code == 202
    assert worker.process_one_job() is True

    res = env.get("/api/change-sets")
    assert res.json()[0]["status"] == "rolled_back"

    for change in changes:
        assert os.path.exists(change["old_path"])
        assert calculate_sha256(change["old_path"]) == originals[change["file_id"]]
        assert not os.path.exists(change["new_path"])


def test_wrong_candidate_rejected_then_correct_accepted(env: TestClient):
    """§35: the wrong (live) candidate is rejected; the right one wins."""
    _scan_all(env)
    ids = _song_ids(env)
    _identify(env, [ids[0]])

    res = env.get(f"/api/identification/songs/{ids[0]}/candidates")
    candidates = res.json()
    live = next(c for c in candidates if c["recording_mbid"] is None)
    studio = next(c for c in candidates if c["recording_mbid"] == RECORDING_MBID)

    res = env.post(f"/api/identification/songs/{ids[0]}/candidates/{live['id']}/reject")
    assert res.status_code == 204

    res = env.post(f"/api/identification/songs/{ids[0]}/candidates/{studio['id']}/accept")
    assert res.status_code == 200

    res = env.get(f"/api/identification/songs/{ids[0]}/candidates")
    statuses = {c["id"]: c["status"] for c in res.json()}
    assert statuses[live["id"]] == "rejected"
    assert statuses[studio["id"]] == "accepted"

    with Session(worker.engine) as session:
        links = session.exec(
            select(FileRecording).where(FileRecording.file_id == ids[0])
        ).all()
        assert len(links) == 1


def test_worker_restart_drains_queue_and_retries_failed_jobs(env: TestClient):
    """§35 worker restart: pending jobs survive; the restarted worker drains
    them one at a time, and a poisoned job is retried per §24 then failed."""
    _scan_all(env)
    ids = _song_ids(env)

    # Two identify jobs queued while the worker is "down".
    job_ids = []
    for song_id in ids:
        res = env.post("/api/identification/jobs", json={"file_ids": [song_id]})
        assert res.status_code == 202
        job_ids.append(res.json()["id"])

    # The "restarted" worker drains the queue claim-by-claim (§23 atomicity).
    assert worker.process_one_job() is True
    assert worker.process_one_job() is True
    assert worker.process_one_job() is False  # queue drained

    with Session(worker.engine) as session:
        jobs = session.exec(select(Job).where(Job.job_type == "identify")).all()
        assert {job.status for job in jobs} == {"completed"}

    # A poisoned job raises, is requeued, retried, then gives up (§24).
    with Session(worker.engine) as session:
        JobRepository.enqueue(session, "organize", payload={}, max_attempts=3)

    for _ in range(3):  # attempt 1 → requeue, 2 → requeue, 3 → failed
        assert worker.process_one_job() is True
    assert worker.process_one_job() is False

    with Session(worker.engine) as session:
        poisoned = session.exec(
            select(Job).where(Job.job_type == "organize")
        ).one()
        assert poisoned.status == "failed"
        assert poisoned.attempts == 3
        assert poisoned.error_message