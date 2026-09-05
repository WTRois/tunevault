"""MusicBrainz provider tests — fully mocked HTTP (TV2-013, blueprint §35)."""

import asyncio

import httpx
import pytest

from backend.providers.base import MetadataQuery
from backend.providers.musicbrainz import MusicBrainzProvider, _build_query

RECORDING_SEARCH_RESPONSE = {
    "recordings": [
        {
            "id": "recording-mbid-1",
            "title": "Test Song",
            "length": 180000,
            "artist-credit": [{"name": "Test Artist"}],
            "releases": [
                {
                    "id": "release-mbid-1",
                    "title": "Test Album",
                    "release-group": {"id": "rg-mbid-1"},
                }
            ],
        },
        {
            "id": "recording-mbid-2",
            "title": "Test Song (Live)",
            "length": 200000,
            "artist-credit": [{"name": "Test Artist"}],
        },
    ],
    "count": 2,
}


def _client_for(responses: dict[str, object]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        for suffix, payload in responses.items():
            if path.endswith(suffix):
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={"error": f"unexpected path {path}"})

    return httpx.MockTransport(handler)


def test_build_query_prefers_artist_and_title():
    query = MetadataQuery(title="Song", artist="Artist")
    assert _build_query(query) == 'artist:"Artist" AND recording:"Song"'


def test_build_query_falls_back_to_title():
    query = MetadataQuery(title="Only Title")
    assert '"Only Title"' in _build_query(query)


def test_search_parses_and_limits():
    transport = _client_for({"recording": RECORDING_SEARCH_RESPONSE})
    provider = MusicBrainzProvider(transport=transport)

    matches = asyncio.run(provider.search(MetadataQuery(title="Test Song", artist="Test Artist", limit=1)))

    assert len(matches) == 1
    match = matches[0]
    assert match.source == "musicbrainz"
    assert match.title == "Test Song"
    assert match.artist == "Test Artist"
    assert match.duration_ms == 180000
    assert match.recording_mbid == "recording-mbid-1"
    assert match.release_mbid == "release-mbid-1"
    assert match.release_group_mbid == "rg-mbid-1"
    assert match.release_title == "Test Album"


def test_search_deduplicates_same_mbid():
    response = {
        "recordings": [
            {
                "id": "same-mbid",
                "title": "Song",
                "artist-credit": [{"name": "A"}],
            },
            {
                "id": "same-mbid",
                "title": "Song (Alt Release)",
                "artist-credit": [{"name": "A"}],
            },
        ]
    }
    transport = _client_for({"recording": response})
    provider = MusicBrainzProvider(transport=transport)

    matches = asyncio.run(provider.search(MetadataQuery(title="Song", limit=5)))
    assert len(matches) == 1
    assert matches[0].recording_mbid == "same-mbid"


def test_lookup_recording():
    recording = {
        "id": "recording-mbid-1",
        "title": "Test Song",
        "length": 180000,
        "artist-credit": [{"name": "Test Artist"}],
        "releases": [
            {
                "id": "release-mbid-1",
                "title": "Test Album",
                "release-group": {"id": "rg-mbid-1"},
            }
        ],
    }
    transport = _client_for({"recording/recording-mbid-1": recording})
    provider = MusicBrainzProvider(transport=transport)

    match = asyncio.run(provider.lookup_recording("recording-mbid-1"))
    assert match is not None
    assert match.recording_mbid == "recording-mbid-1"
    assert match.title == "Test Song"


def test_search_empty_results():
    transport = _client_for({"recording": {"recordings": []}})
    provider = MusicBrainzProvider(transport=transport)

    matches = asyncio.run(provider.search(MetadataQuery(title="Nope")))
    assert matches == []


def test_search_requires_terms():
    provider = MusicBrainzProvider(transport=_client_for({}))
    with pytest.raises(ValueError):
        asyncio.run(provider.search(MetadataQuery()))