from .arbeitnow import ArbeitnowSource
from .base import JobRecord, Source, SourceError
from .ddg import DdgSource
from .remoteok import RemoteOkSource
from .remotive import RemotiveSource

REGISTRY: dict[str, Source] = {
    source.name: source
    for source in (DdgSource(), RemoteOkSource(), RemotiveSource(), ArbeitnowSource())
}

DEFAULT_SOURCES = ("ddg",)


def available_sources() -> list[str]:
    return list(REGISTRY)


def get_source(name: str) -> Source:
    key = (name or "").strip().lower()
    if key not in REGISTRY:
        raise SourceError(f"unknown source '{name}'; available: {', '.join(REGISTRY)}")
    return REGISTRY[key]


__all__ = [
    "JobRecord",
    "Source",
    "SourceError",
    "REGISTRY",
    "DEFAULT_SOURCES",
    "available_sources",
    "get_source",
]
