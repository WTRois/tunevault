"""Apply + verify + undo engine tests (TV2-026, blueprint §16, §2.4).

Roundtrip acceptance: apply → undo restores byte-identical state; the
verifier catches interrupted/corrupted moves.
"""

import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from mutagen.id3 import ID3, TIT2
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from backend.core.config import settings
from backend.models import Change, ChangeSet, File, MetadataProvenance
from backend.organization.apply import apply_change_set, undo_change_set
from backend.services.scanner import calculate_sha256


def _dummy_mp3(path) -> None:
    with open(path, "wb") as f:
        f.write((b"\xff\xfb\x90\x44" + b"\x00" * 417) * 5)
    ID3().save(str(path))


def _add_title(path, title: str) -> None:
    id3 = ID3(str(path))
    id3.add(TIT2(encoding=3, text=title))
    id3.save(str(path))


@pytest.fixture(name="env")
def env_fixture(tmp_path, monkeypatch):
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

    source = music / "raw_name.mp3"
    _dummy_mp3(source)
    _add_title(source, "Old Title")

    with Session(engine) as session:
        file = File(
            filepath=str(source),
            filename="raw_name.mp3",
            extension=".mp3",
            sha256=calculate_sha256(str(source)),
            file_size=source.stat().st_size,
            modified_at=datetime.now(UTC),
            scan_state="indexed",
        )
        session.add(file)
        session.commit()
        file_id = file.id

        change_set = ChangeSet(name="test-apply", status="pending")
        session.add(change_set)
        session.commit()
        change = Change(
            change_set_id=change_set.id or 0,
            file_id=file_id or 0,
            operation="metadata_update",
            old_value_json=json.dumps({"title": "Old Title", "album": None}),
            new_value_json=json.dumps({"title": "New Title", "album": "New Album"}),
            old_path=str(source),
            new_path="Artist/[2020] Album/01 - New Title.mp3",
            verification_status="pending",
        )
        session.add(change)
        session.commit()
        # Pre-change tag evidence so provenance refresh has something to update.
        session.add(
            MetadataProvenance(
                file_id=file_id or 0,
                field_name="title",
                value_text="Old Title",
                source="existing_tag",
                confidence=Decimal("1.0"),
            )
        )
        session.commit()
        return {
            "engine": engine,
            "file_id": file_id,
            "change_set_id": change_set.id,
            "change_id": change.id,
            "source": source,
        }


def _read_title(path) -> str:
    return str(ID3(str(path)).get("TIT2"))


def test_apply_moves_rewrites_tags_and_records_backup(env):
    with Session(env["engine"]) as session:
        result = apply_change_set(session, env["change_set_id"])

    assert result["applied"] == 1
    new_path = str(Path(settings.MUSIC_DIR) / "Artist/[2020] Album/01 - New Title.mp3")
    assert os.path.exists(new_path)
    assert not os.path.exists(env["source"])  # original removed only after verify
    assert _read_title(new_path) == "New Title"

    with Session(env["engine"]) as session:
        change = session.get(Change, env["change_id"])
        assert change.verification_status == "verified"
        assert change.backup_path and os.path.exists(change.backup_path)
        file = session.get(File, env["file_id"])
        assert file.filepath == new_path
        assert file.sha256 == calculate_sha256(new_path)
        cs = session.get(ChangeSet, env["change_set_id"])
        assert cs.status == "applied"


def test_apply_then_undo_restores_byte_identical_state(env):
    original_sha = calculate_sha256(str(env["source"]))
    original_bytes = env["source"].read_bytes()

    with Session(env["engine"]) as session:
        apply_change_set(session, env["change_set_id"])

    with Session(env["engine"]) as session:
        result = undo_change_set(session, env["change_set_id"])
    assert result["undone"] == 1

    # Byte-identical restoration at the original path.
    assert env["source"].read_bytes() == original_bytes
    assert calculate_sha256(str(env["source"])) == original_sha
    assert _read_title(env["source"]) == "Old Title"

    moved_path = Path(settings.MUSIC_DIR) / "Artist/[2020] Album/01 - New Title.mp3"
    assert not os.path.exists(moved_path)

    with Session(env["engine"]) as session:
        file = session.get(File, env["file_id"])
        assert file.filepath == str(env["source"])
        assert file.sha256 == original_sha
        cs = session.get(ChangeSet, env["change_set_id"])
        assert cs.status == "rolled_back"
        assert cs.rolled_back_at is not None


def test_apply_refuses_fs_writes_in_dry_run(env, monkeypatch):
    monkeypatch.setattr(settings, "ORGANIZE_DRY_RUN", True)
    original_bytes = env["source"].read_bytes()

    with Session(env["engine"]) as session:
        result = apply_change_set(session, env["change_set_id"])

    assert result["dry_run"] is True
    assert result["applied"] == 0
    assert env["source"].read_bytes() == original_bytes  # untouched
    with Session(env["engine"]) as session:
        cs = session.get(ChangeSet, env["change_set_id"])
        assert cs.status == "dry_run"


def test_verification_detects_corrupted_move(env, monkeypatch):
    """Acceptance: the verifier must catch an interrupted/corrupted move."""
    from backend.organization import apply as apply_module

    # Make every hash read of the TARGET return a wrong value — the verify
    # step must then fail and keep the original file intact.
    real_sha_of = apply_module._sha_of
    target_marker = "01 - New Title.mp3"

    def lying_sha_of(path):
        if target_marker in str(path):
            return "0" * 64  # corrupted target hash
        return real_sha_of(path)

    monkeypatch.setattr(apply_module, "_sha_of", lying_sha_of)

    with Session(env["engine"]) as session:
        result = apply_change_set(session, env["change_set_id"])

    assert result["failed"] == 1
    # The original is intact — never destroyed by a failed move.
    assert os.path.exists(env["source"])
    assert _read_title(env["source"]) == "New Title"  # tags were already applied
    moved = Path(settings.MUSIC_DIR) / "Artist/[2020] Album/01 - New Title.mp3"
    assert not moved.exists()  # the failed copy was removed

    with Session(env["engine"]) as session:
        change = session.get(Change, env["change_id"])
        assert change.verification_status == "verify_failed"


def test_undo_without_backup_reports_failure(env):
    with Session(env["engine"]) as session:
        apply_change_set(session, env["change_set_id"])
        # Sabotage: lose the backup artifact (as a disk failure would).
        change = session.get(Change, env["change_id"])
        backup = change.backup_path
        os.remove(backup)

    with Session(env["engine"]) as session:
        result = undo_change_set(session, env["change_set_id"])

    assert result["failed"] >= 1
    assert result["undone"] == 0