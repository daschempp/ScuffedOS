"""Phrase fired rule Signals into warm coaching copy via a single Claude call,
constrained to the facts the rules already verified. Any signal the model
doesn't cleanly return keeps its deterministic template — so the feed always
renders, LLM or not."""
from __future__ import annotations

import json
import logging

from .. import llm
from ..config import settings
from .rules import Signal

log = logging.getLogger("scuffed_os.insights")

_SYSTEM = (
    "You are the Scuffed OS assistant writing a person's daily body-readiness "
    "insight. Voice: warm, calm, direct. Plain text only — no markdown, no emoji, "
    "no headers. One or two short sentences per insight. You receive a JSON list "
    "of insights, each with a code and the exact facts behind it. Use ONLY those "
    "numbers; never invent or infer a value that isn't given. Reply with ONLY a "
    'JSON array, one object per input code, shaped '
    '{"code": <code>, "headline": <=8 words, "body": one or two sentences}.'
)


def _fallback(sig: Signal) -> dict:
    return {"code": sig.code, "tone": sig.tone, "headline": sig.headline,
            "body": sig.template, "source": "rules"}


def phrase(signals: list[Signal]) -> list[dict]:
    """[Signal] -> [{code, tone, headline, body, source}], input order kept."""
    if not signals:
        return []
    by_code = {s.code: s for s in signals}
    phrased: dict[str, dict] = {}
    try:
        payload = [{"code": s.code, "tone": s.tone, "facts": s.facts} for s in signals]
        raw = llm.complete(
            model=settings.assistant_model,
            system=_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload)}],
        )
        for item in json.loads(raw):
            code = item.get("code")
            sig = by_code.get(code)
            if sig and item.get("headline") and item.get("body"):
                phrased[code] = {
                    "code": code, "tone": sig.tone,
                    "headline": str(item["headline"])[:160],
                    "body": str(item["body"]), "source": "llm",
                }
    except Exception as exc:  # noqa: BLE001 — disabled LLM, bad JSON, network: fall back
        log.info("insight phrasing fell back to templates: %s", exc)
    return [phrased.get(s.code) or _fallback(s) for s in signals]
