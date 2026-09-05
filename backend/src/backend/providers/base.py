"""Provider protocol and shared data types (blueprint §25)."""

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class MetadataQuery:
    """Normalized identification query sent to providers."""

    title: str | None = None
    artist: str | None = None
    release_title: str | None = None
    duration_ms: int | None = None
    fingerprint: str | None = None
    limit: int = 5

    def key_params(self) -> dict[str, Any]:
        """Deterministic parameters used for cache keys (§26)."""
        return {
            "title": self.title,
            "artist": self.artist,
            "release_title": self.release_title,
            "duration_ms": self.duration_ms,
            "fingerprint": self.fingerprint,
            "limit": self.limit,
        }


@dataclass(slots=True)
class ProviderMatch:
    """One normalized search result from a provider."""

    source: str
    title: str | None = None
    artist: str | None = None
    release_title: str | None = None
    track_number: int | None = None
    duration_ms: int | None = None
    recording_mbid: str | None = None
    release_mbid: str | None = None
    release_group_mbid: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProviderMatch":
        return cls(**data)


@runtime_checkable
class MetadataProvider(Protocol):
    """Interface every external metadata provider implements (§25)."""

    name: str

    async def search(self, query: MetadataQuery) -> list[ProviderMatch]: ...