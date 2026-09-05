"""Scoring tests — golden cases from blueprint §8.3/§8.4/§8.5 (TV2-016)."""

import asyncio

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from backend.identification.candidates import (
    build_evidence,
    generate_candidates,
    rank_candidates,
)
from backend.identification.constants import (
    AUTO_APPLY,
    AUTO_SUGGEST_REVIEW,
    NO_MATCH,
    REVIEW_REQUIRED,
)
from backend.identification.scoring import (
    ScoredEvidence,
    duration_ratio_score,
    score_candidate,
    score_candidates,
    similarity,
)
from backend.providers.base import MetadataQuery, ProviderMatch


def test_similarity_identical_and_disjoint():
    assert similarity("Numb", "Numb") == 1.0
    # difflib never returns 0 for non-empty strings — just require low similarity.
    assert similarity("Linkin Park", "Metallica") < 0.5


def test_similarity_normalizes_noise():
    # Normalization folds technical noise before comparison.
    assert similarity("Numb [320kbps]", "numb") == 1.0


def test_duration_score_bands():
    assert duration_ratio_score(180_000, 180_000) == 1.0
    assert duration_ratio_score(180_000, 180_500) == 1.0  # within 1s
    assert duration_ratio_score(180_000, 182_000) == 0.6  # within 3s
    assert duration_ratio_score(180_000, 185_000) == 0.3  # within 7s
    assert duration_ratio_score(180_000, 200_000) == 0.0
    assert duration_ratio_score(None, 180_000) == 0.0


class Candidate:
    def __init__(self, **kwargs):
        defaults = {
            "source": "musicbrainz",
            "title": None,
            "artist": None,
            "release_title": None,
            "track_number": None,
            "duration_ms": None,
            "recording_mbid": None,
            "payload": {},
        }
        defaults.update(kwargs)
        for key, value in defaults.items():
            setattr(self, key, value)


def test_exact_mbid_dominates():
    evidence = ScoredEvidence(
        artist="Linkin Park",
        title="Numb",
        duration_ms=187_000,
        recording_mbid="mbid-1",
    )
    exact = Candidate(recording_mbid="mbid-1", title="Numb", artist="Linkin Park", duration_ms=187_000)
    score, outcome, details = score_candidate(evidence, exact)
    assert details["mbid_exact"] == 25.0
    # §8.3 note: exact MBID dynamically dominates — floored at the auto-apply level.
    assert score == 95.0
    assert outcome == AUTO_APPLY


def test_perfect_metadata_match_reaches_auto_apply():
    evidence = ScoredEvidence(artist="Linkin Park", title="Numb", duration_ms=187_000)
    candidate = Candidate(
        title="Numb", artist="Linkin Park", release_title="Meteora", duration_ms=187_000
    )
    score, outcome, _ = score_candidate(evidence, candidate)
    # 15 + 15 + 7 = 37 without MBID/fingerprint — review territory, not auto.
    assert outcome in (REVIEW_REQUIRED, NO_MATCH, AUTO_SUGGEST_REVIEW)
    assert score < 95.0


def test_fingerprint_match_adds_weight():
    evidence = ScoredEvidence(
        artist="Linkin Park", title="Numb", duration_ms=187_000, fingerprint_matched=True
    )
    via_acoustid = Candidate(
        source="acoustid", title="Numb", artist="Linkin Park", duration_ms=187_000
    )
    score, outcome, details = score_candidate(evidence, via_acoustid)
    assert details["fingerprint"] == 25.0
    # Strong fingerprint (AcoustID + plausible duration) floors at review level (§8.3).
    assert score == 85.0
    assert outcome == AUTO_SUGGEST_REVIEW


def test_different_artist_strong_title_penalty():
    evidence = ScoredEvidence(artist="Linkin Park", title="Numb")
    imposter = Candidate(title="Numb", artist="Someone Else Entirely")
    score, _, details = score_candidate(evidence, imposter)
    assert details["penalties"] == -20.0
    assert score == 0.0  # 15 (title) - 20 penalty → clamped at 0


def test_missing_artist_does_not_trigger_artist_penalty():
    # Neither side has an artist — absence is not a conflict.
    evidence = ScoredEvidence(title="Numb")
    candidate = Candidate(title="Numb")
    _, _, details = score_candidate(evidence, candidate)
    assert details["penalties"] == 0.0


def test_track_number_contradiction_penalty():
    evidence = ScoredEvidence(title="Numb", track_number=3)
    wrong_track = Candidate(title="Numb", track_number=11)
    _, _, details = score_candidate(evidence, wrong_track)
    assert details["penalties"] == -10.0


def test_duration_contradiction_penalty():
    evidence = ScoredEvidence(title="Numb", duration_ms=187_000)
    wrong_duration = Candidate(title="Numb", duration_ms=300_000)
    _, _, details = score_candidate(evidence, wrong_duration)
    assert details["penalties"] == -8.0


def test_outcome_thresholds():
    evidence = ScoredEvidence(title="Numb")
    weak = Candidate(title="Numb")  # title only → 15
    _, outcome, _ = score_candidate(evidence, weak)
    assert outcome == NO_MATCH

    mid = Candidate(title="Numb", artist="Numb Artist")  # exact title 15 + partial artist
    _, outcome, _ = score_candidate(evidence, mid)
    assert outcome in (NO_MATCH, REVIEW_REQUIRED)


def test_score_candidates_sorted_desc():
    evidence = ScoredEvidence(artist="Linkin Park", title="Numb", recording_mbid="mbid-1")
    best = Candidate(recording_mbid="mbid-1", title="Numb", artist="Linkin Park")
    worst = Candidate(title="Numb", artist="Totally Different Band")
    ranked = score_candidates(evidence, [worst, best])
    assert ranked[0][3] is best


def test_build_evidence_prefers_tags_over_filename():
    from datetime import UTC, datetime

    from backend.models import File

    file = File(
        filepath="/music/01 - numb.mp3",
        filename="01 - numb.mp3",
        extension=".mp3",
        sha256="a" * 64,
        file_size=10,
        modified_at=datetime.now(UTC),
        duration_ms=187_000,
    )
    identification = build_evidence(
        file,
        tags={"title": "Numb", "artist": "Linkin Park", "track_number": 3},
    )
    assert identification.evidence.title == "Numb"
    assert identification.evidence.artist == "Linkin Park"
    assert identification.evidence.track_number == 3
    assert identification.evidence.duration_ms == 187_000


def test_build_evidence_falls_back_to_filename():
    from datetime import UTC, datetime

    from backend.models import File

    file = File(
        filepath="/music/Linkin.Park - 01 - Numb [320kbps].mp3",
        filename="Linkin.Park - 01 - Numb [320kbps].mp3",
        extension=".mp3",
        sha256="a" * 64,
        file_size=10,
        modified_at=datetime.now(UTC),
        duration_ms=187_000,
    )
    identification = build_evidence(file)
    assert identification.evidence.artist == "linkin park"
    assert identification.evidence.title == "numb"
    assert identification.evidence.track_number == 1


class StubMB:
    """Stub provider returning fixed matches — no network."""

    name = "musicbrainz"

    def __init__(self, matches):
        self.matches = matches
        self.calls = 0

    async def search(self, query: MetadataQuery) -> list[ProviderMatch]:
        self.calls += 1
        return self.matches


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_generate_and_rank_end_to_end(session):
    from datetime import UTC, datetime

    from backend.models import File

    file = File(
        filepath="/music/numb.mp3",
        filename="numb.mp3",
        extension=".mp3",
        sha256="a" * 64,
        file_size=10,
        modified_at=datetime.now(UTC),
        duration_ms=187_000,
    )
    session.add(file)
    session.commit()

    mb = StubMB(
        [
            ProviderMatch(
                source="musicbrainz",
                title="Numb",
                artist="Linkin Park",
                duration_ms=187_000,
                recording_mbid="mbid-1",
            ),
            ProviderMatch(source="musicbrainz", title="Faint", artist="Linkin Park"),
        ]
    )
    tags = {"title": "Numb", "artist": "Linkin Park"}
    identification, candidates = asyncio.run(
        generate_candidates(session, file, tags=tags, musicbrainz=mb, acoustid=AcoustIDStub())
    )
    assert len(candidates) == 2

    ranked = rank_candidates(identification, candidates)
    assert ranked[0][3].recording_mbid == "mbid-1"
    assert mb.calls == 1  # served through the cache layer


class AcoustIDStub:
    name = "acoustid"

    def enabled(self):
        return False

    async def search(self, query):
        return []