"""Folder/filename naming (blueprint §17) + collision policy (TV2-025).

Templates come from settings (§17 template engine — never hard-code);
components are sanitized per §17 filename safety and collisions are
resolved without ever overwriting an existing file.
"""

import itertools
import os
import re

from backend.core.config import settings
from backend.organization.template import render_template

# Characters that are unsafe or reserved across common filesystems.
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

MAX_COMPONENT_LENGTH = 180  # keep components well under common 255-byte limits


def sanitize_component(value: str | None, fallback: str = "Unknown") -> str:
    """Sanitize one path component: reserved chars, control chars, trailing dots."""
    text = _UNSAFE_CHARS.sub("_", (value or "").strip())
    text = text.rstrip(" .")
    if not text or text.split(".")[0].upper() in _WINDOWS_RESERVED:
        return fallback
    if len(text) > MAX_COMPONENT_LENGTH:
        text = text[:MAX_COMPONENT_LENGTH].rstrip(" .")
    return text


def build_target_path(
    *,
    album_artist: str | None,
    year: int | None,
    album: str | None,
    track: int | None,
    title: str | None,
    disc: int | None,
    ext: str,
    artist: str | None = None,
    release_country: str | None = None,
    catalog_number: str | None = None,
) -> str:
    """Render the configured §17 layout; missing values degrade gracefully."""
    parts = {
        "artist": sanitize_component(artist),
        "album_artist": sanitize_component(album_artist),
        "album": sanitize_component(album),
        "year": year if year else "",
        "track": track,
        "title": sanitize_component(title, fallback="Unknown Title"),
        "disc": disc if disc else 1,
        "release_country": sanitize_component(release_country) if release_country else "",
        "catalog_number": sanitize_component(catalog_number) if catalog_number else "",
        "ext": sanitize_component(ext.lstrip(".").lower()),
    }
    template = (
        settings.ORGANIZATION_MULTI_DISC_TEMPLATE
        if (disc or 1) > 1
        else settings.ORGANIZATION_TEMPLATE
    )
    return render_template(template, parts)


def resolve_collision(
    target: str,
    sha256: str | None,
    existing_sha,
) -> tuple[str, str]:
    """§17 collision policy. Returns ``(path, status)``.

    Status:
        ``ok``         — target is free,
        ``duplicate``   — identical content already exists at target (never copy),
        ``suffixed``   — different content at target → never overwrite; new name.

    ``existing_sha(path)`` returns the SHA-256 of the file currently at
    ``path`` (None when unreadable); it is only consulted when the target
    already exists.
    """
    if not os.path.exists(target):
        return target, "ok"

    if sha256 and existing_sha(target) == sha256:
        return target, "duplicate"

    stem, ext = os.path.splitext(target)
    for counter in itertools.count(2):
        candidate = f"{stem} ({counter}){ext}"
        if not os.path.exists(candidate):
            return candidate, "suffixed"
        if sha256 and existing_sha(candidate) == sha256:
            return candidate, "duplicate"