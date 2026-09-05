"""Unit tests for the path sandbox (TV2-004, blueprint §27.1/§27.4)."""

from pathlib import Path

import pytest

from backend.core import paths
from backend.core.config import settings


@pytest.fixture(name="sandbox")
def sandbox_fixture(tmp_path, monkeypatch):
    """Point all configured roots at a temporary tree."""
    music = tmp_path / "music"
    music.mkdir()
    storage = tmp_path / "storage"
    storage.mkdir()
    covers = storage / "covers"
    covers.mkdir()
    downloads = storage / "downloads"
    downloads.mkdir()
    monkeypatch.setattr(settings, "MUSIC_DIR", str(music))
    monkeypatch.setattr(settings, "STORAGE_DIR", str(storage))
    monkeypatch.setattr(settings, "COVERS_DIR", str(covers))
    monkeypatch.setattr(settings, "DOWNLOADS_DIR", str(downloads))
    return music


def test_validate_read_accepts_path_inside_root(sandbox: Path):
    target = sandbox / "track.mp3"
    target.write_bytes(b"audio")
    assert paths.validate_read(target) == target.resolve()


def test_validate_read_rejects_missing_path(sandbox: Path):
    with pytest.raises(paths.PathNotFoundError):
        paths.validate_read(sandbox / "missing.mp3")


def test_validate_read_rejects_path_outside_roots(sandbox: Path, tmp_path):
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"x")
    with pytest.raises(paths.PathOutsideRootsError):
        paths.validate_read(outside)


def test_validate_read_rejects_dotdot_escape(sandbox: Path, tmp_path):
    escape = tmp_path / "escape.mp3"
    escape.write_bytes(b"x")
    with pytest.raises(paths.PathOutsideRootsError):
        paths.validate_read(sandbox / ".." / "escape.mp3")


def test_validate_read_rejects_symlink_escape(sandbox: Path, tmp_path):
    secret = tmp_path / "secret.mp3"
    secret.write_bytes(b"x")
    link = sandbox / "link.mp3"
    link.symlink_to(secret)
    with pytest.raises(paths.PathOutsideRootsError):
        paths.validate_read(link)


def test_validate_write_allows_new_file_inside_root(sandbox: Path):
    resolved = paths.validate_write(sandbox / "new.mp3")
    assert resolved == (sandbox / "new.mp3").resolve()


def test_validate_write_rejects_absolute_outside(sandbox: Path):
    with pytest.raises(paths.PathOutsideRootsError):
        paths.validate_write("/etc/passwd")


def test_validate_scan_directory_accepts_music_dir(sandbox: Path):
    assert paths.validate_scan_directory(sandbox) == sandbox.resolve()


def test_validate_scan_directory_accepts_subdirectory(sandbox: Path):
    sub = sandbox / "album"
    sub.mkdir()
    assert paths.validate_scan_directory(sub) == sub.resolve()


def test_validate_scan_directory_rejects_storage_dir(sandbox: Path):
    with pytest.raises(paths.PathOutsideRootsError):
        paths.validate_scan_directory(Path(settings.STORAGE_DIR))


def test_validate_scan_directory_rejects_file(sandbox: Path):
    target = sandbox / "track.mp3"
    target.write_bytes(b"audio")
    with pytest.raises(paths.PathNotFoundError):
        paths.validate_scan_directory(target)