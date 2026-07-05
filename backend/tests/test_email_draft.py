"""email_draft (M5 slice-2): AI-drafted email body via the shared llm seam;
user-initiated only; never raises."""
from app import email_draft, llm

from .fakes import FakeLLM, text_turn


class _FakeDraft:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def draft(self, instructions, notes, mode, original):
        self.calls.append((instructions, notes, mode, original))
        return self.result


def test_configure_none_returns_none():
    email_draft.configure(None)
    assert email_draft.draft("write it", "", "new", None) is None


def test_fake_object_seam_is_delegated_to():
    fake = _FakeDraft("Hi Priya, confirming the 30th works for me.")
    email_draft.configure(fake)
    text = email_draft.draft("confirm the date", "typed notes", "reply",
                             {"from_name": "Priya", "from_email": "priya@x.io",
                              "subject": "Re: date", "body_excerpt": "Does the 30th work?"})
    assert text == "Hi Priya, confirming the 30th works for me."
    assert fake.calls == [("confirm the date", "typed notes", "reply",
                           {"from_name": "Priya", "from_email": "priya@x.io",
                            "subject": "Re: date", "body_excerpt": "Does the 30th work?"})]


def test_real_path_returns_stripped_llm_text():
    llm.configure(FakeLLM(text_turn("  Hi Priya,\n\nConfirming the 30th works.\n  ")))
    email_draft.configure("unset")
    text = email_draft.draft("confirm the date", "", "reply",
                             {"from_name": "Priya", "from_email": "priya@x.io",
                              "subject": "Re: date", "body_excerpt": "Does the 30th work?"})
    assert text == "Hi Priya,\n\nConfirming the 30th works."


def test_real_path_new_mode_with_no_original():
    llm.configure(FakeLLM(text_turn("Hey team, quick update on the launch.")))
    email_draft.configure("unset")
    text = email_draft.draft("write an update to the team", "launch is on track", "new", None)
    assert text == "Hey team, quick update on the launch."


def test_offline_llm_returns_none_without_raising():
    llm.configure(None)
    email_draft.configure("unset")
    assert email_draft.draft("write it", "", "new", None) is None


def test_fake_raising_returns_none_without_raising():
    class _Raises:
        def draft(self, *a, **k):
            raise RuntimeError("boom")

    email_draft.configure(_Raises())
    assert email_draft.draft("write it", "", "new", None) is None
