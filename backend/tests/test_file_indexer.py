"""Tests for the V2 fast-pass indexer (TV2-010, blueprint §33/§34)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from backend.models import File, FileRecording, Recording
from backend.services import file_indexer
from backend.services.file_indexer import index_file, save_audio_features


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _write_audio(path, content: bytes = b"\xff\xfb\x90\x44" + b"\x00" * 417, tags: bool = False):
    from mutagen.id3 import ID3, TIT2, TPE1

    path.write_bytes(content * 5)
    if tags:
        id3 = ID3()
        id3.add(TIT2(encoding=3, text="Test Song"))
        id3.add(TPE1(encoding=3, text="Test Artist"))
        id3.save(str(path))
    else:
        ID3().save(str(path))


def test_index_file_creates_file_recording_and_link(session, tmp_path, monkeypatch):
    audio = tmp_path / "track.mp3"
    _write_audio(audio)

    # Deterministic tags — mutagen on a synthetic MPEG frame is not reliable.
    def fake_extract(filepath):
        return {
            "filename": "track.mp3",
            "filepath": str(audio),
            "sha256": "f" * 64,
            "file_size": audio.stat().st_size,
            "duration": 3.0,
            "title": "Test Song",
            "artist": "Test Artist",
            "codec": "mp3",
            "bitrate": 320000,
            "sample_rate": 44100,
            "channels": 2,
        }

    monkeypatch.setattr(file_indexer, "extract_metadata", fake_extract)

    file, _meta, changed, created = index_file(session, str(audio))

    assert changed is True
    assert created is True
    assert file.id is not None
    assert file.filepath == str(audio)
    assert file.scan_state == "indexed"
    assert file.file_size == audio.stat().st_size
    assert file.extension == ".mp3"
    assert len(file.sha256) == 64

    link = session.exec(select(FileRecording)).first()
    assert link is not None
    assert link.file_id == file.id
    assert link.source == "existing_tag"

    recording = session.get(Recording, link.recording_id)
    assert recording is not None


def test_fast_pass_skips_unchanged_file(session, tmp_path, monkeypatch):
    audio = tmp_path / "track.mp3"
    _write_audio(audio)

    calls = []
    real_extract = file_indexer.extract_metadata

    def counting_extract(filepath):
        calls.append(filepath)
        return real_extract(filepath)

    monkeypatch.setattr(file_indexer, "extract_metadata", counting_extract)

    _, _, changed1, _created1 = index_file(session, str(audio))
    assert changed1 is True
    assert len(calls) == 1

    # Second pass, untouched file: no extraction, no hashing.
    file2, meta2, changed2, created2 = index_file(session, str(audio))
    assert changed2 is False
    assert created2 is False
    assert meta2 == {}
    assert len(calls) == 1
    assert file2.scan_state == "indexed"


def test_changed_file_is_reindexed(session, tmp_path):
    audio = tmp_path / "track.mp3"
    _write_audio(audio)

    _, _, changed1, _created1 = index_file(session, str(audio))
    assert changed1 is True

    # Touch the file (different size) → re-extraction must happen.
    _write_audio(audio, content=b"\xff\xfb\x90\x44" + b"\x00" * 900)
    import os

    os.utime(audio, (0, 0))

    _, meta2, changed2, _created2 = index_file(session, str(audio))
    assert changed2 is True
    assert meta2 != {}


def test_fast_pass_mtime_comparison_is_tz_safe(session, tmp_path):
    audio = tmp_path / "track.mp3"
    _write_audio(audio)

    _, _, _, _ = index_file(session, str(audio))

    file = session.exec(select(File)).one()
    # Simulate SQLite's naive round-trip: stored datetimes come back tz-naive.
    naive = file.modified_at
    file.modified_at = naive.replace(tzinfo=None)
    session.add(file)
    session.commit()

    _, _, changed, _ = index_file(session, str(audio))
    assert changed is False


def test_save_audio_features_is_versioned_and_idempotent(session):
    from backend.models import AudioFeature

    dummy = File(
        filepath="/music/x.mp3",
        filename="x.mp3",
        extension=".mp3",
        sha256="a" * 64,
        file_size=10,
        modified_at=datetime.now(UTC),
    )
    session.add(dummy)
    session.commit()

    save_audio_features(session, dummy.id, {"bpm": 120.5, "musical_key": "C Major"})
    row = session.exec(select(AudioFeature)).one()
    assert row.bpm == Decimal("120.5")
    assert row.musical_key == "C Major"
    assert row.analysis_version is not None

    save_audio_features(session, dummy.id, {"bpm": 125.0, "musical_key": "D Minor"})
    rows = session.exec(select(AudioFeature)).all()
    assert len(rows) == 1
    assert rows[0].bpm == Decimal("125.0")