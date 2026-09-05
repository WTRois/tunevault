"""Tests for the provider layer: cache, rate limit, retry, UA (TV2-012, §25/§26)."""

import asyncio

import httpx
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from backend.core.config import settings
from backend.providers import cache as provider_cache
from backend.providers.base import MetadataQuery, ProviderMatch
from backend.providers.cache import cached_search, provider_cache_key
from backend.providers.http import ProviderHttpError, build_user_agent, get_json, make_client
from backend.providers.rate_limit import PROVIDER_BUCKETS, TokenBucket


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class FakeProvider:
    name = "fake"

    def __init__(self, matches: list[ProviderMatch]):
        self.matches = matches
        self.search_calls = 0

    async def search(self, query: MetadataQuery) -> list[ProviderMatch]:
        self.search_calls += 1
        return self.matches


def test_cached_search_hits_cache_on_second_call(session):
    provider = FakeProvider([ProviderMatch(source="fake", title="Song")])
    query = MetadataQuery(title="Song", artist="Artist")

    first = asyncio.run(cached_search(provider, query, session))
    assert len(first) == 1
    assert provider.search_calls == 1

    # Second identical query must be served from cache — no new provider call.
    second = asyncio.run(cached_search(provider, query, session))
    assert provider.search_calls == 1
    assert second[0].title == "Song"


def test_cache_key_changes_with_query(session):
    provider = FakeProvider([])
    asyncio.run(cached_search(provider, MetadataQuery(title="A"), session))
    asyncio.run(cached_search(provider, MetadataQuery(title="B"), session))
    assert provider.search_calls == 2

    key_a = provider_cache_key("fake", "search", MetadataQuery(title="A").key_params())
    key_b = provider_cache_key("fake", "search", MetadataQuery(title="B").key_params())
    assert key_a != key_b


def test_expired_cache_entry_is_a_miss(session):
    from datetime import UTC, datetime, timedelta

    from sqlmodel import select

    from backend.models import ProviderCache

    key = provider_cache_key("fake", "search", {"x": 1})
    provider_cache.put_cached(session, key, "fake", [{"source": "fake"}])
    row = session.exec(
        select(ProviderCache).where(ProviderCache.cache_key == key)
    ).one()
    row.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
    session.add(row)
    session.commit()

    assert provider_cache.get_cached(session, key) is None


def test_token_bucket_rate_limited():
    bucket = TokenBucket(capacity=1.0, refill_rate=1.0)
    assert bucket.acquire() == 0.0
    # Bucket empty — second acquire must wait ~1s for refill.
    wait = bucket.acquire()
    assert 0.0 < wait <= 1.0


def test_wait_for_slot_sleeps_when_bucket_empty(monkeypatch):
    from backend.providers import rate_limit

    bucket = TokenBucket(capacity=1.0, refill_rate=1.0)
    monkeypatch.setitem(PROVIDER_BUCKETS, "fake", bucket)

    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(rate_limit.asyncio, "sleep", fake_sleep)

    asyncio.run(rate_limit.wait_for_slot("fake"))  # consumes the only token
    asyncio.run(rate_limit.wait_for_slot("fake"))  # must sleep for refill
    assert len(sleeps) == 1
    assert sleeps[0] > 0


def test_user_agent_includes_contact_email():
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "PROVIDER_CONTACT_EMAIL", "user@example.com")
        ua = build_user_agent()
    assert settings.PROJECT_NAME in ua
    assert "user@example.com" in ua


def test_user_agent_without_email_still_valid():
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "PROVIDER_CONTACT_EMAIL", None)
        ua = build_user_agent()
    assert "@" not in ua


def test_get_json_retries_on_429_then_succeeds():
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)

    async def run():
        async with make_client(transport=transport) as client:
            return await get_json(client, "https://provider.test/test")

    result = asyncio.run(run())
    assert result == {"ok": True}
    assert attempts["count"] == 2


def test_get_json_fails_after_max_retries():
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(503)

    transport = httpx.MockTransport(handler)

    async def run():
        async with make_client(transport=transport) as client:
            await get_json(client, "https://provider.test/test")

    with pytest.raises(ProviderHttpError):
        asyncio.run(run())
    assert attempts["count"] == 3