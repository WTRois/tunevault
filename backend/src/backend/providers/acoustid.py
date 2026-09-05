"""AcoustID provider (blueprint §5.9, §7 evidence tier 3).

Submits a Chromaprint fingerprint to AcoustID and maps MusicBrainz recording
IDs. Without an API key the provider degrades gracefully: :meth:`search`
returns an empty list, never an error (identification continues via tags/MusicBrainz).
"""

from typing import Any

from backend.core.config import settings
from backend.core.versions import FINGERPRINT_VERSION
from backend.providers.base import MetadataQuery, ProviderMatch
from backend.providers.http import get_json, make_client

ACOUSTID_BASE_URL = "https://api.acoustid.org/v2"


class AcoustIDProvider:
    """Looks up fingerprints via api.acoustid.org."""

    name = "acoustid"

    def __init__(self, base_url: str = ACOUSTID_BASE_URL, transport=None, api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self._transport = transport
        self.api_key = api_key if api_key is not None else settings.ACOUSTID_API_KEY

    def enabled(self) -> bool:
        return bool(self.api_key)

    async def search(self, query: MetadataQuery) -> list[ProviderMatch]:
        """Fingerprint lookup — requires query.fingerprint; no-op when disabled."""
        if not self.enabled() or not query.fingerprint:
            return []

        client = make_client(transport=self._transport)
        try:
            data = await get_json(
                client,
                f"{self.base_url}/lookup",
                params={
                    "format": "json",
                    "client": self.api_key,
                    "fingerprint": query.fingerprint,
                    "duration": max(1, (query.duration_ms or 0) // 1000),
                    "meta": "recordings+releasegroups",
                },
            )
        finally:
            await client.aclose()

        return self._parse_response(data)

    def _parse_response(self, data: dict[str, Any]) -> list[ProviderMatch]:
        results = data.get("results") or []
        if not results:
            return []

        recordings = results[0].get("recordings") or []
        matches: list[ProviderMatch] = []
        seen: set[str] = set()
        for recording in recordings:
            mbid = recording.get("id")
            if not mbid or mbid in seen:
                continue
            seen.add(mbid)

            artists = recording.get("artists") or []
            artist = artists[0].get("name") if artists else None

            release_groups = recording.get("releasegroups") or []
            release_group = release_groups[0] if release_groups else {}

            matches.append(
                ProviderMatch(
                    source="acoustid",
                    title=recording.get("title"),
                    artist=artist,
                    release_title=release_group.get("title"),
                    duration_ms=query_duration_from_recording(recording),
                    recording_mbid=mbid,
                    release_group_mbid=release_group.get("id"),
                    payload={"fingerprint_version": FINGERPRINT_VERSION, **recording},
                )
            )
            if len(matches) >= 5:
                break
        return matches


def query_duration_from_recording(recording: dict[str, Any]) -> int | None:
    duration = recording.get("duration")
    return int(duration) * 1000 if duration else None