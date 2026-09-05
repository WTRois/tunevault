import numpy as np
from loguru import logger

# Pitch class names for Musical Key mapping
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def estimate_key_from_chroma(chroma: np.ndarray) -> str | None:
    """Estimate musical key from chroma STFT feature array."""
    if chroma is None or chroma.size == 0:
        return None

    # Mean chroma vector across time frames
    chroma_mean = np.mean(chroma, axis=1)
    if len(chroma_mean) != 12:
        return None

    # Dominant pitch class index
    key_index = int(np.argmax(chroma_mean))
    key_name = NOTE_NAMES[key_index]

    # Simple major/minor profile heuristics using third interval
    major_third_energy = chroma_mean[(key_index + 4) % 12]
    minor_third_energy = chroma_mean[(key_index + 3) % 12]

    mode = "Major" if major_third_energy >= minor_third_energy else "Minor"
    return f"{key_name} {mode}"


def analyze_audio_features(
    filepath: str, total_duration: float | None = None
) -> dict[str, None | float | str]:
    """Analyze audio using Librosa to estimate BPM and Musical Key.

    Optimized by loading a 30-second window from the middle of the audio file.
    """
    result: dict[str, None | float | str] = {
        "bpm": None,
        "musical_key": None,
    }

    try:
        import librosa

        offset = 0.0
        duration = 30.0

        if total_duration and total_duration > 40.0:
            offset = (total_duration / 2.0) - 15.0

        # Load audio segment with default sampling rate (22050 Hz) mono
        y, sr = librosa.load(filepath, sr=22050, mono=True, offset=offset, duration=duration)

        if y is None or len(y) == 0:
            return result

        # 1. Estimate BPM (Tempo)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        if isinstance(tempo, np.ndarray):
            tempo_val = float(tempo[0]) if tempo.size > 0 else None
        else:
            tempo_val = float(tempo)

        if tempo_val and tempo_val > 0:
            result["bpm"] = round(tempo_val, 1)

        # 2. Estimate Musical Key using Chroma STFT
        chroma = librosa.feature.chroma_stft(y=y, sr=sr)
        result["musical_key"] = estimate_key_from_chroma(chroma)

    except Exception as err:  # noqa: BLE001
        logger.debug(f"Audio analysis skipped for {filepath}: {err}")

    return result
