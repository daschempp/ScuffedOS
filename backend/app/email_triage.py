"""Email triage (M5) — one Claude (Haiku) call per synced message.

Input: subject + sender + snippet + a bounded ~2 KB plain-text body excerpt
(the excerpt transits Gmail -> server -> Anthropic and is NEVER persisted).
Output: (category, summary) where category is 'needs_reply' | 'fyi' (or None on
failure) and summary is a list of <=3 short bullet strings (or None on failure).

Seam mirrors llm.py / food_db.py: configure(fake) installs an object exposing
.triage(...); configure(None) disables triage (always returns (None, None));
configure("unset") uses the real Claude client via app/llm.py. A model/offline
failure returns (None, None) — the caller keeps the message untriaged (it still
shows) and re-triages on the next sync. This function never raises.
"""
from __future__ import annotations

import json
import logging
import re

from . import llm
from .config import settings

log = logging.getLogger("scuffed_os.email_triage")

_override: object | None | str = "unset"

_CATEGORIES = ("needs_reply", "fyi")
_MAX_BULLETS = 3

_SYSTEM = (
    "You triage a single email for a busy person's inbox. Decide whether it "
    "NEEDS A REPLY from the user or is just FYI (no reply needed), and write at "
    "most three very short summary bullets (each a terse phrase, not a sentence). "
    "Respond with ONLY a JSON object, no prose, of the exact form: "
    '{\"category\": \"needs_reply\"|\"fyi\", \"summary\": [\"bullet\", ...]}.'
)

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def configure(override: object | None | str = "unset") -> None:
    """Tests install a fake with .triage(...); None disables; 'unset' uses real."""
    global _override
    _override = override


def _build_prompt(subject: str, from_name: str, from_email: str,
                  snippet: str, body_excerpt: str) -> str:
    sender = f"{from_name} <{from_email}>".strip()
    return (
        f"From: {sender}\n"
        f"Subject: {subject}\n"
        f"Preview: {snippet}\n"
        f"Body:\n{body_excerpt}"
    )


def _clamp(payload: dict) -> tuple[str | None, list[str] | None]:
    """Validate the model's JSON: category to the two-value enum (else None),
    summary to <=3 non-empty string bullets (else None)."""
    raw_cat = payload.get("category")
    category = raw_cat if raw_cat in _CATEGORIES else None
    raw_summary = payload.get("summary")
    summary: list[str] | None = None
    if isinstance(raw_summary, list):
        bullets = [str(b).strip() for b in raw_summary if str(b).strip()]
        summary = bullets[:_MAX_BULLETS] if bullets else None
    return category, summary


def _extract(text: str) -> tuple[str | None, list[str] | None]:
    match = _JSON_OBJECT.search(text or "")
    if not match:
        return None, None
    try:
        payload = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None, None
    if not isinstance(payload, dict):
        return None, None
    return _clamp(payload)


def _final_text(prompt: str) -> str:
    """One Haiku call via the shared llm seam; return the assistant's text.
    Reads the streaming context the same way the assistant loop does."""
    with llm.stream(
        model=settings.assistant_model,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        tools=[],
    ) as stream:
        for _ in stream.text_stream:
            pass
        message = stream.get_final_message()
    parts = [b.text for b in message.content if getattr(b, "type", None) == "text"]
    return "".join(parts)


def triage(subject: str, from_name: str, from_email: str,
           snippet: str, body_excerpt: str) -> tuple[str | None, list[str] | None]:
    """Return (category, summary). Any failure/offline -> (None, None). Never raises."""
    if _override is None:
        return None, None
    if _override != "unset":
        try:
            return _override.triage(subject, from_name, from_email, snippet, body_excerpt)
        except Exception:
            log.exception("fake triage raised; leaving untriaged")
            return None, None
    if not llm.available():
        return None, None
    try:
        text = _final_text(
            _build_prompt(subject, from_name, from_email, snippet, body_excerpt)
        )
        return _extract(text)
    except Exception:
        log.exception("triage call failed; leaving message untriaged")
        return None, None
