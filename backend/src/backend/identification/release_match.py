"""Release matching (blueprint §10) — recording → release/release_track.

After a recording match is accepted, resolve which concrete release the
file belongs to. §10 resolution order + user release preferences (config);
results land in release_groups / releases / release_tracks / file_releases.
"""

from decimal import Decimal
from typing import Any

from loguru import logger
from sqlmodel import Session, select

from backend.core.config import settings
from backend.core.time import now_utc
from backend.identification.constants import DURATION_TOLERANCE_WEAK
from backend.models import AppSetting, File, FileRelease, Release, ReleaseGroup, ReleaseTrack
from backend.providers.base import ProviderMatch

# §10 user preferences served from simple config (task TV2-018).
RELEASE_PREFERENCES = (
    "prefer_original",
    "prefer_remaster",
    "prefer_high_res",
    "prefer_specific_country",
    "prefer_specific_label",
)

HIGH_RES_FORMATS = ("SACD", "DVD", "Blu-ray", "Hybrid")
MAX_RELEASE_LOOKUPS = 3


# app_settings keys → preference dict fields (§10). DB values override config.
_PREFERENCE_SETTING_KEYS = {
    "release_preference": "preference",
    "release_preference_country": "country",
    "release_preference_label": "label",
}


def release_preferences(session: Session | None = None) -> dict[str, str]:
    """Effective user release preference (§10): app_settings overrides → config."""
    preference = (
        settings.RELEASE_PREFERENCE
        if settings.RELEASE_PREFERENCE in RELEASE_PREFERENCES
        else "prefer_original"
    )
    prefs = {
        "preference": preference,
        "country": settings.RELEASE_PREFERENCE_COUNTRY,
        "label": settings.RELEASE_PREFERENCE_LABEL,
    }
    if session is not None:
        keys = tuple(_PREFERENCE_SETTING_KEYS)
        for row in session.exec(
            select(AppSetting).where(AppSetting.key.in_(keys))  # pyright: ignore[reportArgumentType]
        ).all():
            field = _PREFERENCE_SETTING_KEYS.get(row.key)
            if field and row.value:
                prefs[field] = row.value
    if prefs["preference"] not in RELEASE_PREFERENCES:
        prefs["preference"] = "prefer_original"
    return prefs


def _release_year(release: dict[str, Any]) -> int | None:
    date = release.get("date") or ""
    year = date[:4]
    return int(year) if year.isdigit() else None


def _release_labels(release: dict[str, Any]) -> set[str]:
    return {
        info.get("label", {}).get("name")
        for info in (release.get("label-info") or [])
        if info.get("label")
    }


def _score_release(
    release: dict[str, Any],
    existing_album: str | None,
    prefs: dict[str, str],
) -> int:
    """§10 ranking score: existing album match first, then preference rules.

    Higher is better. Barcode/catalog lookups (§10 #2/#3) need per-release
    detail and are applied via ``lookup_release`` after ranking.
    """
    score = 0
    group = release.get("release-group") or {}
    secondary = set(group.get("secondary-types") or [])
    is_compilation = "Compilation" in secondary
    year = _release_year(release)
    media = release.get("media") or [{}]
    fmt = media[0].get("format") or ""

    # §10 #4: existing album + artist — strongest local evidence.
    if existing_album and (
        release.get("title") == existing_album or group.get("title") == existing_album
    ):
        score += 100

    preference = prefs["preference"]
    if preference == "prefer_original":
        score -= (year or 9999) // 10
        if is_compilation:
            score -= 500
        if group.get("primary-type") == "Album":
            score += 50
    elif preference == "prefer_remaster":
        disambiguation = release.get("disambiguation") or ""
        if "Remaster" in secondary or "remaster" in disambiguation.lower():
            score += 500
    elif preference == "prefer_high_res":
        if any(f in fmt for f in HIGH_RES_FORMATS):
            score += 500
    elif preference == "prefer_specific_country" and prefs["country"]:
        if release.get("country") == prefs["country"]:
            score += 500
    elif preference == "prefer_specific_label" and prefs["label"]:
        if prefs["label"] in _release_labels(release):
            score += 500

    return score


def rank_releases(
    releases: list[dict[str, Any]],
    existing_album: str | None = None,
    prefs: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Order candidate releases per §10 + preferences (best first, stable)."""
    prefs = prefs or release_preferences()
    ranked = sorted(
        releases,
        key=lambda r: (
            -_score_release(r, existing_album, prefs),
            _release_year(r) or 9999,
            r.get("id") or "",
        ),
    )
    return ranked


def _find_track(
    details: dict[str, Any], recording_mbid: str | None
) -> dict[str, Any] | None:
    """Locate the recording inside a release tracklist (media → track-list)."""
    if not recording_mbid:
        return None
    for media in details.get("media") or []:
        for track in media.get("track-list") or []:
            if (track.get("recording") or {}).get("id") == recording_mbid:
                return {
                    "disc_number": media.get("position", 1),
                    "track_number": track.get("position") or 1,
                    "title": track.get("title"),
                    "length_ms": track.get("length"),
                }
    return None


def _duration_matches(file_duration_ms: int | None, length_ms: int | None) -> bool:
    """§10 #9 duration consistency — within the large duration band (§8.3)."""
    if not file_duration_ms or not length_ms:
        return True  # missing data never blocks a tracklist match
    return abs(file_duration_ms - length_ms) <= DURATION_TOLERANCE_WEAK * 1000


def _upsert_release_group(session: Session, group: dict[str, Any]) -> ReleaseGroup:
    mbid = group.get("id")
    row = (
        session.exec(select(ReleaseGroup).where(ReleaseGroup.musicbrainz_release_group_id == mbid)).first()
        if mbid
        else None
    )
    if row is None:
        row = ReleaseGroup(
            musicbrainz_release_group_id=mbid,
            title=group.get("title") or "",
            primary_type=group.get("primary-type"),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def _upsert_release(session: Session, group_row: ReleaseGroup, release: dict[str, Any]) -> Release:
    mbid = release.get("id")
    row = (
        session.exec(select(Release).where(Release.musicbrainz_release_id == mbid)).first()
        if mbid
        else None
    )
    if row is None:
        row = Release(
            release_group_id=group_row.id or 0,
            musicbrainz_release_id=mbid,
            title=release.get("title") or "",
            date=release.get("date"),
            country=release.get("country"),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def _upsert_release_track(
    session: Session,
    release_row: Release,
    recording_row_id: int,
    track: dict[str, Any],
) -> ReleaseTrack:
    row = session.exec(
        select(ReleaseTrack).where(
            ReleaseTrack.release_id == release_row.id,
            ReleaseTrack.recording_id == recording_row_id,
        )
    ).first()
    if row is None:
        row = ReleaseTrack(
            release_id=release_row.id or 0,
            recording_id=recording_row_id,
            disc_number=track.get("disc_number", 1),
            track_number=track.get("track_number", 1),
            position=track.get("track_number", 1),
            title=track.get("title"),
            length_ms=track.get("length_ms"),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def _link_file_release(
    session: Session,
    file_id: int,
    release_row: Release,
    track_row: ReleaseTrack,
    confidence: Decimal,
    source: str,
) -> None:
    link = session.exec(select(FileRelease).where(FileRelease.file_id == file_id)).first()
    if link is None:
        session.add(
            FileRelease(
                file_id=file_id,
                release_id=release_row.id or 0,
                release_track_id=track_row.id or 0,
                confidence=confidence,
                source=source,
                matched_at=now_utc(),
            )
        )
    else:
        link.release_id = release_row.id or 0
        link.release_track_id = track_row.id or 0
        link.confidence = confidence
        link.source = source
        link.matched_at = now_utc()
        session.add(link)
    session.commit()


async def match_release(
    session: Session,
    file: File,
    match: ProviderMatch,
    provider: Any = None,
    recording_row_id: int | None = None,
    source: str = "musicbrainz",
    confidence: Decimal = Decimal("1.0"),
) -> dict | None:
    """Resolve + persist release-level identity for an accepted match (§10).

    Ranks the candidate releases carried by the provider payload, fetches the
    best tracklists (bounded lookups) and links the file to the release whose
    tracklist contains the matched recording. Returns a summary dict or None.
    """
    payload = match.payload or {}
    releases = list(payload.get("releases") or [])
    explicit_mbid = match.release_mbid
    if explicit_mbid and not any(r.get("id") == explicit_mbid for r in releases):
        releases.insert(
            0,
            {
                "id": explicit_mbid,
                "title": match.release_title,
                "release-group": {"id": match.release_group_mbid},
            },
        )
    if not releases:
        return None

    existing_album = getattr(match, "album", None)
    ranked = rank_releases(releases, existing_album=existing_album, prefs=release_preferences(session))

    file_duration_ms = file.duration_ms
    for release in ranked[:MAX_RELEASE_LOOKUPS]:
        details = None
        if provider is not None and release.get("id"):
            try:
                details = await provider.lookup_release(release["id"])
            except Exception as err:  # noqa: BLE001
                logger.warning(f"Release lookup {release.get('id')} failed: {err}")
                details = None
        if details is None:
            continue

        track = _find_track(details, match.recording_mbid)
        if track is None or not _duration_matches(file_duration_ms, track.get("length_ms")):
            continue

        if recording_row_id is None:
            continue  # no Recording row to link the release track to

        group_row = _upsert_release_group(session, details.get("release-group") or release.get("release-group") or {})
        release_row = _upsert_release(session, group_row, details)
        track_row = _upsert_release_track(session, release_row, recording_row_id, track)
        _link_file_release(session, file.id or 0, release_row, track_row, confidence, source)

        return {
            "release_id": release_row.id,
            "release_mbid": release_row.musicbrainz_release_id,
            "release_title": release_row.title,
            "track_number": track_row.track_number,
            "disc_number": track_row.disc_number,
            "matched_at": now_utc(),
        }
    return None