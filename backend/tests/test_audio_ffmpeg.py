"""FFprobe wrapper + technical metadata tests (TV2-028, blueprint §12.1/§32).

Sample files are generated with the ffmpeg binary itself — no fixture
files in the repo. Skipped automatically when ffmpeg is unavailable.
"""

import subprocess

import pytest

from backend.audio.ffmpeg import (
    FFmpegToolError,
    FFmpegUnavailable,
    classify_lossless,
    probe_technical_metadata,
)
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


@pytest.fixture(name="flac_path")
def flac_fixture(tmp_path):
    return _generate(
        ["-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=44100:duration=1", "-c:a", "flac"],
        tmp_path / "tone.flac",
    )


def test_probe_flac(flac_path):
    meta = probe_technical_metadata(flac_path)
    assert meta["codec"] == "flac"
    assert meta["container"] == "flac"
    assert meta["sample_rate"] == 44100
    assert meta["bit_depth"] == 16
    assert meta["channels"] == 1
    assert meta["lossless"] is True
    assert meta["duration"] is not None and 0.9 < meta["duration"] <= 1.0


def test_probe_wav_24bit(tmp_path):
    path = _generate(
        [
            "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000:duration=1",
            "-c:a", "pcm_s24le",
        ],
        tmp_path / "tone24.wav",
    )
    meta = probe_technical_metadata(path)
    assert meta["codec"].startswith("pcm_s24")
    assert meta["bit_depth"] == 24
    assert meta["sample_rate"] == 48000
    assert meta["lossless"] is True


def test_probe_mp3_lossy(tmp_path):
    path = _generate(
        [
            "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=44100:duration=1",
            "-c:a", "libmp3lame", "-b:a", "128k",
        ],
        tmp_path / "tone.mp3",
    )
    meta = probe_technical_metadata(path)
    assert meta["codec"] == "mp3"
    assert meta["lossless"] is False
    assert meta["bit_depth"] is None
    assert meta["bitrate"] is not None and meta["bitrate"] > 100_000


def test_probe_missing_file_maps_to_error(tmp_path):
    with pytest.raises(FFmpegToolError):
        probe_technical_metadata(str(tmp_path / "missing.flac"))


def test_missing_binary_maps_to_unavailable(flac_path, monkeypatch):
    monkeypatch.setattr(settings, "FFPROBE_PATH", "/nonexistent/ffprobe")
    with pytest.raises(FFmpegUnavailable):
        probe_technical_metadata(flac_path)


def test_classify_lossless_table():
    assert classify_lossless("flac") is True
    assert classify_lossless("ALAC") is True
    assert classify_lossless("pcm_s16le") is True
    assert classify_lossless("mp3") is False
    assert classify_lossless("vorbis") is False
    assert classify_lossless(None) is None
    assert classify_lossless("futurecodec") is None