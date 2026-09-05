"""Configuration tests (TV2-038, blueprint §38)."""

import importlib

import pytest
from pydantic import ValidationError

from backend.core.config import Settings, settings, validate_startup


def test_cors_origins_accepts_comma_separated_string():
    """Compose §30 sets CORS_ORIGINS=http://localhost:5173 (plain string)."""
    config = Settings(CORS_ORIGINS="http://localhost:5173")
    assert config.CORS_ORIGINS == ["http://localhost:5173"]

    config = Settings(CORS_ORIGINS=" http://a.com ,http://b.com ,, http://c.com ")
    assert config.CORS_ORIGINS == ["http://a.com", "http://b.com", "http://c.com"]


def test_cors_origins_accepts_json_list():
    config = Settings(CORS_ORIGINS=["http://a.com", "http://b.com"])
    assert config.CORS_ORIGINS == ["http://a.com", "http://b.com"]


def test_threshold_ordering_enforced():
    with pytest.raises(ValidationError, match="AUTO_APPLY"):
        Settings(IDENTIFICATION_AUTO_APPLY_THRESHOLD=50.0)  # below REVIEW (85)

    with pytest.raises(ValidationError, match="AUTO_APPLY"):
        Settings(IDENTIFICATION_REVIEW_THRESHOLD=60.0)  # below REJECT (70)

    # Equal bands are allowed (e.g. auto-apply == review).
    config = Settings(IDENTIFICATION_REVIEW_THRESHOLD=95.0)
    assert config.IDENTIFICATION_REVIEW_THRESHOLD == 95.0


def test_log_validation():
    with pytest.raises(ValidationError, match="LOG_LEVEL"):
        Settings(LOG_LEVEL="VERBOSE")
    with pytest.raises(ValidationError, match="LOG_FORMAT"):
        Settings(LOG_FORMAT="xml")
    assert Settings(LOG_LEVEL="debug").LOG_LEVEL == "DEBUG"  # normalized


def test_thresholds_wire_into_scoring_constants(monkeypatch):
    """§8.4 thresholds read from settings (§38) at import time."""
    from backend.core.config import settings as live_settings
    from backend.identification import constants

    monkeypatch.setattr(live_settings, "IDENTIFICATION_AUTO_APPLY_THRESHOLD", 97.0)
    monkeypatch.setattr(live_settings, "IDENTIFICATION_REJECT_THRESHOLD", 65.0)
    try:
        reloaded = importlib.reload(constants)  # re-reads the patched singleton
        assert reloaded.AUTO_APPLY_THRESHOLD == 97.0
        assert reloaded.REVIEW_REQUIRED_THRESHOLD == 65.0
    finally:
        monkeypatch.undo()  # restore original attribute values
        importlib.reload(constants)  # restore defaults for other tests

    assert constants.AUTO_APPLY_THRESHOLD == 95.0
    assert constants.REVIEW_REQUIRED_THRESHOLD == 70.0


def test_validate_startup_passes_by_default():
    validate_startup()  # must not raise with default settings


def test_validate_startup_fails_fast_on_missing_required(monkeypatch):
    monkeypatch.setattr(settings, "MUSIC_DIR", "")
    with pytest.raises(RuntimeError, match="MUSIC_DIR"):
        validate_startup()

    monkeypatch.setattr(settings, "MUSIC_DIR", "/music")
    monkeypatch.setattr(settings, "CORS_ORIGINS", [])
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        validate_startup()


def test_user_agent_override():
    from backend.providers.http import build_user_agent

    default_ua = build_user_agent()
    assert default_ua.startswith("TuneVault/")

    config = Settings(MUSICBRAINZ_USER_AGENT="TuneVault/2.0 (contact@example.com)")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "backend.providers.http.settings",
        config,
    )
    try:
        assert build_user_agent() == "TuneVault/2.0 (contact@example.com)"
    finally:
        monkeypatch.undo()