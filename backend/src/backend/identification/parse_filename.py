"""Filename parser: ``Artist - Title [Quality]`` (blueprint §8.2 example).

Extracts (artist, title, track, noise) tokens from a filename without
touching the file itself.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from backend.identification.normalize import normalize_text

_TRACK_RE = re.compile(r"(?:^|\D)(\d{1,3})(?=\s*[-_.]\s*\D|\s*[-_.]\s*$)", re.ASCII)
_BRACKETS_RE = re.compile(r"[\[\({]([^\]\)}]*)[\]\)}]")


@dataclass(frozen=True, slots=True)
class ParsedFilename:
    artist: str | None
    title: str | None
    track_number: int | None
    noise: list[str]


def parse_filename(filename: str) -> ParsedFilename:
    """Parse ``Artist - Title [noise]`` / ``01 - Title`` / ``Artist - 01 - Title``.

    Returns normalized tokens; anything unrecognized lands in ``noise``.
    """
    stem = Path(filename).stem
    if not stem:
        return ParsedFilename(artist=None, title=None, track_number=None, noise=[])

    # Collect bracketed content as noise (quality tags etc).
    noise: list[str] = []
    noise.extend(m.strip().lower() for m in _BRACKETS_RE.findall(stem))
    stem = _BRACKETS_RE.sub(" ", stem)

    # Leading track number: "01 - Title" / "01. Title" / "01 Title"
    track_number: int | None = None
    leading = re.match(r"^\s*(\d{1,3})\s*[-_. ]\s*(.+)$", stem)
    body = stem
    if leading:
        candidate = int(leading.group(1))
        if 0 < candidate < 100:
            track_number = candidate
            body = leading.group(2)

    # Split on the primary " - " separator: "Artist - Title"
    artist: str | None = None
    title: str | None = None
    parts = [p.strip() for p in re.split(r"\s+-\s+|\s+–\s+", body) if p.strip()]
    if len(parts) >= 2:
        artist = normalize_text(parts[0]) or None
        title = normalize_text(parts[-1]) or None
        # Middle numeric chunk can still be a track number: "Artist - 01 - Title"
        for part in parts[1:-1]:
            if part.isdigit() and track_number is None:
                track_number = int(part)
            else:
                noise.append(normalize_text(part))
    elif parts:
        title = normalize_text(parts[0]) or None

    # Trailing "(Official Video)" etc. handled by normalizer noise patterns.
    return ParsedFilename(artist=artist, title=title, track_number=track_number, noise=noise)