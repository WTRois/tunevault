"""Release matching tests (TV2-018, blueprint §10) — mocked MusicBrainz data."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from backend.identification.release_match import match_release, rank_releases
from backend.models import File, FileRelease, Recording, Release, ReleaseTrack
from backend.providers.base import ProviderMatch

ORIGINAL = {
    "id": "rel-original",
    "title": "The Dark Side of the Moon",
    "date": "1973-03-01",
    "country": "GB",
    "release-group": {
        "id": "rg-1",
        "title": "The Dark Side of the Moon",
        "primary-type": "Album",
    },
}

COMPILATION = {
    "id": "rel-comp",
    "title": "Best of Pink Floyd",
    "date": "2001-11-05",
    "country": "US",
    "release-group": {
        "id": "rg-2",
        "title": "Best of Pink Floyd",
        "primary-type": "Album",
        "secondary-types": ["Compilation"],
    },
}


class StubReleaseProvider:
    """lookup_release stub keyed by MBID (no network)."""

    name = "musicbrainz"

    def __init__(self, details_by_mbid):
        self.details = details_by_mbid

    async def lookup_release(self, mbid: str):
        return self.details[mbid]


def _details(release: dict, recording_mbid: str = "rec-1", length_ms: int = 421000) -> dict:
    detail = dict(release)
    detail["media"] = [
        {
            "position": 1,
            "format": "CD",
            "track-list": [
                {"position": 4, "title": "Time", "length": length_ms, "recording": {"id": recording_mbid}}
            ],
        }
    ]
    return detail


def _match(releases: list[dict]) -> ProviderMatch:
    return ProviderMatch(
        source="musicbrainz",
        title="Time",
        artist="Pink Floyd",
        release_title="The Dark Side of the Moon",
        duration_ms=421000,
        recording_mbid="rec-1",
        payload={"releases": releases},
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


def _seed_file(session: Session) -> File:
    file = File(
        filepath="/music/04 - Time.flac",
        filename="04 - Time.flac",
        extension=".flac",
        sha256="a" * 64,
        file_size=40_000_000,
        modified_at=datetime.now(UTC),
        duration_ms=421_500,
        scan_state="indexed",
    )
    session.add(file)
    session.commit()
    session.refresh(file)
    return file


def test_rank_prefers_original_over_compilation():
    ranked = rank_releases([COMPILATION, ORIGINAL])
    assert ranked[0]["id"] == "rel-original"


def test_rank_prefers_specific_country():
    ranked = rank_releases(
        [ORIGINAL, COMPILATION],
        prefs={"preference": "prefer_specific_country", "country": "US", "label": ""},
    )
    assert ranked[0]["id"] == "rel-comp"


def test_rank_prefers_remaster():
    remaster = dict(ORIGINAL, id="rel-remaster", date="2011", disambiguation="2011 Remaster")
    ranked = rank_releases(
        [ORIGINAL, remaster],
        prefs={"preference": "prefer_remaster", "country": "", "label": ""},
    )
    assert ranked[0]["id"] == "rel-remaster"


def test_match_release_fills_file_releases(session):
    """Acceptance: original wins over compilation; file_releases is filled."""
    import asyncio

    file = _seed_file(session)
    provider = StubReleaseProvider(
        {
            "rel-original": _details(ORIGINAL),
            "rel-comp": _details(COMPILATION),
        }
    )

    result = asyncio.run(
        match_release(
            session, file, _match([COMPILATION, ORIGINAL]), provider=provider, recording_row_id=None
        )
    )
    # Without a recording row the release track cannot be linked.
    assert result is None

    recording = Recording(title="Time", artist_credit="Pink Floyd", musicbrainz_recording_id="rec-1")
    session.add(recording)
    session.commit()
    session.refresh(recording)

    result = asyncio.run(
        match_release(
            session, file, _match([COMPILATION, ORIGINAL]), provider=provider, recording_row_id=recording.id
        )
    )
    assert result is not None
    assert result["release_mbid"] == "rel-original"
    assert result["release_title"] == "The Dark Side of the Moon"
    assert result["track_number"] == 4
    assert result["disc_number"] == 1

    release = session.exec(select(Release)).one()
    assert release.musicbrainz_release_id == "rel-original"

    track = session.exec(select(ReleaseTrack)).one()
    assert track.recording_id == recording.id
    assert track.track_number == 4

    link = session.exec(select(FileRelease)).one()
    assert link.file_id == file.id
    assert link.release_id == release.id
    assert link.release_track_id == track.id


def test_match_release_falls_through_when_tracklist_lacks_recording(session):
    """§10 #8/#9: verify the tracklist — a release without the recording is skipped."""
    import asyncio

    file = _seed_file(session)
    recording = Recording(title="Time", artist_credit="Pink Floyd", musicbrainz_recording_id="rec-1")
    session.add(recording)
    session.commit()
    session.refresh(recording)

    provider = StubReleaseProvider(
        {
            # Original's tracklist does NOT contain the recording → fall through.
            "rel-original": _details(ORIGINAL, recording_mbid="rec-other"),
            "rel-comp": _details(COMPILATION),
        }
    )

    result = asyncio.run(
        match_release(
            session,
            file,
            _match([COMPILATION, ORIGINAL]),
            provider=provider,
            recording_row_id=recording.id,
        )
    )
    assert result is not None
    assert result["release_mbid"] == "rel-comp"
    assert session.exec(select(FileRelease)).one().release_id == result["release_id"]


def test_match_release_rejects_duration_mismatch(session):
    """§10 #9 duration consistency: >7s mismatch cannot be the matched track."""
    import asyncio

    file = _seed_file(session)
    recording = Recording(title="Time", artist_credit="Pink Floyd", musicbrainz_recording_id="rec-1")
    session.add(recording)
    session.commit()
    session.refresh(recording)

    provider = StubReleaseProvider(
        {
            "rel-original": _details(ORIGINAL, length_ms=300000),  # 2 minutes off
            "rel-comp": _details(COMPILATION),
        }
    )

    result = asyncio.run(
        match_release(
            session,
            file,
            _match([COMPILATION, ORIGINAL]),
            provider=provider,
            recording_row_id=recording.id,
        )
    )
    assert result is not None
    assert result["release_mbid"] == "rel-comp"


def test_match_release_without_provider_is_a_noop(session):
    """Endpoint stubs may pass provider=None — nothing is written (§10 best effort)."""
    import asyncio

    file = _seed_file(session)
    result = asyncio.run(match_release(session, file, _match([ORIGINAL]), provider=None))
    assert result is None
    assert session.exec(select(FileRelease)).all() == []