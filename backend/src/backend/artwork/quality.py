"""Artwork quality score (blueprint §11, TV2-022 — weights verified verbatim).

Components and weights (§11):
    resolution            40%
    source trust          25%
    image validity        15%
    format                10%
    file size / quality   10%

Curves (documented policy, §11 gives weights only):
    resolution   — min side: 1000px+ = 1.0, 300px = 0.3, linear in between
    source trust — coverartarchive = 1.0, user = 0.9, existing_tag = 0.8,
                   youtube = 0.5, unknown = 0.3
    validity     — decodable image = 1.0 (dimension/aspect gates live in the
                   validator; invalid candidates never reach scoring)
    format       — png = 1.0, jpeg = 0.9, other = 0.6
    file size    — 200 KB+ = 1.0, 20 KB = 0.1, linear in between

The score never rewards upscaling (§11): resolution uses the real pixel
dimensions of the source image only.
"""

from backend.artwork.validator import image_dimensions

SOURCE_TRUST = {
    "coverartarchive": 1.0,
    "user": 0.9,
    "existing_tag": 0.8,
    "youtube": 0.5,
}

WEIGHT_RESOLUTION = 0.40
WEIGHT_SOURCE_TRUST = 0.25
WEIGHT_VALIDITY = 0.15
WEIGHT_FORMAT = 0.10
WEIGHT_FILE_SIZE = 0.10


def _resolution_score(min_side: int) -> float:
    if min_side >= 1000:
        return 1.0
    if min_side <= 300:
        return 0.3
    return 0.3 + 0.7 * (min_side - 300) / 700


def _format_score(mime_type: str | None) -> float:
    mime = (mime_type or "").lower()
    if "png" in mime:
        return 1.0
    if "jpeg" in mime or "jpg" in mime:
        return 0.9
    return 0.6


def _file_size_score(size_bytes: int) -> float:
    if size_bytes >= 200_000:
        return 1.0
    if size_bytes <= 20_000:
        return 0.1
    return 0.1 + 0.9 * (size_bytes - 20_000) / 180_000


def artwork_quality_score(
    image_bytes: bytes,
    source: str,
    mime_type: str | None = None,
) -> float:
    """Weighted §11 quality score in [0, 100]. Invalid images score 0."""
    size = image_dimensions(image_bytes)
    if size is None:
        return 0.0
    width, height = size
    min_side = min(width, height)

    resolution = _resolution_score(min_side)
    trust = SOURCE_TRUST.get(source, 0.3)
    validity = 1.0
    fmt = _format_score(mime_type)
    weight = _file_size_score(len(image_bytes))

    score = (
        WEIGHT_RESOLUTION * resolution
        + WEIGHT_SOURCE_TRUST * trust
        + WEIGHT_VALIDITY * validity
        + WEIGHT_FORMAT * fmt
        + WEIGHT_FILE_SIZE * weight
    )
    return round(score * 100, 2)