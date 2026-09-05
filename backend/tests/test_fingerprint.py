"""Tests for fpcalc wrapper + AcoustID provider (TV2-014, graceful degradation)."""

import asyncio
import stat
from pathlib import Path

import httpx
import pytest

from backend.fingerprint import fpcalc
from backend.fingerprint.fpcalc import FpcalcUnavailable, compute_fingerprint, fpcalc_available
from backend.providers.acoustid import AcoustIDProvider
from backend.providers.base import MetadataQuery


def _mock_fpcalc_script(tmp_path: Path) -> Path:
    """A fake fpcalc binary: prints duration + fingerprint lines."""
    script = tmp_path / "fpcalc"
    script.write_text(
        "#!/bin/sh\necho '180.000'\necho 'AQAAABgY'\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_compute_fingerprint_with_mock_binary(tmp_path):
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"audio")
    script = _mock_fpcalc_script(tmp_path)

    result = compute_fingerprint(str(audio), fpcalc_path=str(script))
    assert result.duration_ms == 180000
    assert result.fingerprint == "AQAAABgY"


def test_missing_binary_raises_unavailable(tmp_path):
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"audio")
    with pytest.raises(FpcalcUnavailable):
        compute_fingerprint(str(audio), fpcalc_path=str(tmp_path / "nonexistent"))


def test_fpcalc_available_reflects_which(monkeypatch):
    monkeypatch.setattr(fpcalc.shutil, "which", lambda _: "/usr/bin/fpcalc")
    assert fpcalc_available("/usr/bin/fpcalc") is True
    monkeypatch.setattr(fpcalc.shutil, "which", lambda _: None)
    assert fpcalc_available("missing") is False


def test_failing_binary_raises_error(tmp_path):
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"audio")
    script = tmp_path / "fpcalc"
    script.write_text("#!/bin/sh\necho oops >&2\nexit 1\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    from backend.fingerprint.fpcalc import FpcalcError

    with pytest.raises(FpcalcError):
        compute_fingerprint(str(audio), fpcalc_path=str(script))


def test_acoustid_disabled_without_api_key():
    provider = AcoustIDProvider(api_key="")
    assert provider.enabled() is False
    matches = asyncio.run(provider.search(MetadataQuery(fingerprint="AQAAABgY")))
    assert matches == []


def test_acoustid_lookup_parses_recordings():
    response = {
        "results": [
            {
                "recordings": [
                    {
                        "id": "recording-mbid-1",
                        "title": "Test Song",
                        "duration": 180,
                        "artists": [{"name": "Test Artist"}],
                        "releasegroups": [
                            {"id": "rg-mbid-1", "title": "Test Album"}
                        ],
                    },
                    {
                        "id": "recording-mbid-1",  # duplicate MBID must be deduped
                        "title": "Test Song (dup)",
                    },
                ]
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "fingerprint=AQAAABgY" in str(request.url)
        return httpx.Response(200, json=response)

    provider = AcoustIDProvider(transport=httpx.MockTransport(handler), api_key="test-key")
    assert provider.enabled() is True

    matches = asyncio.run(
        provider.search(MetadataQuery(fingerprint="AQAAABgY", duration_ms=180000))
    )
    assert len(matches) == 1
    match = matches[0]
    assert match.source == "acoustid"
    assert match.recording_mbid == "recording-mbid-1"
    assert match.title == "Test Song"
    assert match.artist == "Test Artist"
    assert match.duration_ms == 180000
    assert match.payload["fingerprint_version"] == "1"


def test_acoustid_no_results():
    provider = AcoustIDProvider(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"results": []})),
        api_key="test-key",
    )
    matches = asyncio.run(provider.search(MetadataQuery(fingerprint="AQAA")))
    assert matches == []