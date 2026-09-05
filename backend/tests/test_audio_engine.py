import os
import tempfile

import numpy as np
import pytest
from sqlmodel import Session, SQLModel, create_engine

from backend.models.scan_job import ScanJob
from backend.repositories.song_repository import SongRepository
from backend.services.analyzer import analyze_audio_features, estimate_key_from_chroma
from backend.services.extractor import extract_metadata
from backend.services.scanner import (
    calculate_sha256,
    get_file_system_metadata,
    is_supported_audio_file,
    scan_directory,
)


@pytest.fixture(name="db_session")
def db_session_fixture():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_scanner_extension_filter():
    assert is_supported_audio_file("song.mp3") is True
    assert is_supported_audio_file("track.FLAC") is True
    assert is_supported_audio_file("audio.wav") is True
    assert is_supported_audio_file("file.txt") is False
    assert is_supported_audio_file("image.jpg") is False


def test_scanner_directory_and_hash():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test dummy audio files
        f1 = os.path.join(tmpdir, "test1.mp3")
        f2 = os.path.join(tmpdir, "test2.flac")
        f3 = os.path.join(tmpdir, "ignore.txt")

        with open(f1, "wb") as f:
            f.write(b"dummy mp3 data content 123")
        with open(f2, "wb") as f:
            f.write(b"dummy flac data content 456")
        with open(f3, "w") as f:
            f.write("text content")

        files = scan_directory(tmpdir)
        assert len(files) == 2
        assert f1 in files
        assert f2 in files

        hash1 = calculate_sha256(f1)
        assert len(hash1) == 64
        assert isinstance(hash1, str)

        meta = get_file_system_metadata(f1)
        assert meta["filename"] == "test1.mp3"
        assert meta["file_size"] > 0


def test_extractor_metadata_fallback():
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp.write(b"dummy audio binary data")
        tmp_path = tmp.name

    try:
        meta = extract_metadata(tmp_path)
        assert meta["filename"] == os.path.basename(tmp_path)
        assert meta["filepath"] == os.path.abspath(tmp_path)
        assert meta["codec"] == "mp3"
        assert meta["sha256"] is not None
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_analyzer_chroma_key_estimation():
    # Test C Major profile (high energy at C [index 0] and E [index 4])
    chroma = np.zeros((12, 10))
    chroma[0, :] = 1.0  # C
    chroma[4, :] = 0.8  # E
    chroma[7, :] = 0.7  # G

    key = estimate_key_from_chroma(chroma)
    assert key == "C Major"

    # Test invalid audio file graceful fallback
    res = analyze_audio_features("non_existent_file.mp3")
    assert res["bpm"] is None
    assert res["musical_key"] is None


def test_song_repository_operations(db_session: Session):
    song_data = {
        "filename": "track.flac",
        "filepath": "/music/artist1/album1/track.flac",
        "sha256": "dummyhash999",
        "title": "Starlight",
        "artist": "Muse",
        "album": "Black Holes",
        "genre": "Rock",
        "duration": 240.0,
    }

    # 1. Upsert (Create)
    song, created = SongRepository.upsert_song(db_session, song_data)
    assert created is True
    assert song.id is not None
    assert song.title == "Starlight"

    # 2. Upsert (Update)
    song_data["title"] = "Starlight (Updated)"
    updated_song, created_again = SongRepository.upsert_song(db_session, song_data)
    assert created_again is False
    assert updated_song.id == song.id
    assert updated_song.title == "Starlight (Updated)"

    # 3. List with search & pagination
    songs, count = SongRepository.list_songs(db_session, search="Starlight", page=1, limit=10)
    assert count == 1
    assert len(songs) == 1
    assert songs[0].artist == "Muse"

    # 4. Delete
    deleted = SongRepository.delete_song(db_session, song.id)
    assert deleted is True
    assert SongRepository.get_by_id(db_session, song.id) is None


def test_scan_worker_execution(db_session: Session, monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        f1 = os.path.join(tmpdir, "song1.mp3")
        with open(f1, "wb") as f:
            f.write(b"dummy mp3 audio content")

        # Create scan job
        job = ScanJob(directory_path=tmpdir, status="pending")
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)

        # Monkeypatch session engine in worker to use our memory DB or run worker
        from backend.workers import scan_worker

        def mock_engine():
            return db_session.bind

        monkeypatch.setattr(scan_worker, "engine", db_session.bind)

        # Run worker with Librosa analysis disabled for speed in unit test
        scan_worker.run_scan_job(
            job_id=job.id,
            directory_path=tmpdir,
            perform_audio_analysis=False,
        )

        db_session.refresh(job)
        assert job.status == "completed"
        assert job.total_files == 1
        assert job.scanned_files == 1
        assert job.added_count == 1
