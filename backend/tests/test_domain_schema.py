"""Round-trip tests for the V2 domain schema (TV2-009, blueprint §5.1–§5.15)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from backend.models import (
    Artist,
    Artwork,
    AudioFeature,
    Change,
    ChangeSet,
    File,
    FileRecording,
    FileRelease,
    Fingerprint,
    MetadataCandidate,
    MetadataProvenance,
    Recording,
    Release,
    ReleaseGroup,
    ReleaseTrack,
)


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


def _file(session: Session) -> File:
    file = File(
        filepath="/music/album/track01.flac",
        filename="track01.flac",
        extension=".flac",
        sha256="a" * 64,
        file_size=1000,
        modified_at=datetime.now(UTC),
        duration_ms=180000,
        codec="flac",
        sample_rate=44100,
        bit_depth=16,
        channels=2,
        scan_state="extracted",
    )
    session.add(file)
    session.commit()
    session.refresh(file)
    return file


def test_file_roundtrip(session: Session):
    file = _file(session)
    assert file.id is not None
    fetched = session.get(File, file.id)
    assert fetched.sha256 == "a" * 64
    assert fetched.scan_state == "extracted"


def test_file_filepath_unique(session: Session):
    _file(session)
    duplicate = File(
        filepath="/music/album/track01.flac",
        filename="dup.flac",
        extension=".flac",
        sha256="b" * 64,
        file_size=10,
        modified_at=datetime.now(UTC),
    )
    session.add(duplicate)
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        session.commit()


def test_recording_artist_and_file_link(session: Session):
    artist = Artist(name="Test Artist")
    recording = Recording(
        title="Test Song",
        artist_credit="Test Artist",
        duration_ms=180000,
        musicbrainz_recording_id="mbid-123",
    )
    session.add(artist)
    session.add(recording)
    session.commit()

    file = _file(session)
    link = FileRecording(
        file_id=file.id,
        recording_id=recording.id,
        confidence=Decimal("0.95"),
        source="musicbrainz",
    )
    session.add(link)
    session.commit()

    fetched = session.exec(select(FileRecording).where(FileRecording.file_id == file.id)).one()
    assert fetched.recording_id == recording.id


def test_release_track_unique_position(session: Session):
    group = ReleaseGroup(title="Album")
    session.add(group)
    session.commit()

    release = Release(release_group_id=group.id, title="Album")
    session.add(release)
    session.commit()

    recording = Recording(title="Song")
    session.add(recording)
    session.commit()

    track = ReleaseTrack(
        release_id=release.id,
        recording_id=recording.id,
        disc_number=1,
        track_number=1,
        position=1,
    )
    session.add(track)
    session.commit()

    from sqlalchemy.exc import IntegrityError

    duplicate = ReleaseTrack(
        release_id=release.id,
        recording_id=recording.id,
        disc_number=1,
        track_number=1,
        position=2,
    )
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        session.commit()


def test_fingerprint_and_audio_features_unique_per_file(session: Session):
    file = _file(session)
    session.add(
        Fingerprint(
            file_id=file.id, provider="chromaprint", fingerprint="fpdata", duration_ms=180000,
            fingerprint_version="v1",
        )
    )
    session.add(
        AudioFeature(file_id=file.id, bpm=Decimal("120.5"), analysis_version="2026.1")
    )
    session.commit()

    from sqlalchemy.exc import IntegrityError

    session.add(
        Fingerprint(
            file_id=file.id, provider="chromaprint", fingerprint="dup", duration_ms=1,
            fingerprint_version="v1",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_candidate_provenance_changeset_chain(session: Session):
    file = _file(session)
    candidate = MetadataCandidate(
        file_id=file.id,
        source="musicbrainz",
        payload_json='{"title": "Test Song"}',
        score=Decimal("0.97"),
        confidence_level="high",
        status="pending",
    )
    session.add(candidate)
    session.commit()

    provenance = MetadataProvenance(
        file_id=file.id,
        field_name="title",
        value_text="Test Song",
        source="musicbrainz",
        confidence=Decimal("0.97"),
        candidate_id=candidate.id,
    )
    change_set = ChangeSet(name="Test changeset")
    session.add(provenance)
    session.add(change_set)
    session.commit()

    change = Change(
        change_set_id=change_set.id,
        file_id=file.id,
        operation="metadata_update",
        old_value_json='{"title": null}',
        new_value_json='{"title": "Test Song"}',
    )
    session.add(change)
    session.commit()

    fetched = session.exec(select(Change).where(Change.change_set_id == change_set.id)).one()
    assert fetched.operation == "metadata_update"
    assert fetched.file_id == file.id


def test_artwork_with_release(session: Session):
    group = ReleaseGroup(title="Album")
    session.add(group)
    session.commit()
    release = Release(release_group_id=group.id, title="Album")
    session.add(release)
    session.commit()

    artwork = Artwork(
        release_id=release.id,
        source="coverartarchive",
        url="https://example.com/front.jpg",
        type="front",
        is_embedded=False,
        quality_score=Decimal("0.9"),
    )
    session.add(artwork)
    session.commit()

    fetched = session.exec(select(Artwork).where(Artwork.release_id == release.id)).one()
    assert fetched.type == "front"
    assert fetched.is_embedded is False


def test_file_release_link(session: Session):
    group = ReleaseGroup(title="Album")
    session.add(group)
    session.commit()
    release = Release(release_group_id=group.id, title="Album")
    session.add(release)
    recording = Recording(title="Song")
    session.add(recording)
    session.commit()
    track = ReleaseTrack(
        release_id=release.id, recording_id=recording.id, disc_number=1, track_number=1, position=1
    )
    session.add(track)
    session.commit()

    file = _file(session)
    link = FileRelease(
        file_id=file.id,
        release_id=release.id,
        release_track_id=track.id,
        confidence=Decimal("0.9"),
        source="musicbrainz",
    )
    session.add(link)
    session.commit()

    fetched = session.exec(select(FileRelease).where(FileRelease.file_id == file.id)).one()
    assert fetched.release_track_id == track.id