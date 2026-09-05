import io
import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from mutagen.id3 import ID3
from PIL import Image
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from backend.database.session import get_session
from backend.main import app
from backend.services.scanner import calculate_sha256
from backend.services.tag_writer import (
    embed_cover_art,
    remove_cover_art,
    restore_backup,
    write_text_metadata,
)


def create_dummy_jpeg() -> bytes:
    """Generate dummy JPEG image bytes for testing."""
    img = Image.new("RGB", (100, 100), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def create_dummy_mp3_file() -> str:
    """Create a temporary MP3 file with valid MPEG sync frame headers for Mutagen."""
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)  # noqa: SIM115
    dummy_frame = b"\xff\xfb\x90\x44" + (b"\x00" * 417)
    tmp.write(dummy_frame * 5)
    tmp.close()

    id3 = ID3()
    id3.save(tmp.name)
    return tmp.name


def test_write_text_metadata_mp3():
    tmp_path = create_dummy_mp3_file()

    try:
        new_hash = write_text_metadata(
            tmp_path,
            {
                "title": "Updated Title",
                "artist": "Updated Artist",
                "album": "Updated Album",
                "year": 2026,
            },
        )
        assert len(new_hash) == 64

        # Read back tags
        read_tags = ID3(tmp_path)
        assert str(read_tags.get("TIT2")) == "Updated Title"
        assert str(read_tags.get("TPE1")) == "Updated Artist"
        assert str(read_tags.get("TALB")) == "Updated Album"
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        if os.path.exists(f"{tmp_path}.bak"):
            os.remove(f"{tmp_path}.bak")


def test_embed_and_remove_cover_art():
    tmp_path = create_dummy_mp3_file()

    try:
        dummy_img = create_dummy_jpeg()
        new_hash, cache_path = embed_cover_art(tmp_path, dummy_img)
        assert len(new_hash) == 64
        assert os.path.exists(cache_path)

        # Remove cover art
        updated_hash = remove_cover_art(tmp_path)
        assert len(updated_hash) == 64

    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        if os.path.exists(f"{tmp_path}.bak"):
            os.remove(f"{tmp_path}.bak")


def test_update_metadata_and_cover_api_endpoints(monkeypatch, tmp_path):
    from backend.core.config import settings

    # Point the path sandbox at the test tree (TV2-004)
    music = tmp_path / "music"
    music.mkdir()
    monkeypatch.setattr(settings, "MUSIC_DIR", str(music))

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

    # Create the MP3 inside the sandboxed music dir
    tmp_path = str(music / "test.mp3")
    dummy_frame = b"\xff\xfb\x90\x44" + (b"\x00" * 417)
    with open(tmp_path, "wb") as f:
        f.write(dummy_frame * 5)
    ID3().save(tmp_path)

    try:
        # Seed DB song record (V2 schema, TV2-011b)
        from backend.repositories.song_repository import SongRepository

        with Session(engine) as session:
            view, _created = SongRepository.upsert_song(
                session,
                {
                    "filename": "test.mp3",
                    "filepath": tmp_path,
                    "sha256": "originalhash",
                    "title": "Old Title",
                    "artist": "Old Artist",
                },
                source="existing_tag",
            )
            song_id = view.id

        with TestClient(app) as client:
            # 1. Test PUT /api/songs/{id}/metadata
            res_meta = client.put(
                f"/api/songs/{song_id}/metadata",
                json={
                    "title": "New API Title",
                    "artist": "New API Artist",
                    "year": 2026,
                },
            )
            assert res_meta.status_code == 200
            assert res_meta.json()["title"] == "New API Title"

            # 2. Test POST /api/songs/{id}/cover
            img_bytes = create_dummy_jpeg()
            res_cover = client.post(
                f"/api/songs/{song_id}/cover",
                files={"file": ("cover.jpg", img_bytes, "image/jpeg")},
            )
            assert res_cover.status_code == 200
            assert res_cover.json()["has_cover"] is True

            # 3. Test DELETE /api/songs/{id}/cover
            res_del = client.delete(f"/api/songs/{song_id}/cover")
            assert res_del.status_code == 200
            assert res_del.json()["has_cover"] is False

    finally:
        app.dependency_overrides.clear()
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        if os.path.exists(f"{tmp_path}.bak"):
            os.remove(f"{tmp_path}.bak")


def test_failed_write_restores_byte_identical_backup(monkeypatch):
    tmp_path = create_dummy_mp3_file()
    try:
        original_hash = calculate_sha256(tmp_path)

        def corrupt_and_raise(self, filething, *args, **kwargs):
            path = filething if isinstance(filething, str) else filething.name
            with open(path, "wb") as f:
                f.write(b"simulated mid-write corruption")
            raise RuntimeError("simulated mid-write failure")

        monkeypatch.setattr(ID3, "save", corrupt_and_raise)
        with pytest.raises(RuntimeError):
            write_text_metadata(tmp_path, {"title": "Should Fail"})

        # Auto-restore from .bak must make the file byte-identical again
        assert calculate_sha256(tmp_path) == original_hash
        assert not os.path.exists(f"{tmp_path}.bak")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        if os.path.exists(f"{tmp_path}.bak"):
            os.remove(f"{tmp_path}.bak")


def test_restore_backup_roundtrip():
    tmp_path = create_dummy_mp3_file()
    try:
        with open(tmp_path, "rb") as f:
            original_bytes = f.read()
        original_hash = calculate_sha256(tmp_path)

        # A successful write must not leave a stale .bak behind
        write_text_metadata(tmp_path, {"title": "Mutated"})
        assert calculate_sha256(tmp_path) != original_hash
        assert not os.path.exists(f"{tmp_path}.bak")

        # Undo scenario (§16): restore the pre-change snapshot after a real write
        with open(f"{tmp_path}.bak", "wb") as f:
            f.write(original_bytes)  # pre-change snapshot, as a change_set would store it
        assert restore_backup(tmp_path) is True
        assert calculate_sha256(tmp_path) == original_hash  # byte-identical restore

        # No backup -> restore is a no-op and must not touch the file
        os.remove(f"{tmp_path}.bak")
        assert restore_backup(tmp_path) is False
        assert calculate_sha256(tmp_path) == original_hash
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        if os.path.exists(f"{tmp_path}.bak"):
            os.remove(f"{tmp_path}.bak")
