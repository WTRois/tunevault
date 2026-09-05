"""Per-provider token-bucket rate limiting (blueprint §26)."""

import asyncio
import time


class TokenBucket:
    """Classic token bucket: ``acquire`` returns the seconds to wait."""

    def __init__(self, capacity: float, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate  # tokens per second
        self.tokens = capacity
        self.last_refill = time.monotonic()

    def acquire(self, tokens: float = 1.0) -> float:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.last_refill) * self.refill_rate)
        self.last_refill = now
        if self.tokens >= tokens:
            self.tokens -= tokens
            return 0.0
        wait = (tokens - self.tokens) / self.refill_rate
        self.tokens = 0.0
        return wait


# Conservative defaults per provider docs; 1 req/s for MusicBrainz.
PROVIDER_BUCKETS: dict[str, TokenBucket] = {
    "musicbrainz": TokenBucket(capacity=1.0, refill_rate=1.0),
    "acoustid": TokenBucket(capacity=3.0, refill_rate=3.0),
    "coverartarchive": TokenBucket(capacity=1.0, refill_rate=1.0),
    "lrclib": TokenBucket(capacity=2.0, refill_rate=2.0),
}

DEFAULT_BUCKET_CAPACITY = 5.0
DEFAULT_BUCKET_REFILL = 5.0


async def wait_for_slot(provider: str) -> None:
    """Sleep until the provider's bucket has a free slot."""
    bucket = PROVIDER_BUCKETS.get(provider)
    if bucket is None:
        bucket = TokenBucket(DEFAULT_BUCKET_CAPACITY, DEFAULT_BUCKET_REFILL)
        PROVIDER_BUCKETS[provider] = bucket
    wait = bucket.acquire()
    if wait > 0:
        await asyncio.sleep(wait)