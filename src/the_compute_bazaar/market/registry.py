"""Canonical registry of scheduled market sources."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping

from .pipeline import MarketSource
from .sources.sesterce import SesterceSource


SourceFactory = Callable[[Mapping[str, str]], MarketSource]


class MarketSourceRegistry:
    def __init__(self, sources: Mapping[str, SourceFactory]) -> None:
        self._sources = dict(sources)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._sources))

    def build(
        self, name: str, *, environment: Mapping[str, str] | None = None
    ) -> MarketSource:
        try:
            factory = self._sources[name]
        except KeyError as exc:
            raise KeyError(f"Unknown market source: {name}") from exc
        return factory(environment or os.environ)


default_registry = MarketSourceRegistry(
    {
        "sesterce": lambda env: SesterceSource(env.get("SESTERCE_API_KEY", "")),
    }
)
