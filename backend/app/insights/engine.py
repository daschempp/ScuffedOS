"""Insight generation orchestrator. Reads the day's snapshot window, runs the
rules, phrases the fired signals, and caches one insight row per signal. Reads
never call this — only the fitness sync hook and POST /api/insights/refresh do."""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime

from ..store import store
from . import phraser
from . import rules as rules_mod

log = logging.getLogger("scuffed_os.insights")

DOMAIN = "fitness"
BASELINE_DAYS = 7
_AUTO_GENERATION_LOCK = threading.Lock()


def _today() -> date:
    return datetime.now().astimezone().date()   # matches store._local_today


def generate_for_day(day: date) -> int:
    """Force-(re)generate the day's fitness insights. Returns cards written."""
    window = store.list_snapshots(day, BASELINE_DAYS)
    today = next((s for s in window if s["day"] == day), None)
    history = [s for s in window if s["day"] != day]
    signals = rules_mod.run_rules(rules_mod.Ctx(day=day, today=today, history=history))
    facts_by_code = {s.code: s.facts for s in signals}
    cards = phraser.phrase(signals)
    fired_codes = set()
    for c in cards:
        store.upsert_insight(
            day=day, domain=DOMAIN, code=c["code"], tone=c["tone"],
            headline=c["headline"], body=c["body"],
            signals=facts_by_code.get(c["code"], {}), source=c["source"],
        )
        fired_codes.add(c["code"])
    store.prune_insights(day, DOMAIN, fired_codes)
    return len(cards)


def maybe_generate_today() -> int:
    """Gated generation for the sync hook: only when today's recovery is scored
    and no recovery anchor exists yet for today. A pre-recovery manual refresh
    may have cached other cards, but must not suppress the anchored daily read.
    Concurrent sync ticks in this backend process are serialized so they cannot
    both clear the gate and duplicate the day's LLM call. Returns cards written
    (0 if skipped)."""
    with _AUTO_GENERATION_LOCK:
        day = _today()
        if store.has_insight(day, DOMAIN, "recovery_band"):
            return 0
        window = store.list_snapshots(day, 0)          # today only
        today = next((s for s in window if s["day"] == day), None)
        if not today or today.get("recovery_pct") is None:
            return 0                                    # wait for recovery to score
        return generate_for_day(day)
