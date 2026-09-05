from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from backend.core.config import settings
from backend.database.session import get_session
from backend.main import app
from backend.workers import scan_worker


@pytest.fixture(name="client")
def client_fixture(monkeypatch, tmp_path):
    # Point the path sandbox roots at a temp tree (TV2-004)
    music = tmp_path / "music"
    music.mkdir()
    (tmp_path / "storage" / "covers").mkdir(parents=True)
    (tmp_path / "storage" / "downloads").mkdir(parents=True)
    monkeypatch.setattr(settings, "MUSIC_DIR", str(music))
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "COVERS_DIR", str(tmp_path / "storage" / "covers"))
    monkeypatch.setattr(settings, "DOWNLOADS_DIR", str(tmp_path / "storage" / "downloads"))
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    # Patch scan worker engine to test memory DB
    monkeypatch.setattr(scan_worker, "engine", engine)

    def get_test_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session

    # Seed test songs into memory DB (V2 schema, TV2-011b)
    with Session(engine) as session:
        from backend.repositories.song_repository import SongRepository

        SongRepository.upsert_song(
            session,
            {
                "filename": "track01.mp3",
                "filepath": "/music/album1/track01.mp3",
                "sha256": "hash123",
                "title": "Song Alpha",
                "artist": "Artist One",
                "album": "Album One",
                "genre": "Rock",
                "duration": 200.0,
                "file_size": 5000000,
                "codec": "mp3",
            },
            source="existing_tag",
        )
        SongRepository.upsert_song(
            session,
            {
                "filename": "track02.flac",
                "filepath": "/music/album2/track02.flac",
                "sha256": "hash456",
                "title": "Song Beta",
                "artist": "Artist Two",
                "album": "Album Two",
                "genre": "Jazz",
                "duration": 300.0,
                "file_size": 15000000,
                "codec": "flac",
            },
            source="existing_tag",
        )

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


def test_health_endpoint(client: TestClient):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_scan_api(client: TestClient):
    # Scan input must be inside the sandboxed MUSIC_DIR (TV2-004)
    scan_dir = Path(settings.MUSIC_DIR) / "album1"
    scan_dir.mkdir()
    response = client.post(
        "/api/scan",
        json={"directory_path": str(scan_dir), "perform_audio_analysis": False},
    )
    assert response.status_code == 202
    job_data = response.json()
    assert job_data["id"] is not None
    job_id = job_data["id"]

    status_res = client.get(f"/api/scan/status/{job_id}")
    assert status_res.status_code == 200
    assert status_res.json()["id"] == job_id

    jobs_res = client.get("/api/scan/jobs")
    assert jobs_res.status_code == 200
    assert len(jobs_res.json()) >= 1


def test_scan_rejects_directory_outside_music_dir(client: TestClient):
    outside = Path(settings.MUSIC_DIR).parent / "elsewhere"
    outside.mkdir(exist_ok=True)
    response = client.post(
        "/api/scan",
        json={"directory_path": str(outside), "perform_audio_analysis": False},
    )
    assert response.status_code == 403


def test_songs_list_and_filters(client: TestClient):
    res = client.get("/api/songs")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2

    res_search = client.get("/api/songs?search=Alpha")
    assert res_search.status_code == 200
    assert res_search.json()["total"] == 1
    assert res_search.json()["items"][0]["title"] == "Song Alpha"

    res_genre = client.get("/api/songs?genre=Jazz")
    assert res_genre.status_code == 200
    assert res_genre.json()["total"] == 1
    assert res_genre.json()["items"][0]["artist"] == "Artist Two"


def test_song_detail_delete_and_cover(client: TestClient):
    res_list = client.get("/api/songs")
    song_id = res_list.json()["items"][0]["id"]

    res_detail = client.get(f"/api/songs/{song_id}")
    assert res_detail.status_code == 200
    assert res_detail.json()["id"] == song_id

    res_cover = client.get(f"/api/songs/{song_id}/cover")
    assert res_cover.status_code == 200
    assert "image/svg+xml" in res_cover.headers["content-type"]

    res_del = client.delete(f"/api/songs/{song_id}")
    assert res_del.status_code == 200

    res_404 = client.get(f"/api/songs/{song_id}")
    assert res_404.status_code == 404


def test_stats_endpoint(client: TestClient):
    res = client.get("/api/stats")
    assert res.status_code == 200
    data = res.json()
    assert data["total_songs"] == 2
    assert data["total_artists"] == 2
    assert data["total_albums"] == 2
    assert data["total_duration"] == 500.0
    assert "mp3" in data["codecs"]
    assert "flac" in data["codecs"]


def test_export_endpoints(client: TestClient):
    res_json = client.get("/api/export/json")
    assert res_json.status_code == 200
    assert "application/json" in res_json.headers["content-type"]
    assert len(res_json.json()) == 2

    res_csv = client.get("/api/export/csv")
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.headers["content-type"]
    assert "filename,filepath" in res_csv.text

    res_xlsx = client.get("/api/export/xlsx")
    assert res_xlsx.status_code == 200
    assert "spreadsheetml" in res_xlsx.headers["content-type"]


def test_stream_song_audio(client: TestClient):
    audio_path = Path(settings.MUSIC_DIR) / "track_stream.mp3"
    audio_path.write_bytes(b"ID3FakeMP3ContentForStreamingTest")

    # Fetch songs list to get valid song ID
    res_list = client.get("/api/songs")
    song = res_list.json()["items"][0]
    song_id = song["id"]

    # Patch song filepath to existing temp file
    from backend.database.session import get_session
    from backend.models import File

    override_session = next(app.dependency_overrides[get_session]())
    db_file = override_session.get(File, song_id)
    if db_file:
        db_file.filepath = str(audio_path)
        override_session.add(db_file)
        override_session.commit()

    stream_res = client.get(f"/api/songs/{song_id}/stream")
    assert stream_res.status_code == 200
    assert "audio/" in stream_res.headers["content-type"]
    assert stream_res.headers["accept-ranges"] == "bytes"
    assert stream_res.content == b"ID3FakeMP3ContentForStreamingTest"

    range_res = client.get(
        f"/api/songs/{song_id}/stream",
        headers={"Range": "bytes=3-9"},
    )
    assert range_res.status_code == 206
    assert range_res.content == b"FakeMP3"
    assert range_res.headers["content-range"] == "bytes 3-9/33"
    assert range_res.headers["content-length"] == "7"

    suffix_res = client.get(
        f"/api/songs/{song_id}/stream",
        headers={"Range": "bytes=-10"},
    )
    assert suffix_res.status_code == 206
    assert suffix_res.content == b"eamingTest"

    invalid_range_res = client.get(
        f"/api/songs/{song_id}/stream",
        headers={"Range": "bytes=100-200"},
    )
    assert invalid_range_res.status_code == 416
    assert invalid_range_res.headers["content-range"] == "bytes */33"

    # Test 404 for invalid song ID
    res_404 = client.get("/api/songs/99999/stream")
    assert res_404.status_code == 404
