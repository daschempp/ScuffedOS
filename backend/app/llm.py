"""Anthropic client seam (review D3).

Everything that talks to the Claude API goes through here: client
construction, model routing (cheap/fast tier for chat, escalation for heavy
work), and a single streaming entry point the assistant loop consumes. Tests
swap the whole seam with `configure(fake)`.
"""
from __future__ import annotations

import re

from .config import settings

_client = None
_override = "unset"  # "unset" → real client; None → disabled; object → fake

# Requests that warrant the heavy model: multi-domain synthesis rather than a
# single read/write. Email drafting joins this list in M5.
_HEAVY_PATTERNS = re.compile(r"plan (my|the) day|brief me|draft", re.IGNORECASE)

MAX_TOKENS = 4096


def configure(override="unset") -> None:
    """Tests install a fake here (or None to simulate no API key);
    configure() restores the real client."""
    global _override
    _override = override


def available() -> bool:
    if _override == "unset":
        return bool(settings.anthropic_api_key)
    return _override is not None


def pick_model(message: str) -> str:
    if _HEAVY_PATTERNS.search(message):
        return settings.assistant_heavy_model
    return settings.assistant_model


def stream(*, model: str, system: str, messages: list, tools: list):
    """Return the SDK's streaming context manager for one Messages call."""
    if _override != "unset":
        if _override is None:
            raise RuntimeError("LLM is disabled")
        return _override.stream(model=model, system=system, messages=messages, tools=tools)

    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client.messages.stream(
        model=model,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=messages,
        tools=tools,
    )
