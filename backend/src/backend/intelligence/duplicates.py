"""Duplicate detection (blueprint §13, TV2-032) — SUGGEST-ONLY.

Two levels per §13: exact (SHA-256 equal) and audio (chromaprint
fingerprint similarity inside a duration window). Pairs sharing a
canonical recording link (MBID evidence) are classified
``SAME_RECORDING_DIFFERENT_FORMAT`` / ``SAME_RECORDING_DIFFERENT_RELEASE``.

§13: "Jangan otomatis menghapus duplicate. Default hanya suggest." —
there is deliberately NO delete/remove/unlink code path in this module;
its output is data for the review UI, nothing more.
"""

from collections import defaultdict
from itertools import combinations

import numpy as np
from sqlmodel import Session, select

from backend.models import File, FileRecording, FileRelease, Fingerprint

# Chromaprint raw frames are 32-bit words (~0.123s each). The same audio
# re-encoded compares at ~0.95+; unrelated audio sits near ~0.5.
AUDIO_SIMILARITY_MIN = 0.80
DURATION_WINDOW_MS = 3_000
_MIN_COMPARED_FRAMES = 8
_MAX_OFFSET_FRAMES = 8

# §13 classes that represent redundant audio; SAME_RECORDING_DIFFERENT_RELEASE
# is informational (compilation + album both kept) and never a problem count.
PROBLEM_CLASSES = ("EXACT_FILE_DUPLICATE", "AUDIO_DUPLICATE", "SAME_RECORDING_DIFFERENT_FORMAT")


def _parse_fingerprint(raw: str | None) -> np.ndarray | None:
    """Raw fpcalc -plain output: comma/space separated (signed) 32-bit words."""
    if not raw:
        return None
    try:
        words = [int(token) for token in raw.replace(",", " ").split()]
    except ValueError:
        return None
    if not words:
        return None
    return np.array(words, dtype=np.uint32) & np.uint32(0xFFFFFFFF)


def fingerprint_similarity(
    raw_a: str | None, raw_b: str | None, max_offset: int = _MAX_OFFSET_FRAMES
) -> float | None:
    """Best-offset mean bit similarity of two raw chromaprint streams.

    Returns None when either stream is missing/too short to judge.
    """
    a = _parse_fingerprint(raw_a)
    b = _parse_fingerprint(raw_b)
    if a is None or b is None:
        return None
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) < _MIN_COMPARED_FRAMES:
        return None

    best = 0.0
    for offset in range(-max_offset, max_offset + 1):
        if offset >= 0:
            n = min(len(shorter), len(longer) - offset)
            s_start, l_start = 0, offset
        else:
            n = min(len(shorter) + offset, len(longer))
            s_start, l_start = -offset, 0
        if n < _MIN_COMPARED_FRAMES:
            continue
        xor = shorter[s_start : s_start + n] ^ longer[l_start : l_start + n]
        similarity = 1.0 - float(np.bitwise_count(xor).mean()) / 32.0
        best = max(best, similarity)
    return best


def _pair_payload(file_a: File, file_b: File, classification: str, similarity) -> dict:
    return {
        "file_id_a": file_a.id,
        "filename_a": file_a.filename,
        "path_a": file_a.filepath,
        "file_id_b": file_b.id,
        "filename_b": file_b.filename,
        "path_b": file_b.filepath,
        "classification": classification,
        "similarity": similarity,
    }


def _pair_key(a_id, b_id) -> tuple[int, int]:
    return (min(a_id, b_id), max(a_id, b_id))


def find_exact_duplicates(session: Session) -> list[dict]:
    """Every pair of files sharing a SHA-256 (§13 exact level)."""
    files = session.exec(select(File).order_by(File.id)).all()
    by_sha: dict[str, list[File]] = defaultdict(list)
    for file in files:
        by_sha[file.sha256].append(file)
    pairs = []
    for group in by_sha.values():
        if len(group) < 2:
            continue
        for a, b in combinations(group, 2):
            pairs.append(_pair_payload(a, b, "EXACT_FILE_DUPLICATE", 1.0))
    return pairs


def find_audio_candidates(session: Session) -> list[tuple[File, File, float]]:
    """All fingerprint comparisons inside the §13 duration window, with
    their similarity — callers decide which ones matter."""
    rows = session.exec(
        select(File, Fingerprint).where(File.id == Fingerprint.file_id)
    ).all()
    entries = []
    for file, fp in rows:
        parsed = _parse_fingerprint(fp.fingerprint)
        if parsed is None or len(parsed) < _MIN_COMPARED_FRAMES:
            continue
        entries.append((file, fp))
    entries.sort(key=lambda e: e[1].duration_ms)

    compared = []
    for i, (file_a, fp_a) in enumerate(entries):
        for file_b, fp_b in entries[i + 1 :]:
            if fp_b.duration_ms - fp_a.duration_ms > DURATION_WINDOW_MS:
                break  # sorted by duration — nothing further can be in window
            similarity = fingerprint_similarity(fp_a.fingerprint, fp_b.fingerprint)
            if similarity is None:
                continue
            compared.append((file_a, file_b, similarity))
    return compared


def _recording_link_pairs(session: Session, releases: dict[int, int | None]) -> list[tuple]:
    """Pairs of files sharing a canonical recording link (§13 MBID level)."""
    recordings = session.exec(select(FileRecording).order_by(FileRecording.id)).all()
    by_recording: dict[int, list[FileRecording]] = defaultdict(list)
    for row in recordings:
        by_recording[row.recording_id].append(row)
    files = {f.id: f for f in session.exec(select(File)).all()}
    pairs = []
    for rows in by_recording.values():
        if len(rows) < 2:
            continue
        for a, b in combinations(rows, 2):
            file_a, file_b = files.get(a.file_id), files.get(b.file_id)
            if file_a is None or file_b is None:
                continue
            same_release = (
                releases.get(a.file_id) is not None
                and releases.get(a.file_id) == releases.get(b.file_id)
            )
            classification = (
                "SAME_RECORDING_DIFFERENT_FORMAT"
                if same_release
                else "SAME_RECORDING_DIFFERENT_RELEASE"
            )
            pairs.append((file_a, file_b, classification))
    return pairs


def find_duplicates(session: Session) -> list[dict]:
    """All duplicate pairs with §13 classifications — suggest-only data."""
    releases = {
        row.file_id: row.release_id
        for row in session.exec(select(FileRelease)).all()
    }
    recordings = {
        row.file_id: row.recording_id
        for row in session.exec(select(FileRecording)).all()
    }

    pairs: list[dict] = []
    seen: set[tuple[int, int]] = set()
    dissimilar: set[tuple[int, int]] = set()

    # 1. Exact byte duplicates — strongest evidence wins.
    for pair in find_exact_duplicates(session):
        seen.add(_pair_key(pair["file_id_a"], pair["file_id_b"]))
        pairs.append(pair)

    # 2. Acoustic matches inside the duration window.
    for file_a, file_b, similarity in find_audio_candidates(session):
        key = _pair_key(file_a.id, file_b.id)
        if key in seen:
            continue
        if similarity < AUDIO_SIMILARITY_MIN:
            dissimilar.add(key)  # acoustic evidence — remember the mismatch
            continue
        seen.add(key)
        if recordings.get(file_a.id) == recordings.get(file_b.id) and recordings.get(file_a.id):
            classification = (
                "AUDIO_DUPLICATE"
                if releases.get(file_a.id) == releases.get(file_b.id)
                else "SAME_RECORDING_DIFFERENT_RELEASE"
            )
        else:
            classification = "AUDIO_DUPLICATE"
        pairs.append(_pair_payload(file_a, file_b, classification, round(similarity, 3)))

    # 3. Recording-link evidence without acoustic confirmation — but an
    # explicit acoustic mismatch outranks the link (misidentification).
    for file_a, file_b, classification in _recording_link_pairs(session, releases):
        key = _pair_key(file_a.id, file_b.id)
        if key in seen or key in dissimilar:
            continue
        pairs.append(_pair_payload(file_a, file_b, classification, None))
        seen.add(key)

    return pairs


def duplicate_file_ids(session: Session) -> set[int]:
    """Files involved in problem-duplicate pairs (§13 redundant-audio
    classes only — informational release variants don't count)."""
    ids: set[int] = set()
    for pair in find_duplicates(session):
        if pair["classification"] not in PROBLEM_CLASSES:
            continue
        ids.add(pair["file_id_a"])
        ids.add(pair["file_id_b"])
    return ids