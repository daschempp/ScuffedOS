"""AI email drafting (M5 slice-2) — one Claude call per user-initiated draft
request. NEVER runs automatically: only `POST /api/email/draft` (the compose
editor's AI-draft button) and the assistant's `draft_email` tool call this.

Input: user instructions + whatever the user has already typed (notes) +, for
reply/forward, the original message's sender/subject/a bounded ~2KB
body_excerpt (fetched live by the router — transits, never persisted, same
posture as email_triage). Output: a plain-text email body (no subject line,
no signature placeholders) or None on any failure/offline. Drafts are never
persisted server-side.

Seam mirrors email_triage.py: configure(fake) installs an object exposing
.draft(...); configure(None) disables drafting (always returns None);
configure("unset") uses the real Claude client via app/llm.py. This function
never raises.
"""
from __future__ import annotations

import logging

from . import llm
from .config import settings

log = logging.getLogger("scuffed_os.email_draft")

_override: object | None | str = "unset"

_SYSTEM = (
    "You draft a single email body for a busy person, at their request. "
    "Write ONLY the plain-text body of the email — no subject line, no "
    "greeting-less filler, no signature placeholder (e.g. no '[Your Name]'). "
    "Follow the user's instructions exactly. If the user has already typed "
    "notes, treat them as raw material to turn into a proper email, not as "
    "a suggestion to ignore. If this is a reply or forward, use the original "
    "message's sender, subject, and body excerpt as context so the draft "
    "makes sense in that thread. Respond with ONLY the email body text — no "
    "prose about what you did, no markdown fences, no quotation marks around it."
)


def configure(override: object | None | str = "unset") -> None:
    """Tests install a fake with .draft(...); None disables; 'unset' uses real."""
    global _override
    _override = override


def _build_prompt(instructions: str, notes: str, mode: str, original: dict | None) -> str:
    lines = [f"Mode: {mode}", f"Instructions: {instructions}"]
    if notes:
        lines.append(f"Notes already typed (raw material, not a final draft):\n{notes}")
    if original is not None:
        sender = f"{original.get('from_name', '')} <{original.get('from_email', '')}>".strip()
        lines.append(
            f"Original message being {('replied to' if mode == 'reply' else 'forwarded')}:\n"
            f"From: {sender}\n"
            f"Subject: {original.get('subject', '')}\n"
            f"Body:\n{original.get('body_excerpt', '')}"
        )
    return "\n\n".join(lines)


def _final_text(prompt: str) -> str:
    """One Claude call via the shared llm seam; return the assistant's text.
    Reads the streaming context the same way email_triage._final_text does."""
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


def draft(instructions: str, notes: str, mode: str, original: dict | None) -> str | None:
    """Return the drafted plain-text body, or None on any failure/offline.
    Never raises. NEVER called except from the draft endpoint/tool."""
    if _override is None:
        return None
    if _override != "unset":
        try:
            return _override.draft(instructions, notes, mode, original)
        except Exception:
            log.exception("fake draft raised; returning None")
            return None
    if not llm.available():
        return None
    try:
        text = _final_text(_build_prompt(instructions, notes, mode, original))
        text = text.strip()
        return text or None
    except Exception:
        log.exception("draft call failed")
        return None
