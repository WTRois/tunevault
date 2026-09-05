"""Loudness ebur128 tests (TV2-029, blueprint §12.2).

Fixture: aevalsrc 0.5·sin(2π·1000t) — deterministic half-scale sine.
K-weighting is ~0 dB at 1 kHz, so integrated loudness ≈ RMS = -9.0 LUFS
and true peak ≈ -6.0 dBFS. Samples are generated with the ffmpeg binary
itself; skipped when it is unavailable.
"""

import subprocess

import pytest

from backend.audio.loudness import analyze_loudness, measure_loudness, measure_replaygain
from backend.core.config import settings

FFMPEG = settings.FFMPEG_PATH


def _ffmpeg_available() -> bool:
    try:
        subprocess.run([FFMPEG, "-version"], capture_output=True, timeout=10, check=False)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


pytestmark = pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg binary not available")


@pytest.fixture(name="sine_path")
def sine_fixture(tmp_path):
    path = tmp_path / "sine.flac"
    subprocess.run(
        [
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "aevalsrc=0.5*sin(2*PI*1000*t):s=48000:d=2",
            "-c:a", "flac", str(path),
        ],
        check=True,
    )
    return str(path)


def test_ebur128_sine_alignment(sine_path):
    loudness = measure_loudness(sine_path)
    # Half-scale 1 kHz sine ≈ -9.0 LUFS / -6.0 dBFS true peak (tolerance ±1.5).
    assert loudness["integrated_lufs"] is not None
    assert abs(loudness["integrated_lufs"] - (-9.0)) < 1.5
    assert loudness["true_peak_db"] is not None
    assert abs(loudness["true_peak_db"] - (-6.0)) < 1.5
    # A steady sine has essentially zero loudness range.
    assert loudness["dynamic_range"] is not None
    assert loudness["dynamic_range"] < 1.0


def test_replaygain_track_parsed(sine_path):
    gain = measure_replaygain(sine_path)
    assert gain["replaygain_track_db"] is not None
    assert abs(gain["replaygain_track_db"]) < 30.0


def test_analyze_loudness_combined(sine_path):
    combined = analyze_loudness(sine_path)
    assert combined["integrated_lufs"] is not None
    assert combined["replaygain_track_db"] is not None
    # Album gain is deferred to a future album-level pass (§12.2).
    assert combined["replaygain_album_db"] is None


def test_analyze_loudness_degrades_gracefully(monkeypatch, sine_path):
    from backend.audio import loudness as loudness_module

    def boom(filepath: str) -> dict:
        raise loudness_module.FFmpegToolError("boom")

    monkeypatch.setattr(loudness_module, "measure_loudness", boom)
    monkeypatch.setattr(loudness_module, "measure_replaygain", boom)
    combined = analyze_loudness(sine_path)
    assert combined == {"replaygain_album_db": None}