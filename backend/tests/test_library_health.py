"""Library health API tests (TV2-033, blueprint §14).

Fixture numbers are computed by hand below; the endpoint must return the
§14 shape with exactly those values.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from backend.core.versions import ANALYSIS_VERSION
from backend.database.session import get_session
from backend.main import app
from backend.models import Artwork, AudioFeature, File, FileRecording, MetadataProvenance


def _file_row(session, path: str, sha: str) -> File:
    file = File(
        filepath=path,
        filename=path.rsplit("/", 1)[-1],
        extension=".flac",
        sha256=sha,
        file_size=1,
        modified_at=datetime.now(UTC),
        scan_state="indexed",
        sample_rate=44_100,
    )
    session.add(file)
    session.commit()
    session.refresh(file)
    return file


def _provenance(session, file_id: int, fields: dict[str, str]) -> None:
    for field_name, value in fields.items():
        session.add(
            MetadataProvenance(
                file_id=file_id,
                field_name=field_name,
                value_text=value,
                source="existing_tag",
                confidence=Decimal("90.0"),
            )
        )
    session.commit()


@pytest.fixture(name="client")
def client_fixture(tmp_path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        # F1 — fully healthy file.
        f1 = _file_row(session, "/music/one.flac", "hash-1")
        _provenance(
            session, f1.id or 0,
            {"title": "One", "artist": "Artist", "album": "Album",
             "year": "2020", "track_number": "1"},
        )
        session.add(FileRecording(
            file_id=f1.id or 0, recording_id=1,
            confidence=Decimal("1.0"), source="musicbrainz",
        ))
        # NOTE: recording_id 1 has no seeded recordings row on purpose —
        # SQLite in tests does not enforce FKs.
        session.add(Artwork(file_id=f1.id or 0, source="existing_tag", is_embedded=True))
        session.add(AudioFeature(
            file_id=f1.id or 0, bpm=Decimal(120),
            integrated_lufs=Decimal("-14.0"), analysis_version=ANALYSIS_VERSION,
        ))

        # F2 — incomplete metadata, unidentified, no artwork.
        f2 = _file_row(session, "/music/two.flac", "hash-2")
        _provenance(
            session, f2.id or 0,
            {"title": "Two", "artist": "Artist", "album": "Album"},
        )

        # F3/F4 — same album, F3 deviates on album_artist (minority).
        f3 = _file_row(session, "/music/three.flac", "hash-3")
        _provenance(
            session, f3.id or 0,
            {"title": "Three", "artist": "Artist", "album": "Greatest Hits",
             "album_artist": "B", "year": "2020", "track_number": "2"},
        )
        f4 = _file_row(session, "/music/four.flac", "hash-4")
        _provenance(
            session, f4.id or 0,
            {"title": "Four", "artist": "Artist", "album": "Greatest Hits",
             "album_artist": "A", "year": "2020", "track_number": "3"},
        )
        for f, recording_id in ((f3, 2), (f4, 3)):
            session.add(FileRecording(
                file_id=f.id or 0, recording_id=recording_id,
                confidence=Decimal("1.0"), source="musicbrainz",
            ))

        # F5 — exact duplicate of F1 + suspicious hi-res claim.
        f5 = _file_row(session, "/music/one-copy.flac", "hash-1")
        f5.sample_rate = 176_400
        session.add(f5)
        _provenance(
            session, f5.id or 0,
            {"title": "One", "artist": "Artist", "album": "Album",
             "year": "2020", "track_number": "1"},
        )
        session.add(AudioFeature(
            file_id=f5.id or 0,
            integrated_lufs=Decimal("-14.0"),
            frequency_ceiling_hz=Decimal(20000),
            analysis_version=ANALYSIS_VERSION,
        ))
        session.commit()

    def get_test_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_library_health_shape_and_numbers(client: TestClient):
    body = client.get("/api/library/health").json()
    # §14 shape, exactly these top-level keys.
    assert set(body) == {
        "metadata_health", "identification_health", "artwork_health",
        "audio_analysis_health", "duplicate_health", "issues",
    }
    assert set(body["issues"]) == {
        "missing_artwork", "unidentified", "duplicates",
        "inconsistent_album_artist", "possible_upsample",
    }
    # Hand-computed fixture numbers (5 files).
    assert body["metadata_health"] == 80.0          # F1, F3, F4, F5 complete
    assert body["identification_health"] == 60.0    # F1, F3, F4 linked
    assert body["artwork_health"] == 20.0           # only F1 has embedded art
    assert body["audio_analysis_health"] == 40.0    # F1, F5 fresh analysis
    assert body["duplicate_health"] == 60.0         # F1+F5 duplicated → 100-40
    assert body["issues"] == {
        "missing_artwork": 4,        # F2..F5
        "unidentified": 2,           # F2, F5
        "duplicates": 2,             # F1, F5
        "inconsistent_album_artist": 1,  # F3 (minority album_artist)
        "possible_upsample": 1,      # F5 (176.4 kHz claim, ~20 kHz ceiling)
    }


def test_issue_drilldowns(client: TestClient):
    unidentified = client.get("/api/library/issues/unidentified").json()
    assert [row["file_id"] for row in unidentified] == [2, 5]

    duplicates = client.get("/api/library/issues/duplicates").json()
    assert len(duplicates) == 1
    assert duplicates[0]["classification"] == "EXACT_FILE_DUPLICATE"
    assert sorted((duplicates[0]["file_id_a"], duplicates[0]["file_id_b"])) == [1, 5]

    inconsistent = client.get("/api/library/issues/inconsistent_album_artist").json()
    assert len(inconsistent) == 1
    assert inconsistent[0]["expected_album_artist"] == "A"
    assert inconsistent[0]["actual_album_artist"] == "B"

    upsample = client.get("/api/library/issues/possible_upsample").json()
    assert len(upsample) == 1
    assert upsample[0]["sample_rate"] == 176_400
    assert upsample[0]["frequency_ceiling_hz"] == 20000.0

    missing_art = client.get("/api/library/issues/missing_artwork").json()
    assert [row["file_id"] for row in missing_art] == [2, 3, 4, 5]


def test_unknown_issue_type_400(client: TestClient):
    res = client.get("/api/library/issues/nonexistent")
    assert res.status_code == 400
    # main.py maps HTTPException details to {error, message, status}.
    assert "missing_artwork" in res.json()["message"]


def test_empty_library_is_healthy():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        from backend.intelligence.health import compute_library_health

        health = compute_library_health(session)
    assert health["metadata_health"] == 100.0
    assert all(count == 0 for count in health["issues"].values())