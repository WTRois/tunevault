"""Duplicate detection tests (TV2-032, blueprint §13) — suggest-only.

Synthetic chromaprint streams (32-bit words) drive the comparator; no
fpcalc binary is needed. The module must never contain a delete path.
"""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from backend.intelligence.duplicates import (
    AUDIO_SIMILARITY_MIN,
    duplicate_file_ids,
    find_duplicates,
    fingerprint_similarity,
)
from backend.models import (
    File,
    FileRecording,
    FileRelease,
    Fingerprint,
    Recording,
    Release,
    ReleaseGroup,
    ReleaseTrack,
)

_WORDS = [0x12345678, 0x9ABCDEF0, 0x0F1E2D3C, 0x55AA55AA, 0x13579BDF,
          0x2468ACE0, 0xDEADBEEF, 0xFEEDC0DE, 0x12345678, 0x9ABCDEF0]


def _fingerprint_string(words) -> str:
    return ",".join(str(w & 0xFFFFFFFF) for w in words)


def _similar_stream() -> str:
    # One bit flipped per word → ~31/32 bit agreement.
    return _fingerprint_string([w ^ 0x1 for w in _WORDS])


def _dissimilar_stream() -> str:
    return _fingerprint_string([~w for w in _WORDS])


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


def _file(session, path: str, sha: str) -> File:
    file = File(
        filepath=path,
        filename=Path(path).name,
        extension=".flac",
        sha256=sha,
        file_size=1,
        modified_at=datetime.now(UTC),
        scan_state="indexed",
    )
    session.add(file)
    session.commit()
    session.refresh(file)
    return file


def _fingerprint(session, file_id: int, raw: str, duration_ms: int = 180_000) -> None:
    session.add(
        Fingerprint(
            file_id=file_id,
            provider="acoustid",
            fingerprint=raw,
            duration_ms=duration_ms,
            fingerprint_version="1",
        )
    )
    session.commit()


def _recording(session, title="Rec") -> Recording:
    recording = Recording(title=title)
    session.add(recording)
    session.commit()
    session.refresh(recording)
    return recording


def _release(session, title="Rel") -> Release:
    group = ReleaseGroup(title=f"{title}-group")
    session.add(group)
    session.commit()
    session.refresh(group)
    release = Release(title=title, release_group_id=group.id or 0)
    session.add(release)
    session.commit()
    session.refresh(release)
    return release


def _link(session, file_id: int, recording_id: int, release_id: int | None = None) -> None:
    session.add(
        FileRecording(
            file_id=file_id, recording_id=recording_id, confidence=Decimal("1.0"),
            source="musicbrainz",
        )
    )
    if release_id is not None:
        # Two formats of the same release track share ONE ReleaseTrack row
        # (unique constraint on release/position/recording).
        release_track = session.exec(
            select(ReleaseTrack).where(
                ReleaseTrack.release_id == release_id,
                ReleaseTrack.recording_id == recording_id,
            )
        ).first()
        if release_track is None:
            release_track = ReleaseTrack(
                release_id=release_id,
                recording_id=recording_id,
                disc_number=1,
                track_number=1,
                position=1,
            )
            session.add(release_track)
            session.flush()
        session.add(
            FileRelease(
                file_id=file_id,
                release_id=release_id,
                release_track_id=release_track.id or 0,
                confidence=Decimal("1.0"),
                source="musicbrainz",
            )
        )
    session.commit()


def test_similarity_comparator():
    identical = fingerprint_similarity(_fingerprint_string(_WORDS), _fingerprint_string(_WORDS))
    assert identical is not None and identical > 0.99

    similar = fingerprint_similarity(_fingerprint_string(_WORDS), _similar_stream())
    assert similar is not None and similar > AUDIO_SIMILARITY_MIN

    dissimilar = fingerprint_similarity(_fingerprint_string(_WORDS), _dissimilar_stream())
    assert dissimilar is not None and dissimilar < AUDIO_SIMILARITY_MIN

    assert fingerprint_similarity(_fingerprint_string(_WORDS), None) is None
    assert fingerprint_similarity("1,2,3", "4,5,6") is None  # too short to judge


def test_exact_duplicates_detected(session):
    _file(session, "/music/a.flac", "same-hash")
    _file(session, "/music/b.flac", "same-hash")
    _file(session, "/music/c.flac", "other-hash")

    pairs = find_duplicates(session)
    assert len(pairs) == 1
    assert pairs[0]["classification"] == "EXACT_FILE_DUPLICATE"
    assert pairs[0]["similarity"] == 1.0
    assert duplicate_file_ids(session) == {1, 2}


def test_audio_duplicates_by_fingerprint(session):
    base = _file(session, "/music/base.flac", "hash-a")
    other = _file(session, "/music/other.flac", "hash-b")
    stranger = _file(session, "/music/stranger.flac", "hash-c")
    _fingerprint(session, base.id or 0, _fingerprint_string(_WORDS), 180_000)
    _fingerprint(session, other.id or 0, _similar_stream(), 181_000)  # within ±3 s window
    _fingerprint(session, stranger.id or 0, _dissimilar_stream(), 180_500)

    pairs = find_duplicates(session)
    assert len(pairs) == 1
    assert pairs[0]["classification"] == "AUDIO_DUPLICATE"
    assert pairs[0]["file_id_a"] == base.id
    assert pairs[0]["file_id_b"] == other.id
    assert pairs[0]["similarity"] is not None and pairs[0]["similarity"] > AUDIO_SIMILARITY_MIN
    # The acoustically different file is never reported.
    assert all(stranger.id not in (p["file_id_a"], p["file_id_b"]) for p in pairs)


def test_recording_link_classifications(session):
    same_release = _release(session, "Album")
    other_release = _release(session, "Compilation")
    recording = _recording(session)

    a = _file(session, "/music/a.flac", "hash-a")
    b = _file(session, "/music/b.flac", "hash-b")
    c = _file(session, "/music/c.flac", "hash-c")
    _link(session, a.id or 0, recording.id or 0, same_release.id)
    _link(session, b.id or 0, recording.id or 0, same_release.id)
    _link(session, c.id or 0, recording.id or 0, other_release.id)

    pairs = find_duplicates(session)
    by_classification = {p["classification"] for p in pairs}
    # Same release, same recording → redundant copy; different release → informational.
    assert "SAME_RECORDING_DIFFERENT_FORMAT" in by_classification
    assert "SAME_RECORDING_DIFFERENT_RELEASE" in by_classification

    # Only the redundant same-release copies count as problem duplicates.
    assert duplicate_file_ids(session) == {a.id, b.id}


def test_acoustic_mismatch_outranks_recording_link(session):
    release = _release(session)
    recording = _recording(session)
    a = _file(session, "/music/a.flac", "hash-a")
    b = _file(session, "/music/b.flac", "hash-b")
    _link(session, a.id or 0, recording.id or 0, release.id)
    _link(session, b.id or 0, recording.id or 0, release.id)
    # Acoustically different despite the shared link — nothing is suggested.
    _fingerprint(session, a.id or 0, _fingerprint_string(_WORDS), 180_000)
    _fingerprint(session, b.id or 0, _dissimilar_stream(), 180_000)

    assert find_duplicates(session) == []


def test_module_has_no_delete_operations():
    """Acceptance: the duplicates module contains no delete code path."""
    import ast

    import backend.intelligence.duplicates as module

    tree = ast.parse(Path(module.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            assert name not in {
                "remove", "delete", "unlink", "rmtree", "removedirs",
            }, f"duplicates module must not call {name!r}"