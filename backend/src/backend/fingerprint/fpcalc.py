"""fpcalc (Chromaprint) wrapper — subprocess discipline per blueprint §32.

Argument list (never a shell string), explicit binary path, timeout, captured
stderr, error mapping. Missing binary or failure degrades gracefully: callers
must treat fingerprinting as optional evidence.
"""

import shutil
from dataclasses import dataclass

FPCALC_DEFAULT_PATH = "fpcalc"
FPCALC_TIMEOUT_SECONDS = 30.0


class FpcalcError(RuntimeError):
    """fpcalc is unavailable or failed."""


@dataclass(frozen=True, slots=True)
class FpcalcResult:
    duration_ms: int
    fingerprint: str


class FpcalcUnavailable(FpcalcError):
    """The fpcalc binary is not installed — fingerprinting is skipped."""


def fpcalc_available(fpcalc_path: str = FPCALC_DEFAULT_PATH) -> bool:
    return shutil.which(fpcalc_path) is not None


def compute_fingerprint(filepath: str, fpcalc_path: str = FPCALC_DEFAULT_PATH) -> FpcalcResult:
    """Run fpcalc and return its duration + raw fingerprint.

    Raises :class:`FpcalcUnavailable` when the binary is missing (skip signal),
    or :class:`FpcalcError` on timeout/parse failure.
    """
    import subprocess

    binary = shutil.which(fpcalc_path)
    if binary is None:
        raise FpcalcUnavailable(f"fpcalc binary not found at '{fpcalc_path}'")

    try:
        completed = subprocess.run(
            [binary, "-length", "120", "-plain", filepath],
            capture_output=True,
            text=True,
            timeout=FPCALC_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as err:
        raise FpcalcError(f"fpcalc timed out for {filepath}") from err

    if completed.returncode != 0:
        stderr = completed.stderr.strip() or f"exit code {completed.returncode}"
        raise FpcalcError(f"fpcalc failed for {filepath}: {stderr}")

    lines = completed.stdout.strip().splitlines()
    if len(lines) < 2:
        raise FpcalcError(f"fpcalc produced no fingerprint for {filepath}")

    try:
        duration_ms = int(float(lines[0]) * 1000)
    except ValueError as err:
        raise FpcalcError(f"fpcalc returned unparsable duration for {filepath}") from err

    return FpcalcResult(duration_ms=duration_ms, fingerprint=lines[1].strip())