"""FFmpeg/FFprobe command execution (blueprint §32, TV2-028).

Subprocess rules (§32): argument list — never a shell string, timeout,
captured stderr, explicit binary path from config, explicit error mapping.

This module only runs commands and parses their output. No database, no
business logic — the analyze handler (TV2-031) decides what to persist.
"""

import json
import subprocess

from backend.core.config import settings

# Lossless classification (§12.1) by codec name — True/False/None(unknown).
LOSSLESS_CODECS = {"flac", "alac", "wavpack", "ape", "tak", "shorten", "mlp", "truehd"}
LOSSY_CODECS = {
    "mp3", "aac", "vorbis", "opus", "ac3", "eac3", "dts", "mp2",
    "wma", "wmav2", "wmapro", "cook", "atrac", "amr",
}


class FFmpegToolError(RuntimeError):
    """ffprobe/ffmpeg failed or produced unparseable output."""


class FFmpegUnavailable(FFmpegToolError):
    """The configured binary does not exist (§32 error mapping)."""


def _run(args: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
    """Run a tool subprocess with §32 guarantees; map errors explicitly."""
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout if timeout is not None else settings.FFMPEG_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as err:
        raise FFmpegUnavailable(f"Binary not found: {args[0]!r}") from err
    except subprocess.TimeoutExpired as err:
        raise FFmpegToolError(f"{args[0]} timed out after {err.timeout}s") from err
    if completed.returncode != 0:
        tail = " | ".join((completed.stderr or "").strip().splitlines()[-3:])
        raise FFmpegToolError(f"{args[0]} exited {completed.returncode}: {tail}")
    return completed


def run_ffprobe_json(filepath: str, timeout: int | None = None) -> dict:
    """Probe a media file and return the parsed ffprobe JSON."""
    completed = _run(
        [
            settings.FFPROBE_PATH,
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            filepath,
        ],
        timeout,
    )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as err:
        raise FFmpegToolError(f"ffprobe returned invalid JSON for {filepath}: {err}") from err


def run_ffmpeg_stderr(filter_args: list[str], filepath: str, timeout: int | None = None) -> str:
    """Run ffmpeg filters on a file, discard audio (-f null) and return stderr.

    Used by analysis filters (ebur128, replaygain) that report results via
    log lines; the command never writes output files.
    """
    args = [settings.FFMPEG_PATH, "-nostats", "-hide_banner", "-i", filepath, *filter_args]
    return _run(args, timeout).stderr or ""


def _to_int(value) -> int | None:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed or None


def _to_float(value) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _parse_bit_depth(stream: dict) -> int | None:
    """Bits per sample: raw sample bits first, then container bits, then
    an inference from the sample format (s16 → 16, s32 → 32)."""
    depth = _to_int(stream.get("bits_per_raw_sample"))
    if depth is None:
        depth = _to_int(stream.get("bits_per_sample"))
    if depth is not None:
        return depth
    sample_fmt = str(stream.get("sample_fmt") or "")
    if sample_fmt.startswith("s") and sample_fmt[1:].isdigit():
        return int(sample_fmt[1:])
    return None


def classify_lossless(codec: str | None) -> bool | None:
    """Lossless/lossy classification (§12.1) from the codec name."""
    if not codec:
        return None
    name = codec.lower()
    if name in LOSSLESS_CODECS or name.startswith("pcm_"):
        return True
    if name in LOSSY_CODECS:
        return False
    return None


def _parse_container(format_name: str | None, filepath: str) -> str | None:
    """Container name — for multi-token formats (mov,mp4,m4a,…) prefer the
    token matching the file's own extension, else the first token."""
    if not format_name:
        return None
    tokens = [token.strip() for token in format_name.split(",") if token.strip()]
    ext = filepath.rsplit(".", 1)[-1].lower()
    for token in tokens:
        if token == ext:
            return token
    return tokens[0]


def probe_technical_metadata(filepath: str) -> dict:
    """Technical metadata (blueprint §12.1) for one file, via ffprobe."""
    data = run_ffprobe_json(filepath)
    fmt = data.get("format") or {}
    stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {}
    )
    codec = stream.get("codec_name")
    bitrate = _to_int(fmt.get("bit_rate")) or _to_int(stream.get("bit_rate"))
    duration = _to_float(fmt.get("duration")) or _to_float(stream.get("duration"))
    return {
        "container": _parse_container(fmt.get("format_name"), filepath),
        "codec": codec,
        "bitrate": bitrate,
        "sample_rate": _to_int(stream.get("sample_rate")),
        "bit_depth": _parse_bit_depth(stream),
        "channels": _to_int(stream.get("channels")),
        "channel_layout": stream.get("channel_layout"),
        "duration": duration,
        "lossless": classify_lossless(codec),
    }