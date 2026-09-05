from datetime import datetime

from sqlmodel import Field, SQLModel


class ProviderCache(SQLModel, table=True):
    """Cached provider response (blueprint §26)."""

    __tablename__ = "provider_cache"

    id: int | None = Field(default=None, primary_key=True)
    cache_key: str = Field(unique=True, index=True)
    provider: str = Field(index=True)
    payload_json: str
    expires_at: datetime | None = Field(default=None)