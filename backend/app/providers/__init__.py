"""Fitness provider registry + test seam (M4 design §4).

The sync engine and routers go through these four functions only. The seam
mirrors llm.py / memory_engine.py / reminders.py: `_override == "unset"`
uses the real registry; installing an object (a list of fake providers via
`configure([...])`) swaps it wholesale for tests — no network, no settings.

The real registry builds WhoopProvider lazily and caches it; construction is
cheap (the httpx client is itself lazy inside WhoopProvider), so importing
this package never makes a request.
"""
from __future__ import annotations

from .base import FitnessProvider

_override: object | str = "unset"   # "unset" → real registry; list → fakes
_real: list[FitnessProvider] | None = None


def configure(override: object | str = "unset") -> None:
    """Tests install a fake provider list; configure() restores the real registry."""
    global _override
    _override = override


def _build_real() -> list[FitnessProvider]:
    global _real
    if _real is None:
        try:
            from .whoop import WhoopProvider
        except ImportError:
            return []  # WhoopProvider not present yet (mid-plan); empty registry.
        _real = [WhoopProvider()]
    return _real


def all_providers() -> list[FitnessProvider]:
    """Every registered provider (real, or the installed fake list)."""
    if _override != "unset":
        return list(_override)  # type: ignore[arg-type]
    return _build_real()


def get(name: str) -> FitnessProvider | None:
    """A provider by its `name` (e.g. 'whoop'), or None if not registered."""
    for p in all_providers():
        if p.name == name:
            return p
    return None


def pull_providers() -> list[FitnessProvider]:
    """Providers the sync tick may poll (kind == 'pull')."""
    return [p for p in all_providers() if p.kind == "pull"]
