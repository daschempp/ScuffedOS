"""The one-shot llm.complete() seam used by non-conversational callers."""
import pytest

from app import llm
from .fakes import FakeLLM


def test_complete_returns_text_and_records_call():
    fake = FakeLLM(completions=["primed and ready"])
    llm.configure(fake)
    out = llm.complete(model="m", system="s", messages=[{"role": "user", "content": "x"}])
    assert out == "primed and ready"
    assert fake.complete_calls[0]["model"] == "m"


def test_complete_disabled_raises():
    llm.configure(None)
    with pytest.raises(RuntimeError):
        llm.complete(model="m", system="s", messages=[])
