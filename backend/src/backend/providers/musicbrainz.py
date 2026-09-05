"""MusicBrainz provider via httpx (blueprint §25, §6) — no musicbrainzngs.

WS/2 API: https://musicbrainz.org/ws/2/recording?query=...&fmt=json
"""

from typing import Any

from backend.core.config import settings
from backend.providers.base import MetadataQuery, ProviderMatch
from backend.providers.http import get_json, make_client

MUSICBRAINZ_BASE_URL = settings.MUSICBRAINZ_BASE_URL  # configurable via env (§38)


def _parse_recording(recording: dict[str, Any]) -> ProviderMatch:
    """Flatten one MB /ws/2 recording result into a ProviderMatch."""
    artist_credit = recording.get("artist-credit") or []
    artist = artist_credit[0].get("name") if artist_credit else None

    releases = recording.get("releases") or []
    release = releases[0] if releases else {}
    release_group = release.get("release-group") or {}

    length_ms = recording.get("length")
    return ProviderMatch(
        source="musicbrainz",
        title=recording.get("title"),
        artist=artist,
        release_title=release.get("title"),
        track_number=None,  # filled by release-track lookup (TV2-018)
        duration_ms=int(length_ms) if length_ms else None,
        recording_mbid=recording.get("id"),
        release_mbid=release.get("id"),
        release_group_mbid=release_group.get("id"),
        payload=recording,
    )


def _build_query(query: MetadataQuery) -> str:
    """Lucene-ish query string built from the strongest fields."""
    terms: list[str] = []
    if query.artist:
        terms.append(f'artist:"{query.artist}"')
    if query.title:
        terms.append(f'recording:"{query.title}"')
    if query.release_title and not terms:
        terms.append(f'release:"{query.release_title}"')
    if not terms and query.title:
        terms.append(f'"{query.title}"')
    return " AND ".join(terms)


class MusicBrainzProvider:
    """Searches MusicBrainz recordings; results feed the V2 scorer (TV2-016)."""

    name = "musicbrainz"

    def __init__(self, base_url: str | None = None, transport=None):
        self.base_url = (base_url or MUSICBRAINZ_BASE_URL).rstrip("/")
        self._transport = transport

    async def search(self, query: MetadataQuery) -> list[ProviderMatch]:
        if not (query.title or query.artist or query.release_title):
            raise ValueError("MusicBrainz search requires at least a title, artist, or release")
        client = make_client(transport=self._transport)
        try:
            data = await get_json(
                client,
                f"{self.base_url}/recording",
                params={
                    "query": _build_query(query),
                    "fmt": "json",
                    "limit": min(query.limit, 100),
                },
            )
        finally:
            await client.aclose()

        recordings = data.get("recordings", [])
        matches = []
        seen: set[str] = set()
        for recording in recordings:
            match = _parse_recording(recording)
            if match.recording_mbid in seen:
                continue
            seen.add(match.recording_mbid)
            matches.append(match)
            if len(matches) >= query.limit:
                break
        return matches

    async def lookup_recording(self, mbid: str) -> ProviderMatch | None:
        """Direct MBID lookup (evidence tier 1, §7)."""
        client = make_client(transport=self._transport)
        try:
            data = await get_json(
                client,
                f"{self.base_url}/recording/{mbid}",
                params={"fmt": "json", "inc": "releases+release-groups"},
            )
        finally:
            await client.aclose()
        return _parse_recording(data)

    async def lookup_release(self, mbid: str) -> dict[str, Any]:
        """Release lookup with media+recordings for release matching (TV2-018)."""
        client = make_client(transport=self._transport)
        try:
            return await get_json(
                client,
                f"{self.base_url}/release/{mbid}",
                params={"fmt": "json", "inc": "recordings+release-groups+media"},
            )
        finally:
            await client.aclose()