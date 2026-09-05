"""Artwork selector (blueprint §11 policy, TV2-022).

Policy (§11 "Prefer"): front cover, high resolution, correct aspect ratio,
trusted source. Candidates are validated first; selection then orders by:
    1. front covers before anything else,
    2. §11 quality score (descending),
    3. pixel resolution (descending) as a deterministic tie-break.
"""

from dataclasses import dataclass


@dataclass(slots=True)
class ArtworkCandidate:
    """A validated, scored artwork candidate ready for storage/selection."""

    image_bytes: bytes
    source: str
    url: str | None
    front: bool
    mime_type: str | None
    width: int
    height: int
    quality_score: float


def select_artwork(candidates: list[ArtworkCandidate]) -> ArtworkCandidate | None:
    """Best-per-policy §11; None when nothing survives validation."""
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda c: (c.front, c.quality_score, min(c.width, c.height)),
    )