import re
from typing import Any

import yt_dlp

from backend.models.song import Song
from backend.schemas.song import YouTubeMetadataCandidate

_VERSION_WORDS = {"live", "cover", "remix", "karaoke", "slowed", "nightcore", "acoustic"}


def _normalize(value: str | None) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (value or "").lower()).replace("official video", "").strip()


def _score(song: Song, info: dict[str, Any]) -> float:
    query_title = _normalize(song.title)
    query_artist = _normalize(song.artist)
    candidate_title = _normalize(info.get("track") or info.get("title"))
    candidate_artist = _normalize(info.get("artist") or info.get("uploader") or info.get("channel"))
    score = 0.0
    if query_title and query_title in candidate_title:
        score += 0.55
    if query_artist and query_artist in candidate_artist:
        score += 0.35
    if song.duration and info.get("duration"):
        difference = abs(song.duration - float(info["duration"]))
        score += max(0.0, 0.1 - min(difference, 10) / 100)
    candidate_text = f"{candidate_title} {candidate_artist}"
    if any(word in candidate_text for word in _VERSION_WORDS):
        score -= 0.15
    return max(0.0, min(1.0, score))


def search_candidates(song: Song, limit: int = 5) -> tuple[str, list[YouTubeMetadataCandidate]]:
    query = " ".join(part for part in (song.artist, song.title, song.album) if part)
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "playlistend": limit,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            result = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    except Exception as err:
        raise RuntimeError("YouTube search is unavailable") from err

    entries = result.get("entries", []) if result else []
    candidates: list[YouTubeMetadataCandidate] = []
    for info in entries:
        video_id = info.get("id")
        if not video_id or len(video_id) != 11:
            continue
        duration = info.get("duration")
        if song.duration and duration and abs(song.duration - float(duration)) > 10:
            continue
        title = info.get("track") or info.get("title") or "Unknown title"
        artist = info.get("artist") or info.get("uploader") or info.get("channel")
        candidates.append(
            YouTubeMetadataCandidate(
                video_id=video_id,
                video_url=f"https://www.youtube.com/watch?v={video_id}",
                title=title,
                artist=artist,
                album=info.get("album"),
                year=int(info["upload_date"][:4]) if info.get("upload_date") else None,
                duration=float(duration) if duration else None,
                thumbnail_url=info.get("thumbnail"),
                channel=info.get("channel") or info.get("uploader"),
                match_score=_score(song, info),
            )
        )
    candidates.sort(key=lambda item: item.match_score, reverse=True)
    return query, candidates[:limit]
