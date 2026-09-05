"""Artwork pipeline tests (TV2-021/022/023, blueprint §11) — mocked CAA."""

import io
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from backend.api.endpoints import artwork as artwork_module
from backend.artwork.quality import artwork_quality_score
from backend.artwork.selector import ArtworkCandidate, select_artwork
from backend.artwork.validator import validate_artwork
from backend.core.config import settings
from backend.database.session import get_session
from backend.main import app
from backend.models import Artwork, File, FileRelease, Release, ReleaseGroup, ReleaseTrack


def make_image(width: int = 600, height: int = 600, fmt: str = "JPEG") -> bytes:
    img = Image.new("RGB", (width, height), color="purple")
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


# ---------- validator ----------


def test_validator_accepts_square_cover():
    ok, size = validate_artwork(make_image(500, 500))
    assert ok is True
    assert size == (500, 500)


def test_validator_rejects_too_small():
    ok, size = validate_artwork(make_image(200, 200))
    assert ok is False
    assert size == (200, 200)


def test_validator_rejects_extreme_aspect_ratio():
    ok, _ = validate_artwork(make_image(1000, 100))
    assert ok is False


def test_validator_rejects_corrupt_data():
    ok, size = validate_artwork(b"not an image")
    assert ok is False
    assert size is None


# ---------- quality (§11 weights 40/25/15/10/10) ----------


def test_quality_prefers_higher_resolution():
    small = make_image(350, 350)
    big = make_image(1000, 1000)
    assert artwork_quality_score(big, "coverartarchive") > artwork_quality_score(
        small, "coverartarchive"
    )


def test_quality_prefers_trusted_source():
    image = make_image(500, 500)
    assert artwork_quality_score(image, "coverartarchive") > artwork_quality_score(image, "youtube")


def test_quality_prefers_png_over_jpeg():
    png = artwork_quality_score(make_image(500, 500, fmt="PNG"), "coverartarchive", "image/png")
    jpg = artwork_quality_score(make_image(500, 500), "coverartarchive", "image/jpeg")
    assert png > jpg


def test_quality_zero_for_invalid_image():
    assert artwork_quality_score(b"garbage", "coverartarchive") == 0.0


# ---------- selector (§11 policy) ----------


def _candidate(front: bool, score: float, side: int = 600) -> ArtworkCandidate:
    return ArtworkCandidate(
        image_bytes=make_image(side, side),
        source="coverartarchive",
        url=f"https://caa.test/{front}-{score}.jpg",
        front=front,
        mime_type="image/jpeg",
        width=side,
        height=side,
        quality_score=score,
    )


def test_selector_front_cover_beats_higher_scored_back():
    back = _candidate(front=False, score=95.0)
    front = _candidate(front=True, score=40.0)
    assert select_artwork([back, front]).front is True


def test_selector_quality_breaks_ties_between_fronts():
    best = _candidate(front=True, score=80.0)
    other = _candidate(front=True, score=60.0)
    assert select_artwork([other, best]).quality_score == 80.0


# ---------- endpoints (mocked CAA, §18 artwork section) ----------


@dataclass
class StubImage:
    url: str
    front: bool
    type: str | None
    mime_type: str | None = "image/jpeg"


class StubCAA:
    """CoverArtProvider stub — no network."""

    name = "coverartarchive"

    def __init__(self, images, image_bytes):
        self.images = images
        self.image_bytes = image_bytes

    async def release_covers(self, mbid: str):
        return self.images

    async def download(self, url: str) -> bytes:
        return self.image_bytes[url]


def _dummy_mp3(path) -> None:
    from mutagen.id3 import ID3

    with open(path, "wb") as f:
        f.write((b"\xff\xfb\x90\x44" + b"\x00" * 417) * 5)
    ID3().save(str(path))


@pytest.fixture(name="env")
def env_fixture(monkeypatch, tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    covers = tmp_path / "covers"
    covers.mkdir()
    monkeypatch.setattr(settings, "MUSIC_DIR", str(music))
    monkeypatch.setattr(settings, "COVERS_DIR", str(covers))

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    audio_path = music / "track.mp3"
    _dummy_mp3(audio_path)

    with Session(engine) as session:
        group = ReleaseGroup(title="Meteora")
        session.add(group)
        session.commit()
        release = Release(
            release_group_id=group.id or 0,
            musicbrainz_release_id="rel-mbid-1",
            title="Meteora",
        )
        session.add(release)
        session.commit()
        file = File(
            filepath=str(audio_path),
            filename="track.mp3",
            extension=".mp3",
            sha256="a" * 64,
            file_size=1000,
            modified_at=datetime.now(UTC),
            scan_state="indexed",
        )
        session.add(file)
        session.commit()
        track = ReleaseTrack(
            release_id=release.id or 0,
            recording_id=1,
            disc_number=1,
            track_number=1,
            position=1,
        )
        session.add(track)
        session.commit()
        session.add(
            FileRelease(
                file_id=file.id or 0,
                release_id=release.id or 0,
                release_track_id=track.id or 0,
                confidence=Decimal("1.0"),
                source="musicbrainz",
            )
        )
        session.commit()

    def get_test_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_artwork_search_stores_candidates(env: TestClient, monkeypatch):
    good = make_image(800, 800)
    tiny = make_image(100, 100)  # below MIN_DIMENSION → filtered by validator
    images = [
        StubImage(url="https://caa.test/front.jpg", front=True, type="Front"),
        StubImage(url="https://caa.test/tiny.jpg", front=False, type="Other"),
    ]
    monkeypatch.setattr(
        artwork_module,
        "_caa_provider",
        lambda: StubCAA(
            images,
            {"https://caa.test/front.jpg": good, "https://caa.test/tiny.jpg": tiny},
        ),
    )

    res = env.post("/api/files/1/artwork/search")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1  # tiny image filtered
    assert data[0]["type"] == "front"
    assert data[0]["width"] == 800
    assert data[0]["quality_score"] > 0

    # Bytes cached on disk (§11: store artwork independently).
    from pathlib import Path

    assert Path(data[0]["local_path"]).exists()


def test_artwork_apply_embeds_cover(env: TestClient, monkeypatch):
    images = [StubImage(url="https://caa.test/front.jpg", front=True, type="Front")]
    monkeypatch.setattr(
        artwork_module,
        "_caa_provider",
        lambda: StubCAA(images, {"https://caa.test/front.jpg": make_image(500, 500)}),
    )

    res_search = env.post("/api/files/1/artwork/search")
    assert res_search.status_code == 200
    artwork_id = res_search.json()[0]["id"]

    res_apply = env.post("/api/files/1/artwork/apply", json={"artwork_id": artwork_id})
    assert res_apply.status_code == 200
    assert res_apply.json()["sha256"] != "a" * 64

    # The artwork row is flagged embedded and the physical file really changed.
    from mutagen.id3 import ID3

    session = next(app.dependency_overrides[get_session]())
    row = session.exec(select(Artwork)).one()
    assert row.is_embedded is True
    file = session.get(File, 1)
    id3 = ID3(file.filepath)
    assert any(k.startswith("APIC") for k in id3)


def test_release_artworks_listing(env: TestClient, monkeypatch):
    images = [StubImage(url="https://caa.test/front.jpg", front=True, type="Front")]
    monkeypatch.setattr(
        artwork_module,
        "_caa_provider",
        lambda: StubCAA(images, {"https://caa.test/front.jpg": make_image(500, 500)}),
    )
    assert env.post("/api/files/1/artwork/search").status_code == 200

    res = env.get("/api/releases/1/artworks")
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["release_id"] == 1


def test_artwork_search_requires_identified_file(env: TestClient):
    assert env.post("/api/files/999/artwork/search").status_code == 404