"""email_triage (M5): category + summary via the shared llm seam; never raises."""
from app import email_triage, llm

from .fakes import FakeLLM, text_turn


class _FakeTriage:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def triage(self, subject, from_name, from_email, snippet, body_excerpt):
        self.calls.append((subject, from_name, from_email, snippet, body_excerpt))
        return self.result


def test_configure_none_returns_none_pair():
    email_triage.configure(None)
    assert email_triage.triage("s", "n", "e@x", "snip", "body") == (None, None)


def test_fake_object_seam_is_delegated_to():
    fake = _FakeTriage(("needs_reply", ["Reply about the 30th"]))
    email_triage.configure(fake)
    cat, summary = email_triage.triage("Re: deadline", "Priya", "p@x", "snip", "body")
    assert cat == "needs_reply" and summary == ["Reply about the 30th"]
    assert fake.calls == [("Re: deadline", "Priya", "p@x", "snip", "body")]


def test_real_path_parses_category_and_summary_from_llm_json():
    llm.configure(FakeLLM(text_turn(
        '{"category": "needs_reply", '
        '"summary": ["Confirm the 30th works", "Loop in design review"]}'
    )))
    email_triage.configure("unset")
    cat, summary = email_triage.triage(
        "Re: moved deadline", "Priya Rao", "priya@x.io",
        "Does the 30th still work?", "Hi confirming the 30th ...",
    )
    assert cat == "needs_reply"
    assert summary == ["Confirm the 30th works", "Loop in design review"]


def test_real_path_recovers_json_from_code_fence_and_preamble():
    # The model often wraps JSON in prose and/or a ```json fence. The extractor
    # must still recover the object (spec §11/§5: triage output validated).
    llm.configure(FakeLLM(text_turn(
        "Here you go:\n"
        "```json\n"
        '{"category": "fyi", "summary": ["Newsletter digest", "No action needed"]}\n'
        "```\n"
        "Let me know if you need anything else."
    )))
    email_triage.configure("unset")
    cat, summary = email_triage.triage("Weekly digest", "News", "news@x.io", "snip", "body")
    assert cat == "fyi"
    assert summary == ["Newsletter digest", "No action needed"]


def test_real_path_clamps_unknown_category_to_none():
    llm.configure(FakeLLM(text_turn('{"category": "spam", "summary": ["x"]}')))
    email_triage.configure("unset")
    cat, summary = email_triage.triage("s", "n", "e@x", "snip", "body")
    assert cat is None  # not in the two-value enum
    assert summary == ["x"]


def test_real_path_truncates_summary_to_three_bullets():
    llm.configure(FakeLLM(text_turn(
        '{"category": "fyi", "summary": ["a", "b", "c", "d", "e"]}'
    )))
    email_triage.configure("unset")
    _, summary = email_triage.triage("s", "n", "e@x", "snip", "body")
    assert summary == ["a", "b", "c"]


def test_real_path_bad_json_returns_none_pair():
    llm.configure(FakeLLM(text_turn("sorry, I cannot help with that")))
    email_triage.configure("unset")
    assert email_triage.triage("s", "n", "e@x", "snip", "body") == (None, None)


def test_offline_llm_returns_none_pair_without_raising():
    # llm.configure(None) -> llm.available() is False; triage must not raise.
    llm.configure(None)
    email_triage.configure("unset")
    assert email_triage.triage("s", "n", "e@x", "snip", "body") == (None, None)
