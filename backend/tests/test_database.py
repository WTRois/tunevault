import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from backend.database.session import get_session
from backend.models.scan_job import ScanJob
from backend.models.song import Song


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_create_song(session: Session):
    song = Song(
        filename="track01.mp3",
        filepath="/music/album1/track01.mp3",
        sha256="abc123hash",
        title="Test Song",
        artist="Test Artist",
        album="Test Album",
        year=2024,
        duration=180.5,
        bitrate=320000,
        codec="mp3",
    )
    session.add(song)
    session.commit()
    session.refresh(song)

    assert song.id is not None
    assert song.title == "Test Song"
    assert song.has_cover is False

    # Retrieve from DB
    retrieved = session.exec(select(Song).where(Song.id == song.id)).first()
    assert retrieved is not None
    assert retrieved.filepath == "/music/album1/track01.mp3"


def test_song_filepath_unique_constraint(session: Session):
    song1 = Song(
        filename="track01.mp3",
        filepath="/music/same_path.mp3",
        sha256="hash1",
    )
    session.add(song1)
    session.commit()

    song2 = Song(
        filename="track01_duplicate.mp3",
        filepath="/music/same_path.mp3",
        sha256="hash2",
    )
    session.add(song2)
    with pytest.raises(IntegrityError):
        session.commit()


def test_create_scan_job(session: Session):
    job = ScanJob(
        directory_path="/music",
        status="pending",
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    assert job.id is not None
    assert job.status == "pending"
    assert job.scanned_files == 0

    # Update job
    job.status = "running"
    job.scanned_files = 10
    session.add(job)
    session.commit()

    updated = session.exec(select(ScanJob).where(ScanJob.id == job.id)).first()
    assert updated is not None
    assert updated.status == "running"
    assert updated.scanned_files == 10


def test_get_session_generator():
    generator = get_session()
    session = next(generator)
    assert isinstance(session, Session)
    # Close session
    try:
        next(generator)
    except StopIteration:
        pass
