from .arbeitnow import ArbeitnowSource
from .boards import BoardsSource
from .base import JobRecord, Source, SourceError
from .ddg import DdgSource
from .himalayas import HimalayasSource
from .jobicy import JobicySource
from .remoteok import RemoteOkSource
from .remotive import RemotiveSource
from .web import WebSource
from .workingnomads import WorkingNomadsSource

REGISTRY: dict[str, Source] = {
    source.name: source
    for source in (
        DdgSource(),
        RemoteOkSource(),
        RemotiveSource(),
        ArbeitnowSource(),
        HimalayasSource(),
        JobicySource(),
        WorkingNomadsSource(),
        BoardsSource(),
        WebSource(),
    )
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
