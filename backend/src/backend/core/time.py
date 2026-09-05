from datetime import UTC, datetime


def now_utc() -> datetime:
    """Timezone-aware current UTC timestamp (blueprint §29 — never naive ``utcnow``)."""
    return datetime.now(UTC)