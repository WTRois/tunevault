"""Spectral analysis + upsample detection tests (TV2-030, blueprint §12.3).

Synthetic upsample: white noise band-limited to 18 kHz at 44.1 kHz, then
resampled to 176.4 kHz — hi-res container, standard-res content. Samples
are generated with the ffmpeg binary itself; skipped when unavailable.
"""

import subprocess

import pytest

from backend.audio.spectral import analyze_spectral, classify_upsample
from backend.core.config import settings

FFMPEG = settings.FFMPEG_PATH


def _ffmpeg_available() -> bool:
    try:
        subprocess.run([FFMPEG, "-version"], capture_output=True, timeout=10, check=False)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


pytestmark = pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg binary not available")


def _generate(args: list[str], path) -> str:
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args, str(path)], check=True
    )
    return str(path)


@pytest.fixture(name="base_path")
def base_fixture(tmp_path):
    """Band-limited white noise at 44.1 kHz — a normal standard-res file."""
    return _generate(
        [
            "-f", "lavfi",
            "-i", "anoisesrc=colour=white:sample_rate=44100:duration=2",
            "-af", "lowpass=f=18000",
            "-c:a", "flac",
        ],
        tmp_path / "base.flac",
    )


@pytest.fixture(name="upsampled_path")
def upsampled_fixture(tmp_path, base_path):
    """The same content resampled to 176.4 kHz — the synthetic upsample."""
    return _generate(["-i", base_path, "-ar", "176400", "-c:a", "flac"], tmp_path / "up.flac")


@pytest.fixture(name="hires_path")
def hires_fixture(tmp_path):
    """Full-band white noise at 176.4 kHz — genuine hi-res content."""
    return _generate(
        [
            "-f", "lavfi",
            "-i", "anoisesrc=colour=white:sample_rate=176400:duration=2",
            "-c:a", "flac",
        ],
        tmp_path / "hires.flac",
    )


def test_spectral_measures_present(hires_path):
    spectral = analyze_spectral(hires_path)
    assert spectral["spectral_centroid"] is not None and spectral["spectral_centroid"] > 0
    assert spectral["frequency_ceiling_hz"] is not None
    assert spectral["frequency_ceiling_hz"] > 60_000


def test_upsampled_file_is_flagged(base_path, upsampled_path):
    spectral = analyze_spectral(upsampled_path)
    assert spectral["frequency_ceiling_hz"] is not None
    # Content stops at ~18 kHz while the container claims 176.4 kHz.
    assert spectral["frequency_ceiling_hz"] < 30_000
    verdict = classify_upsample(176_400, spectral["frequency_ceiling_hz"])
    assert verdict["status"] == "possible_upsample"
    assert verdict["confidence"] in ("medium", "high")


def test_normal_standard_res_not_flagged(base_path):
    spectral = analyze_spectral(base_path)
    assert spectral["frequency_ceiling_hz"] is not None
    assert classify_upsample(44_100, spectral["frequency_ceiling_hz"])["status"] == "normal"


def test_genuine_hires_not_flagged(hires_path):
    spectral = analyze_spectral(hires_path)
    verdict = classify_upsample(176_400, spectral["frequency_ceiling_hz"])
    assert verdict["status"] == "normal"


def test_classify_insufficient_data():
    assert classify_upsample(None, None)["status"] == "insufficient_data"
    assert classify_upsample(96_000, None)["status"] == "insufficient_data"
    assert classify_upsample(None, 20_000.0)["status"] == "insufficient_data"
    # Warning-only statuses, never an absolute "fake" verdict.
    # Blueprint §12.3 example: 192 kHz claim, ~18 kHz ceiling → medium.
    assert classify_upsample(192_000, 18_000.0) == {
        "status": "possible_upsample",
        "confidence": "medium",
    }
    # Deep below even that — high confidence.
    assert classify_upsample(192_000, 8_000.0)["confidence"] == "high"
    # Genuine ultrasonic content up to 40 kHz on 96 kHz — normal.
    assert classify_upsample(96_000, 40_000.0)["status"] == "normal"