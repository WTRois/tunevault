"""Shared provider HTTP client: User-Agent + retry/backoff (blueprint §24, §26)."""

import asyncio
from typing import Any

import httpx

from backend.core.config import settings

DEFAULT_TIMEOUT_SECONDS = 15.0
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 0.5

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ProviderHttpError(RuntimeError):
    """Provider request failed after retries."""

    def __init__(self, message: str, cause: Exception | None = None):
        super().__init__(message)
        self.cause = cause


def build_user_agent() -> str:
    """User-Agent per MusicBrainz requirements — never a generic one.

    ``MUSICBRAINZ_USER_AGENT`` (§38) overrides the whole string; otherwise
    it is built from PROJECT_NAME/VERSION plus the contact email.
    """
    if settings.MUSICBRAINZ_USER_AGENT:
        return settings.MUSICBRAINZ_USER_AGENT
    ua = f"{settings.PROJECT_NAME}/{settings.VERSION}"
    if settings.PROVIDER_CONTACT_EMAIL:
        ua += f" ( https://github.com/WTRois/tunevault ; {settings.PROVIDER_CONTACT_EMAIL} )"
    return ua


def make_client(
    *, base_url: str = "", transport: httpx.AsyncBaseTransport | None = None
) -> httpx.AsyncClient:
    """Async client with the shared provider UA (tests may inject a MockTransport)."""
    return httpx.AsyncClient(
        base_url=base_url,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        headers={"User-Agent": build_user_agent()},
        transport=transport,
        follow_redirects=True,
    )


async def get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict | None = None,
) -> Any:
    """GET JSON with retry/backoff: transport errors, 429 and 5xx are retried (§24)."""
    last_error: Exception | None = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            response = await client.get(url, params=params)
            if response.status_code in RETRYABLE_STATUS_CODES:
                last_error = httpx.HTTPStatusError(
                    f"HTTP {response.status_code} for {url}",
                    request=response.request,
                    response=response,
                )
            else:
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as err:
            last_error = err
        except httpx.TransportError as err:
            last_error = err

        if attempt < RETRY_ATTEMPTS:
            await asyncio.sleep(RETRY_BASE_DELAY_SECONDS * 2 ** (attempt - 1))

    raise ProviderHttpError(f"Request to {url} failed after {RETRY_ATTEMPTS} attempts", last_error)