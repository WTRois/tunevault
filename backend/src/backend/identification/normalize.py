"""Text normalization for fuzzy matching (blueprint §8.2).

Normalized output is a comparison token only — the raw value is never
overwritten (§8.2 "Never overwrite original raw value").
"""

import re
import unicodedata

from backend.core.versions import NORMALIZER_VERSION

__all__ = ["NORMALIZER_VERSION", "normalize_text"]

# Noise tokens stripped from filenames before comparison (§8.2 technical suffixes).
NOISE_PATTERNS = [
    r"\b(?:320|256|192|128|2565)?\s?kbps\b",
    r"\b(?:flac|mp3|ogg|m4a|wav|alac|ape|opus)\b",
    r"\b(?:cd|web)?\s?rip\b",
    r"\b24\s?bit\b",
    r"\b(?:19|20)\d{2}\b\s*$",
    r"\bofficial\s+(?:music\s+)?(?:video|audio)\b",
    r"\blyric\s+video\b",
    r"\bvisualizer\b",
    r"\bhd\b",
    r"\bhq\b",
    r"\b(?:feat\.?|featuring)\b",
]

_SEPARATOR_RE = re.compile(r"[\s_\-.]+")
_BRACKET_RE = re.compile(r"[\[\](){}]")
_FEAT_RE = re.compile(r"\bfeat\.?\s+", re.IGNORECASE)
_REMASTER_RE = re.compile(
    r"\b(?:\d{4}\s*)?(?:remaster(?:ed)?(?:\s+\d{4})?|deluxe|special|anniversary)\b.*$",
    re.IGNORECASE,
)


def normalize_text(value: str | None) -> str:
    """Normalize a title/artist/filename fragment for comparison.

    Unicode NFKC → lowercase → strip technical noise → normalize separators
    → collapse whitespace. Meaningful edition labels (live, remix, acoustic)
    are preserved (§8.2).
    """
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value)
    text = text.lower()
    text = _BRACKET_RE.sub(" ", text)
    for pattern in NOISE_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    text = _FEAT_RE.sub(" ", text)
    # Strip technical edition suffixes; keep meaningful labels (live/remix/acoustic).
    text = _REMASTER_RE.sub(" ", text)
    text = _SEPARATOR_RE.sub(" ", text)
    return " ".join(text.split()).strip()