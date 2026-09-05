"""Candidate generation (blueprint §8.1) — bridges files/evidence to providers.

The file's own state (tags, MBID, filename tokens, duration) builds one
:class:`ScoredEvidence`; providers are queried in §7 evidence order and their
matches are collected for scoring (scoring.py).
"""

from dataclasses import dataclass

from sqlmodel import Session

from backend.identification.parse_filename import parse_filename
from backend.identification.scoring import ScoredCandidate, ScoredEvidence, score_candidates
from backend.models import File
from backend.providers.acoustid import AcoustIDProvider
from backend.providers.base import MetadataQuery, ProviderMatch
from backend.providers.cache import cached_search
from backend.providers.musicbrainz import MusicBrainzProvider


@dataclass(slots=True)
class IdentificationEvidence:
    """Everything known about a file before asking providers (§7)."""

    file_id: int
    evidence: ScoredEvidence
    fingerprint: str | None = None  # raw Chromaprint string, if computed


def build_evidence(
    file: File,
    tags: dict | None = None,
    fingerprint: str | None = None,
) -> IdentificationEvidence:
    """Assemble evidence: explicit tags first (§7 tier 1/5), filename parse as fallback."""
    tags = tags or {}
    parsed = parse_filename(file.filename)

    evidence = ScoredEvidence(
        artist=tags.get("artist") or parsed.artist,
        title=tags.get("title") or parsed.title,
        release_title=tags.get("album"),
        duration_ms=file.duration_ms,
        track_number=tags.get("track_number", parsed.track_number),
        disc_number=tags.get("disc_number"),
        recording_mbid=tags.get("musicbrainz_recording_id"),
        fingerprint_matched=False,
    )
    return IdentificationEvidence(
        file_id=file.id or 0,
        evidence=evidence,
        fingerprint=fingerprint,
    )


async def generate_candidates(
    session: Session,
    file: File,
    tags: dict | None = None,
    *,
    musicbrainz: MusicBrainzProvider | None = None,
    acoustid: AcoustIDProvider | None = None,
    fingerprint: str | None = None,
) -> tuple[IdentificationEvidence, list[ProviderMatch]]:
    """Run the §7 evidence order and return (evidence, unique candidates).

    Tags (existing evidence) drive the MusicBrainz search; AcoustID is
    consulted when a fingerprint is available. Both flow through the §26
    cache; provider failures degrade gracefully.
    """
    identification = build_evidence(file, tags=tags, fingerprint=fingerprint)
    evidence = identification.evidence

    candidates: list[ProviderMatch] = []
    seen: set[str] = set()

    mb = musicbrainz or MusicBrainzProvider()
    if evidence.title or evidence.artist:
        query = MetadataQuery(
            title=evidence.title,
            artist=evidence.artist,
            release_title=evidence.release_title,
            duration_ms=evidence.duration_ms,
            limit=5,
        )
        try:
            mb_matches = await cached_search(mb, query, session)
        except Exception:  # noqa: BLE001
            mb_matches = []
        for match in mb_matches:
            key = match.recording_mbid or f"mb:{match.title}:{match.artist}"
            if key not in seen:
                seen.add(key)
                candidates.append(match)

    aid = acoustid or AcoustIDProvider()
    if aid.enabled() and fingerprint:
        identification.evidence.fingerprint_matched = True
        try:
            aid_matches = await cached_search(
                aid,
                MetadataQuery(fingerprint=fingerprint, duration_ms=evidence.duration_ms),
                session,
            )
        except Exception:  # noqa: BLE001
            aid_matches = []
        for match in aid_matches:
            key = match.recording_mbid or f"aid:{match.title}"
            if key not in seen:
                seen.add(key)
                candidates.append(match)

    return identification, candidates


def rank_candidates(
    identification: IdentificationEvidence, candidates: list[ProviderMatch]
) -> list[tuple]:
    """Score candidates against the evidence; best first."""
    return score_candidates(identification.evidence, candidates)


__all__ = [
    "IdentificationEvidence",
    "ScoredCandidate",
    "build_evidence",
    "generate_candidates",
    "rank_candidates",
]