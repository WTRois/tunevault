"""Filesystem sandbox: every FS access must stay inside configured roots.

Implements blueprint §27.1/§27.4 — allowed roots are MUSIC_DIR, STORAGE_DIR,
COVERS_DIR and DOWNLOADS_DIR; symlink traversal and ``..`` escapes are rejected
because paths are resolved before the prefix check.
"""

from pathlib import Path

from backend.core.config import settings


class PathPolicyError(ValueError):
    """Base error for sandbox violations."""


class PathNotFoundError(PathPolicyError):
    """Path does not exist (mapped to HTTP 400/404 by callers)."""


class PathOutsideRootsError(PathPolicyError):
    """Resolved path is outside all allowed roots (mapped to HTTP 403)."""


def allowed_roots() -> tuple[Path, ...]:
    """Configured roots (§27.1). COVERS_DIR/DOWNLOADS_DIR may nest under STORAGE_DIR."""
    return tuple(
        Path(getattr(settings, name)).expanduser().resolve()
        for name in ("MUSIC_DIR", "STORAGE_DIR", "COVERS_DIR", "DOWNLOADS_DIR")
    )


def _inside_roots(resolved: Path) -> bool:
    return any(resolved == root or root in resolved.parents for root in allowed_roots())


def validate_read(path: str | Path) -> Path:
    """Require an existing path inside an allowed root (symlinks are resolved)."""
    try:
        resolved = Path(path).expanduser().resolve(strict=True)
    except OSError as err:
        raise PathNotFoundError(f"Path does not exist or is inaccessible: {path}") from err
    if not _inside_roots(resolved):
        raise PathOutsideRootsError(f"Path is outside the allowed roots: {path}")
    return resolved


def validate_write(path: str | Path) -> Path:
    """Require the path to resolve inside an allowed root (may not exist yet)."""
    resolved = Path(path).expanduser().resolve(strict=False)
    if not _inside_roots(resolved):
        raise PathOutsideRootsError(f"Path is outside the allowed roots: {path}")
    return resolved


def validate_scan_directory(path: str | Path) -> Path:
    """Scan input must be an existing directory inside MUSIC_DIR (§27.1)."""
    resolved = validate_read(path)
    music_root = Path(settings.MUSIC_DIR).expanduser().resolve()
    if resolved != music_root and music_root not in resolved.parents:
        raise PathOutsideRootsError(f"Scan directory must be inside MUSIC_DIR: {music_root}")
    if not resolved.is_dir():
        raise PathNotFoundError(f"Scan path is not a directory: {path}")
    return resolved