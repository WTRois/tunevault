"""Candidate scoring (blueprint §8.3–§8.5), deterministic and versioned.

Weights/thresholds/penalties live in :mod:`backend.identification.constants`
(verbatim from the blueprint). Fuzzy similarity uses stdlib ``difflib``.
"""

from dataclasses import dataclass
from difflib import SequenceMatcher

from backend.identification.constants import (
    AUTO_APPLY,
    AUTO_APPLY_THRESHOLD,
    AUTO_SUGGEST_REVIEW,
    AUTO_SUGGEST_REVIEW_THRESHOLD,
    DURATION_TOLERANCE_HIGH,
    DURATION_TOLERANCE_MEDIUM,
    DURATION_TOLERANCE_WEAK,
    NO_MATCH,
    PENALTY_DIFFERENT_ARTIST_STRONG_TITLE,
    PENALTY_DISC_CONTRADICTION,
    PENALTY_DURATION_CONTRADICTION,
    PENALTY_TRACK_CONTRADICTION,
    REVIEW_REQUIRED,
    REVIEW_REQUIRED_THRESHOLD,
    SCORING_VERSION,
    WEIGHT_ALBUM_SIMILARITY,
    WEIGHT_ARTIST_SIMILARITY,
    WEIGHT_BARCODE_ISRC,
    WEIGHT_DURATION_SIMILARITY,
    WEIGHT_FINGERPRINT,
    WEIGHT_MBID_EXACT,
    WEIGHT_TITLE_SIMILARITY,
    WEIGHT_TRACK_DISC_CONSISTENCY,
)
from backend.identification.normalize import normalize_text

STRONG_TITLE_SIMILARITY = 0.95
DIFFERENT_ARTIST_SIMILARITY = 0.60


def similarity(a: str | None, b: str | None) -> float:
    """Normalized similarity between two raw strings (0.0–1.0)."""
    left = normalize_text(a)
    right = normalize_text(b)
    if not left and not right:
        return 0.0
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


@dataclass(slots=True)
class ScoredEvidence:
    """Inputs the scorer compares a candidate against (all optional)."""

    artist: str | None = None
    title: str | None = None
    release_title: str | None = None
    duration_ms: int | None = None
    track_number: int | None = None
    disc_number: int | None = None
    recording_mbid: str | None = None  # already-known MBID (evidence tier 1)
    fingerprint_matched: bool = False  # candidate came via AcoustID
    isrc: str | None = None


@dataclass(slots=True)
class ScoredCandidate:
    score: float
    outcome: str
    details: dict

    @property
    def high_confidence(self) -> bool:
        return self.score >= AUTO_APPLY_THRESHOLD


def duration_ratio_score(evidence_ms: int | None, candidate_ms: int | None) -> float:
    """Duration component in [0.0, 1.0] using §8.3 tolerance bands."""
    if evidence_ms is None or candidate_ms is None or evidence_ms <= 0 or candidate_ms <= 0:
        return 0.0
    delta_seconds = abs(evidence_ms - candidate_ms) / 1000.0
    if delta_seconds <= DURATION_TOLERANCE_HIGH:
        return 1.0
    if delta_seconds <= DURATION_TOLERANCE_MEDIUM:
        return 0.6
    if delta_seconds <= DURATION_TOLERANCE_WEAK:
        return 0.3
    return 0.0


def score_candidate(evidence: ScoredEvidence, candidate) -> tuple[float, str, dict]:
    """Score one ProviderMatch-shaped candidate. Returns (score, outcome, details).

    ``candidate`` needs: recording_mbid, artist, title, release_title,
    duration_ms, track_number, source. Accepts any object with those
    attributes (ProviderMatch, dict-like wrappers).
    """
    details: dict[str, float] = {}

    mbid_score = WEIGHT_MBID_EXACT if (
        evidence.recording_mbid
        and getattr(candidate, "recording_mbid", None)
        and evidence.recording_mbid == candidate.recording_mbid
    ) else 0.0
    details["mbid_exact"] = mbid_score

    fingerprint_score = WEIGHT_FINGERPRINT if (
        evidence.fingerprint_matched and getattr(candidate, "source", "") == "acoustid"
    ) else 0.0
    details["fingerprint"] = fingerprint_score

    artist_sim = similarity(evidence.artist, getattr(candidate, "artist", None))
    title_sim = similarity(evidence.title, getattr(candidate, "title", None))
    details["artist_similarity"] = artist_sim
    details["title_similarity"] = title_sim

    artist_score = WEIGHT_ARTIST_SIMILARITY * artist_sim
    title_score = WEIGHT_TITLE_SIMILARITY * title_sim
    details["artist_score"] = artist_score
    details["title_score"] = title_score

    album_sim = similarity(evidence.release_title, getattr(candidate, "release_title", None))
    album_score = WEIGHT_ALBUM_SIMILARITY * album_sim
    details["album_score"] = album_score

    duration_component = duration_ratio_score(evidence.duration_ms, getattr(candidate, "duration_ms", None))
    duration_score = WEIGHT_DURATION_SIMILARITY * duration_component
    details["duration_score"] = duration_score

    track_consistent = (
        evidence.track_number is not None
        and getattr(candidate, "track_number", None) is not None
        and evidence.track_number == candidate.track_number
    )
    track_score = WEIGHT_TRACK_DISC_CONSISTENCY * (1.0 if track_consistent else 0.0)
    details["track_score"] = track_score

    isrc_score = WEIGHT_BARCODE_ISRC * (
        1.0 if evidence.isrc and getattr(candidate, "payload", {}).get("isrc") == evidence.isrc else 0.0
    )
    details["isrc_score"] = isrc_score

    score = (
        mbid_score
        + fingerprint_score
        + artist_score
        + title_score
        + album_score
        + duration_score
        + track_score
        + isrc_score
    )

    # §8.5 conflict penalties
    penalties = 0.0
    artist_conflict = (
        bool(evidence.artist)
        and bool(getattr(candidate, "artist", None))
        and artist_sim < DIFFERENT_ARTIST_SIMILARITY
        and title_sim >= STRONG_TITLE_SIMILARITY
    )
    if artist_conflict:
        penalties += PENALTY_DIFFERENT_ARTIST_STRONG_TITLE
    if (
        evidence.disc_number is not None
        and getattr(candidate, "disc_number", None) is not None
        and evidence.disc_number != candidate.disc_number
    ):
        penalties += PENALTY_DISC_CONTRADICTION
    if (
        evidence.track_number is not None
        and getattr(candidate, "track_number", None) is not None
        and evidence.track_number != candidate.track_number
    ):
        penalties += PENALTY_TRACK_CONTRADICTION
    if duration_component == 0.0 and evidence.duration_ms and getattr(candidate, "duration_ms", None):
        penalties += PENALTY_DURATION_CONTRADICTION
    details["penalties"] = penalties

    score = max(0.0, min(100.0, score + penalties))

    # §8.3 note: dynamically let the strongest evidence dominate.
    # Exact MBID (§7 tier 1) is canonical identity — it outranks tag conflicts.
    if mbid_score > 0:
        score = max(score, AUTO_APPLY_THRESHOLD)
    # A strong fingerprint match (AcoustID + plausible duration) floors at
    # review level — but never when the artist conflicts (e.g. cover bands).
    strong_fingerprint = (
        fingerprint_score > 0 and duration_component >= 0.6 and not artist_conflict
    )
    if strong_fingerprint:
        score = max(score, AUTO_SUGGEST_REVIEW_THRESHOLD)

    details["total"] = score
    details["scoring_version"] = SCORING_VERSION

    outcome = (
        AUTO_APPLY if score >= AUTO_APPLY_THRESHOLD
        else AUTO_SUGGEST_REVIEW if score >= AUTO_SUGGEST_REVIEW_THRESHOLD
        else REVIEW_REQUIRED if score >= REVIEW_REQUIRED_THRESHOLD
        else NO_MATCH
    )
    return score, outcome, details


def score_candidates(evidence: ScoredEvidence, candidates) -> list[tuple]:
    """Score and sort candidates: [(score, outcome, details, candidate)] desc."""
    scored = []
    for candidate in candidates:
        score, outcome, details = score_candidate(evidence, candidate)
        scored.append((score, outcome, details, candidate))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored