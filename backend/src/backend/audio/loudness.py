"""Loudness analysis via ffmpeg filters (blueprint §12.2, TV2-029).

Measures, per file:
    - integrated LUFS, true peak, loudness range (LRA)  → ebur128 filter
    - ReplayGain track gain                              → replaygain filter

Album gain needs whole-release grouping and is out of scope for the
per-file analyze job; the column stays NULL until an album-level pass
exists. Both filters only log results — nothing is written.
"""

import re

from backend.audio.ffmpeg import FFmpegToolError, run_ffmpeg_stderr

# Summary block of ebur128 (after the last "Summary:" marker):
#   Integrated loudness:  I: -23.0 LUFS
#   Loudness range:       LRA: 5.6 LU
#   True peak:            Peak: -1.2 dBFS
_INTEGRATED_RE = re.compile(r"\bI:\s*(-?[\d.]+)\s*LUFS")
_LRA_RE = re.compile(r"\bLRA:\s*([\d.]+)\s*LU")
_TRUE_PEAK_RE = re.compile(r"\bPeak:\s*(-?[\d.]+)\s*dBFS")

# replaygain filter log line:
#   track_gain = -8.12 dB_PM, track_peak = 0.987654,
_TRACK_GAIN_RE = re.compile(r"track_gain\s*=\s*([+-]?[\d.]+)\s*dB")


def _to_float(match: re.Match | None) -> float | None:
    return float(match.group(1)) if match else None


def measure_loudness(filepath: str) -> dict:
    """Integrated LUFS, true peak, loudness range via ebur128 (§12.2)."""
    stderr = run_ffmpeg_stderr(["-filter_complex", "ebur128=peak=true", "-f", "null", "-"], filepath)
    summary = stderr.rsplit("Summary:", maxsplit=1)[-1]  # per-frame lines also carry I:/LRA:
    return {
        "integrated_lufs": _to_float(_INTEGRATED_RE.search(summary)),
        "true_peak_db": _to_float(_TRUE_PEAK_RE.search(summary)),
        "dynamic_range": _to_float(_LRA_RE.search(summary)),
    }


def measure_replaygain(filepath: str) -> dict:
    """ReplayGain track gain via ffmpeg's replaygain filter (§12.2)."""
    stderr = run_ffmpeg_stderr(["-af", "replaygain", "-f", "null", "-"], filepath)
    return {"replaygain_track_db": _to_float(_TRACK_GAIN_RE.search(stderr))}


def analyze_loudness(filepath: str) -> dict:
    """All §12.2 loudness measurements for one file, in a single dict.

    A binary/decode failure of one measurement degrades to NULL fields
    instead of failing the whole analyze job.
    """
    combined: dict = {"replaygain_album_db": None}
    for measure in (measure_loudness, measure_replaygain):
        try:
            combined.update(measure(filepath))
        except FFmpegToolError:
            continue
    return combined