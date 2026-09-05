"""Artwork validator (blueprint §11): dimension and aspect-ratio gates.

Policy (documented per TV2-022):
    - image must decode,
    - min side >= MIN_DIMENSION px (300 — below that, covers look broken in UI),
    - aspect ratio within [MIN_ASPECT, MAX_ASPECT] (front covers are near-square;
      0.5–2.0 tolerates booklet scans without accepting banners).
"""

import io

from PIL import Image

MIN_DIMENSION = 300
MIN_ASPECT = 0.5
MAX_ASPECT = 2.0


def image_dimensions(image_bytes: bytes) -> tuple[int, int] | None:
    """Decode header only — returns (width, height) or None for invalid data."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            return image.size
    except Exception:  # noqa: BLE001
        return None


def validate_artwork(image_bytes: bytes) -> tuple[bool, tuple[int, int] | None]:
    """Return (is_valid, dimensions). Never raises on invalid data."""
    size = image_dimensions(image_bytes)
    if size is None:
        return False, None
    width, height = size
    if min(width, height) < MIN_DIMENSION:
        return False, size
    if not MIN_ASPECT <= (width / max(height, 1)) <= MAX_ASPECT:
        return False, size
    return True, size