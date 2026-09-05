"""Template engine for organization paths (blueprint §17, TV2-025).

Templates are configurable, never hard-coded. Supported variables (§17):

    {artist} {album_artist} {album} {year} {track} {disc} {title}
    {release_country} {catalog_number} {ext}

Format specs are honoured (``{track:02}`` → ``"04"``). Missing tokens
degrade to empty strings and the render is cleaned up so a half-empty
template never produces stray ``[]``, double separators or dangling dashes.
"""

import re

SUPPORTED_TOKENS = (
    "artist",
    "album_artist",
    "album",
    "year",
    "track",
    "disc",
    "title",
    "release_country",
    "catalog_number",
    "ext",
)

# {token} or {token:spec}
_TOKEN_RE = re.compile(r"\{([a-z_]+)(?::([^{}]*))?\}")


def render_template(template: str, values: dict) -> str:
    """Render a §17 template; missing/None tokens degrade gracefully."""
    rendered = _TOKEN_RE.sub(
        lambda m: _render_token(m.group(1), m.group(2), values), template
    )
    # Cleanup artifacts left by missing tokens (order matters).
    rendered = re.sub(r"\[\s*\]", "", rendered)  # "[]" from missing {year}
    rendered = re.sub(r"(?<=/)\s*-\s+", "", rendered)  # leading " - " from missing {track}
    rendered = re.sub(r"^\s*-\s+", "", rendered)
    rendered = re.sub(r"\s{2,}", " ", rendered)
    rendered = re.sub(r"\s+/", "/", rendered)
    rendered = re.sub(r"/\s+", "/", rendered)
    rendered = re.sub(r"/{2,}", "/", rendered)
    return rendered.strip(" /")


def _render_token(key: str, spec: str | None, values: dict) -> str:
    value = values.get(key)
    if value is None or value == "":
        return ""
    if spec:
        try:
            return format(value, spec)
        except (ValueError, TypeError):
            return str(value)
    return str(value)