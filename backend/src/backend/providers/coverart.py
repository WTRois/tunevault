"""Cover Art Archive provider via httpx (blueprint §11, TV2-021).

CAA endpoints:
    https://coverartarchive.org/release/{mbid}/json   → list of images
    direct image URLs (…/mbid-2500.jpg)               → image bytes
"""

import hashlib
from dataclasses import asdict, dataclass
from typing import Any

from backend.providers.http import get_json, make_client

COVERART_BASE_URL = "https://coverartarchive.org"


@dataclass(frozen=True, slots=True)
class CoverArtImage:
    """One CAA candidate image for a release."""

    url: str
    front: bool = False
    type: str | None = None
    mime_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CoverArtProvider:
    """Fetches release artwork candidates from the Cover Art Archive (§11)."""

    name = "coverartarchive"

    def __init__(self, base_url: str = COVERART_BASE_URL, transport=None):
        self.base_url = base_url
        self._transport = transport

    async def release_covers(self, release_mbid: str) -> list[CoverArtImage]:
        """List artwork candidates for a MusicBrainz release MBID."""
        client = make_client(transport=self._transport)
        try:
            data = await get_json(client, f"{self.base_url}/release/{release_mbid}/json")
        finally:
            await client.aclose()
        if not isinstance(data, list):
            return []
        images: list[CoverArtImage] = []
        for item in data:
            url = item.get("url")
            if not url:
                continue
            mime = item.get("mimetype") or (url.rsplit(".", 1)[-1] if "." in url else None)
            images.append(
                CoverArtImage(
                    url=url,
                    front=bool(item.get("front")),
                    type=item.get("type"),
                    mime_type=mime,
                )
            )
        return images

    async def download(self, url: str) -> bytes:
        """Download raw image bytes from a CAA URL."""
        client = make_client(transport=self._transport)
        try:
            response = await client.get(url)
            response.raise_for_status()
            return response.content
        finally:
            await client.aclose()


def artwork_cache_path(image_bytes: bytes, mime_type: str | None) -> tuple[str, str, str]:
    """Content-addressed storage path per the V1 covers pattern.

    Returns ``(directory, filename, sha256)``; the directory comes from
    settings so callers can create/copy into the shared covers cache.
    """
    from backend.core.config import settings

    digest = hashlib.sha256(image_bytes).hexdigest()
    extension = "png" if (mime_type or "").endswith("png") else "jpg"
    return settings.resolved_covers_dir, f"{digest}.{extension}", digest