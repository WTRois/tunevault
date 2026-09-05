"""Tests for normalization + filename parsing (TV2-015, blueprint §8.2)."""

from backend.identification.normalize import NORMALIZER_VERSION, normalize_text
from backend.identification.parse_filename import parse_filename


def test_blueprint_example():
    """§8.2: 'Linkin.Park - 01 - Numb [320kbps]' → artist/title/track/noise."""
    parsed = parse_filename("Linkin.Park - 01 - Numb [320kbps].mp3")
    assert parsed.artist == "linkin park"
    assert parsed.title == "numb"
    assert parsed.track_number == 1
    assert "320kbps" in parsed.noise


def test_normalize_unicode_and_separators():
    # NFKC keeps accented letters (only compatibility forms are folded).
    assert normalize_text("  Café   Français ") == "café français"
    assert normalize_text("㍿ Song") == "株式会社 song"  # NFKC unfolds the single glyph
    assert normalize_text("A_B.C-D") == "a b c d"
    assert normalize_text("[320kbps] Song (Official Video)") == "song"
    assert normalize_text("Song feat. Someone") == "song someone"


def test_normalize_keeps_edition_labels():
    # Live/remix/acoustic are meaningful edition labels (§8.2) — preserved.
    assert normalize_text("Numb (Live)") == "numb live"
    assert normalize_text("Numb - Remastered") == "numb"


def test_normalize_empty_and_none():
    assert normalize_text(None) == ""
    assert normalize_text("") == ""


def test_parse_leading_track_number():
    parsed = parse_filename("01 - Numb.mp3")
    assert parsed.artist is None
    assert parsed.title == "numb"
    assert parsed.track_number == 1


def test_parse_artist_title():
    parsed = parse_filename("Daft Punk - One More Time.flac")
    assert parsed.artist == "daft punk"
    assert parsed.title == "one more time"
    assert parsed.track_number is None


def test_parse_title_only():
    parsed = parse_filename("One More Time.mp3")
    assert parsed.artist is None
    assert parsed.title == "one more time"


def test_parse_brackets_become_noise():
    parsed = parse_filename("Artist - Song [CD Rip 24 Bit].flac")
    assert parsed.artist == "artist"
    assert parsed.title == "song"
    assert any("24 bit" in n or "cd rip" in n for n in parsed.noise)


def test_normalizer_version_is_set():
    assert NORMALIZER_VERSION == "1"