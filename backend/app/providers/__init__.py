"""Provider registry + test seam (M4 §4; widened for M5's email domain).

The sync engines and the shared oauth router go through these four functions
only. The seam mirrors llm.py: `_override == "unset"` uses the real registry;
installing a list of fake providers via `configure([...])` swaps it wholesale
for tests — no network, no settings.

The real registry builds WhoopProvider + GoogleProvider lazily and caches them;
construction is cheap (each provider's httpx client is itself lazy), so
importing this package never makes a request. GoogleProvider is imported inside
a try/except so the registry still works mid-plan before that module lands.
"""
from __future__ import annotations

from .base import FitnessProvider, OAuthProvider

_override: object | str = "unset"   # "unset" → real registry; list → fakes
_real: list[OAuthProvider] | None = None


def configure(override: object | str = "unset") -> None:
    """Tests install a fake provider list; configure() restores the real registry."""
    global _override
    _override = override


def _build_real() -> list[OAuthProvider]:
    global _real
    if _real is None:
        built: list[OAuthProvider] = []
        try:
            from .whoop import WhoopProvider
            built.append(WhoopProvider())
        except ImportError:
            pass  # WhoopProvider not present (shouldn't happen) — skip it.
        try:
            from .google import GoogleProvider
            built.append(GoogleProvider())
        except ImportError:
            pass  # GoogleProvider not present yet (mid-plan) — skip it.
        try:
            from .moodle import MoodleProvider
            built.append(MoodleProvider())
        except ImportError:
            pass  # MoodleProvider not present yet (mid-plan) — skip it.
        try:
            from .plaid import PlaidProvider
            built.append(PlaidProvider())
        except ImportError:
            pass  # PlaidProvider not present yet (mid-plan) — skip it.
        _real = built
    return _real


def all_providers() -> list[OAuthProvider]:
    """Every registered provider (real, or the installed fake list)."""
    if _override != "unset":
        return list(_override)  # type: ignore[arg-type]
    return _build_real()


def get(name: str) -> OAuthProvider | None:
    """A provider by its `name` (e.g. 'whoop', 'google'), or None if absent."""
    for p in all_providers():
        if p.name == name:
            return p
    return None


def pull_providers() -> list[FitnessProvider]:
    """Providers the fitness sync tick may poll (kind == 'pull'). A kind-less
    provider (e.g. GoogleProvider) is naturally excluded."""
    return [p for p in all_providers() if getattr(p, "kind", None) == "pull"]
