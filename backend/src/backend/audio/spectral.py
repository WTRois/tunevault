"""Spectral analysis + suspicious upsample detection (blueprint §12.3, TV2-030).

The audio window is loaded at NATIVE sample rate — a 22050 Hz resample
(the V1 BPM/key default) would cap the detectable ceiling at ~11 kHz and
make upsample detection impossible on hi-res files.

Frequency ceiling = cutoff detection: the first bin at/above 16 kHz whose
mean magnitude drops more than 25 dB below the 1–5 kHz passband average
AND stays below it. Upsampled files keep a flat resampler/quantization
noise floor all the way to the (new) Nyquist, so absolute thresholds or
energy percentiles cannot separate content from noise — but the hard
step at the original Nyquist stands out. Genuine hi-res content has no
such step and its ceiling lands near Nyquist.

Upsample classification is WARNING-ONLY: ``classify_upsample`` never
returns an absolute "fake hi-res" verdict, only ``normal`` /
``possible_upsample`` / ``insufficient_data``, and nothing anywhere is
modified based on it.
"""

import numpy as np
from loguru import logger

# Cutoff detection: drop depth below the passband reference, and the
# frequency above which the drop is looked for.
_DROP_DB = 25.0
_SCAN_FROM_HZ = 16_000
_WINDOW_SECONDS = 30.0


def analyze_spectral(filepath: str, total_duration: float | None = None) -> dict:
    """Spectral centroid + frequency ceiling (§12.3) from a middle window."""
    result: dict[str, float | None] = {
        "spectral_centroid": None,
        "frequency_ceiling_hz": None,
    }
    try:
        import librosa

        offset = 0.0
        duration = _WINDOW_SECONDS
        if total_duration and total_duration > _WINDOW_SECONDS + 10.0:
            offset = (total_duration / 2.0) - (_WINDOW_SECONDS / 2.0)

        y, sr = librosa.load(
            filepath, sr=None, mono=True, offset=offset, duration=duration
        )
        if y is None or len(y) == 0:
            return result

        centroid = librosa.feature.spectral_centroid(y=y, sr=sr).mean()

        magnitudes = np.abs(librosa.stft(y)).mean(axis=1)
        freqs = librosa.fft_frequencies(sr=sr)
        result["frequency_ceiling_hz"] = _detect_ceiling(magnitudes, freqs)
        result["spectral_centroid"] = round(float(centroid), 1)
    except Exception as err:  # noqa: BLE001
        logger.debug(f"Spectral analysis skipped for {filepath}: {err}")
    return result


def _detect_ceiling(magnitudes, freqs) -> float:
    """Highest content frequency via cutoff detection (see module docstring)."""
    if len(freqs) == 0 or magnitudes.max() <= 0:
        return 0.0

    passband = (freqs >= 1000) & (freqs <= 5000)
    reference = magnitudes[passband].mean() if passband.any() else magnitudes.mean()
    drop_level = reference * 10 ** (-_DROP_DB / 20)

    start = int(np.searchsorted(freqs, _SCAN_FROM_HZ))
    if start >= len(freqs):
        return round(float(freqs[-1]), 1)  # spectrum ends below 16 kHz

    below = magnitudes[start:] < drop_level
    if below.any():
        rel = int(np.argmax(below))
        if below[rel:].all():
            # Hard cutoff — content stops here (the upsample signature).
            return round(float(freqs[start + rel]), 1)
        # Dips below then rises again (sparse ultrasonic content):
        # ceiling is the highest bin still at/above the drop level.
        return round(float(freqs[start:][~below][-1]), 1)
    # No drop anywhere — genuine full-band content.
    return round(float(freqs[-1]), 1)


def classify_upsample(
    sample_rate: int | None, frequency_ceiling_hz: float | None
) -> dict[str, str | None]:
    """Suspicious upsample classification — WARNING-ONLY (§12.3).

    Hi-res files whose content stops far below Nyquist are flagged
    ``possible_upsample``; thresholds mirror the blueprint example (a
    192 kHz file with an ~18 kHz ceiling → possible, medium confidence).
    The caller may only *display* the verdict, never act on it.
    """
    if not sample_rate or not frequency_ceiling_hz:
        return {"status": "insufficient_data", "confidence": None}

    nyquist = sample_rate / 2.0
    if nyquist <= 24_000:
        # Standard-res container: content naturally stops near Nyquist —
        # there is no "hi-res claim" that could be suspicious.
        return {"status": "normal", "confidence": "high"}

    ratio = frequency_ceiling_hz / nyquist
    if ratio >= 0.35:
        return {"status": "normal", "confidence": "high"}
    if ratio >= 0.18:
        return {"status": "possible_upsample", "confidence": "medium"}
    return {"status": "possible_upsample", "confidence": "high"}