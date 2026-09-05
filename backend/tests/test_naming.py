"""Naming + template tests (TV2-025, blueprint §17)."""


from backend.organization.naming import build_target_path, resolve_collision, sanitize_component
from backend.organization.template import render_template

# ---------- template engine (§17) ----------


def test_render_default_tokens():
    rendered = render_template(
        "{album_artist}/[{year}] {album}/{track:02} - {title}.{ext}",
        {
            "album_artist": "Pink Floyd",
            "year": 1973,
            "album": "The Dark Side of the Moon",
            "track": 4,
            "title": "Time",
            "ext": "flac",
        },
    )
    assert rendered == "Pink Floyd/[1973] The Dark Side of the Moon/04 - Time.flac"


def test_render_missing_year_drops_brackets():
    rendered = render_template(
        "{album_artist}/[{year}] {album}/{track:02} - {title}.{ext}",
        {"album_artist": "Artist", "album": "Album", "track": 1, "title": "T", "ext": "mp3"},
    )
    assert rendered == "Artist/Album/01 - T.mp3"


def test_render_missing_track_drops_dash():
    rendered = render_template(
        "{album_artist}/{album}/{track:02} - {title}.{ext}",
        {"album_artist": "Artist", "album": "Album", "title": "T", "ext": "mp3"},
    )
    assert rendered == "Artist/Album/T.mp3"


def test_render_all_optional_tokens_empty():
    rendered = render_template("{artist}/{album}/{title}.{ext}", {"ext": "mp3"})
    # No stray separators from the empty tokens.
    assert rendered.endswith(".mp3")
    assert rendered.count("//") == 0
    assert not rendered.startswith("/")


def test_render_custom_template_with_all_variables():
    rendered = render_template(
        "{artist} - {album_artist} - {album} - {release_country} - {catalog_number}",
        {
            "artist": "A",
            "album_artist": "B",
            "album": "C",
            "release_country": "JP",
            "catalog_number": "123",
        },
    )
    assert rendered == "A - B - C - JP - 123"


def test_render_format_spec_applied():
    assert render_template("{track:03}", {"track": 4}) == "004"
    assert render_template("{track:02}", {}) == ""


# ---------- filename safety (§17) ----------


def test_sanitize_long_name_is_truncated():
    component = "x" * 500
    assert len(sanitize_component(component)) == 180


def test_sanitize_illegal_and_control_characters():
    assert sanitize_component('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"
    assert sanitize_component("bad\x00\x1fname") == "bad__name"


def test_sanitize_windows_reserved_names():
    assert sanitize_component("con") == "Unknown"
    assert sanitize_component("COM1.bak") == "Unknown"
    assert sanitize_component("console") == "console"  # only exact reserved names


def test_sanitize_trailing_dots_and_spaces():
    assert sanitize_component("name... ") == "name"


# ---------- build_target_path (§17 layout) ----------


def test_build_target_uses_default_template():
    path = build_target_path(
        album_artist="Pink Floyd",
        year=1973,
        album="The Dark Side of the Moon",
        track=4,
        title="Time",
        disc=1,
        ext=".flac",
    )
    assert path == "Pink Floyd/[1973] The Dark Side of the Moon/04 - Time.flac"


def test_build_target_multi_disc_layout():
    path = build_target_path(
        album_artist="Artist",
        year=2000,
        album="Album",
        track=1,
        title="Title",
        disc=2,
        ext=".mp3",
    )
    assert path == "Artist/[2000] Album/CD2/01 - Title.mp3"


def test_build_target_degrades_when_metadata_missing():
    path = build_target_path(
        album_artist=None, year=None, album=None, track=None, title=None, disc=None, ext=".flac"
    )
    # Missing metadata falls back per component: Unknown artist / Unknown album / bare title.
    assert path == "Unknown/Unknown/Unknown Title.flac"


def test_build_target_sanitizes_components():
    path = build_target_path(
        album_artist='AC/DC',
        year=1980,
        album="Back In Black?",
        track=1,
        title="Hells Bells",
        disc=1,
        ext=".mp3",
    )
    assert path == "AC_DC/[1980] Back In Black_/01 - Hells Bells.mp3"


def test_build_target_honours_configured_template(monkeypatch):
    from backend.core.config import settings

    monkeypatch.setattr(
        settings, "ORGANIZATION_TEMPLATE", "{artist}/{album} ({year})/{title}.{ext}"
    )
    path = build_target_path(
        album_artist="AA", artist="The Artist", year=2020, album="Album",
        track=9, title="Song", disc=1, ext=".mp3",
    )
    assert path == "The Artist/Album (2020)/Song.mp3"


# ---------- collision policy (§17) ----------


def test_resolve_collision_free_target(tmp_path):
    target = str(tmp_path / "free.flac")
    path, status = resolve_collision(target, "sha", lambda p: None)
    assert (path, status) == (target, "ok")


def test_resolve_collision_same_sha_is_duplicate(tmp_path):
    target = tmp_path / "song.flac"
    target.write_bytes(b"content")
    path, status = resolve_collision(str(target), "sha-of-content", lambda p: "sha-of-content")
    assert (path, status) == (str(target), "duplicate")


def test_resolve_collision_different_content_gets_suffix(tmp_path):
    target = tmp_path / "song.flac"
    target.write_bytes(b"existing different")
    path, status = resolve_collision(str(target), "sha-of-new", lambda p: "other-sha")
    assert status == "suffixed"
    assert path == str(tmp_path / "song (2).flac")


def test_resolve_collision_suffix_chain(tmp_path):
    (tmp_path / "song.flac").write_bytes(b"a")
    (tmp_path / "song (2).flac").write_bytes(b"b")
    path, status = resolve_collision(str(tmp_path / "song.flac"), "sha-new", lambda p: "x")
    assert status == "suffixed"
    assert path.endswith("song (3).flac")


def test_resolve_collision_duplicate_found_in_suffix_chain(tmp_path):
    (tmp_path / "song.flac").write_bytes(b"a")
    (tmp_path / "song (2).flac").write_bytes(b"the-new-content")
    target = str(tmp_path / "song.flac")
    path, status = resolve_collision(
        target, "sha-new", lambda p: "sha-new" if "(2)" in p else "other"
    )
    assert (path, status) == (str(tmp_path / "song (2).flac"), "duplicate")


def test_resolve_collision_never_overwrites(tmp_path):
    """Acceptance: same name → suffix; the existing file is untouched."""
    target = tmp_path / "song.flac"
    original_bytes = b"original bytes"
    target.write_bytes(original_bytes)
    _path, status = resolve_collision(str(target), "different-sha", lambda p: "whatever")
    assert status == "suffixed"
    assert target.read_bytes() == original_bytes