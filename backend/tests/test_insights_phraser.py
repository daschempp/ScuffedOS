"""Phraser: one LLM call for all signals, per-code fallback to templates."""
import json

from app import llm
from app.insights import phraser
from app.insights.rules import Signal


def _sig(code="recovery_band", tone="positive"):
    return Signal(code, tone, {"recovery_pct": 72}, "Recovery is green",
                  "Recovery is 72% — you're primed.")


def test_phrase_uses_llm_when_available():
    reply = json.dumps([{"code": "recovery_band", "headline": "Green light",
                         "body": "You're recovered — go earn some strain."}])
    llm.configure(llm_fake := _FakeWithCompletion(reply))
    cards = phraser.phrase([_sig()])
    assert cards[0]["source"] == "llm"
    assert cards[0]["headline"] == "Green light"
    assert cards[0]["tone"] == "positive"          # tone comes from the Signal, not the LLM
    # phraser sent the facts, not raw snapshots
    sent = json.loads(llm_fake.complete_calls[0]["messages"][0]["content"])
    assert sent[0]["facts"] == {"recovery_pct": 72}


def test_phrase_falls_back_to_template_when_llm_off():
    llm.configure(None)                            # disabled
    cards = phraser.phrase([_sig()])
    assert cards[0]["source"] == "rules"
    assert cards[0]["body"] == "Recovery is 72% — you're primed."
    assert cards[0]["headline"] == "Recovery is green"


def test_phrase_partial_llm_output_falls_back_per_code():
    # LLM only returns one of two codes -> the other uses its template
    reply = json.dumps([{"code": "recovery_band", "headline": "Green", "body": "Go."}])
    llm.configure(_FakeWithCompletion(reply))
    cards = phraser.phrase([_sig("recovery_band"), _sig("hrv_trend", "caution")])
    by_code = {c["code"]: c for c in cards}
    assert by_code["recovery_band"]["source"] == "llm"
    assert by_code["hrv_trend"]["source"] == "rules"


def test_empty_signals_returns_empty():
    assert phraser.phrase([]) == []


class _FakeWithCompletion:
    def __init__(self, reply):
        self.completions = [reply]
        self.complete_calls = []

    def complete(self, **kwargs):
        self.complete_calls.append(kwargs)
        return self.completions.pop(0)
