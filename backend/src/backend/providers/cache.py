"""Provider response cache: SQLite table keyed per §26.

Every external query flows through :func:`cached_search` — cache first, then
rate limiter, then the network (blueprint §26). Provider calls are logged
with §36 fields (provider, status, duration_ms, error_code).
"""

import hashlib
import json
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlmodel import Session, select

from backend.models.provider_cache import ProviderCache
from backend.providers.base import MetadataProvider, MetadataQuery, ProviderMatch
from backend.providers.rate_limit import wait_for_slot

CACHE_TTL_DAYS = 30


def provider_cache_key(provider: str, kind: str, params: Mapping) -> str:
    """Readable, deterministic key: ``provider:kind:sha256(canonical-json)``."""
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{provider}:{kind}:{digest}"


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def get_cached(session: Session, cache_key: str) -> list[dict] | None:
    """Return fresh cached rows for a key, or None (miss/expired)."""
    row = session.exec(
        select(ProviderCache).where(ProviderCache.cache_key == cache_key)
    ).first()
    if row is None:
        return None
    expires = row.expires_at.replace(tzinfo=UTC) if row.expires_at else None
    if expires is not None and expires <= datetime.now(UTC):
        return None
    return json.loads(row.payload_json)


def put_cached(session: Session, cache_key: str, provider: str, payload: list[dict]) -> None:
    """Insert or refresh a cache entry (payload: list of ProviderMatch dicts)."""
    row = session.exec(
        select(ProviderCache).where(ProviderCache.cache_key == cache_key)
    ).first()
    row = row or ProviderCache(cache_key=cache_key, provider=provider, payload_json="[]")
    row.provider = provider
    row.payload_json = json.dumps(payload, default=str)
    row.expires_at = _now_utc() + timedelta(days=CACHE_TTL_DAYS)
    session.add(row)
    session.commit()


async def cached_search(
    provider: MetadataProvider,
    query: MetadataQuery,
    session: Session,
) -> list[ProviderMatch]:
    """§26 pipeline: cache → rate limiter → provider search → cache fill."""
    cache_key = provider_cache_key(provider.name, "search", query.key_params())

    cached = get_cached(session, cache_key)
    if cached is not None:
        logger.bind(
            operation="provider_search", provider=provider.name, status="cache_hit"
        ).debug(f"Provider search served from cache ({provider.name})")
        return [ProviderMatch.from_dict(item) for item in cached]

    await wait_for_slot(provider.name)
    started = time.perf_counter()
    try:
        matches = await provider.search(query)
    except Exception as err:
        logger.bind(
            operation="provider_search",
            provider=provider.name,
            status="error",
            error_code=type(err).__name__,
            duration_ms=round((time.perf_counter() - started) * 1000),
        ).warning(f"Provider search failed ({provider.name}): {err}")
        raise
    logger.bind(
        operation="provider_search",
        provider=provider.name,
        status="ok",
        count=len(matches),
        duration_ms=round((time.perf_counter() - started) * 1000),
    ).info(f"Provider search completed ({provider.name}): {len(matches)} match(es)")
    put_cached(session, cache_key, provider.name, [m.to_dict() for m in matches])
    return matches


__all__ = [
    "CACHE_TTL_DAYS",
    "cached_search",
    "get_cached",
    "provider_cache_key",
    "put_cached",
]