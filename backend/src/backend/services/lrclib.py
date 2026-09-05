from typing import Any

import httpx

from backend.models.song import Song
from backend.schemas.song import LyricsCandidate

LRCLIB_BASE_URL = "https://lrclib.net/api"


def _candidate(data: dict[str, Any]) -> LyricsCandidate:
    return LyricsCandidate(
        lrclib_id=data.get("id"),
        track_name=data.get("trackName") or "",
        artist_name=data.get("artistName") or "",
        album_name=data.get("albumName"),
        duration=data.get("duration"),
        plain_lyrics=data.get("plainLyrics"),
        synced_lyrics=data.get("syncedLyrics"),
        instrumental=bool(data.get("instrumental", False)),
    )


def _request(path: str, params: dict[str, str | int]) -> httpx.Response:
    try:
        with httpx.Client(base_url=LRCLIB_BASE_URL, timeout=10.0) as client:
            response = client.get(path, params=params)
            response.raise_for_status()
            return response
    except httpx.HTTPStatusError:
        raise
    except httpx.HTTPError as err:
        raise RuntimeError("LRCLIB is unavailable") from err


def lookup_exact(song: Song) -> LyricsCandidate | None:
    params: dict[str, str | int] = {
        "track_name": song.title or "",
        "artist_name": song.artist or "",
        "duration": round(song.duration or 0),
    }
    if song.album:
        params["album_name"] = song.album

    try:
        response = _request("/get", params)
    except httpx.HTTPStatusError as err:
        if err.response.status_code == 404:
            return None
        raise RuntimeError("LRCLIB is unavailable") from err

    result = _candidate(response.json())
    return result if result.plain_lyrics or result.synced_lyrics else None


def search_candidates(song: Song, limit: int = 5) -> list[LyricsCandidate]:
    query = " ".join(part for part in (song.artist, song.title) if part)
    try:
        response = _request("/search", {"q": query})
    except httpx.HTTPStatusError as err:
        raise RuntimeError("LRCLIB is unavailable") from err

    candidates: list[LyricsCandidate] = []
    for item in response.json():
        candidate = _candidate(item)
        if candidate.instrumental or not (candidate.plain_lyrics or candidate.synced_lyrics):
            continue
        if song.duration and candidate.duration and abs(song.duration - candidate.duration) > 5:
            continue
        candidates.append(candidate)
        if len(candidates) == limit:
            break
    return candidates
