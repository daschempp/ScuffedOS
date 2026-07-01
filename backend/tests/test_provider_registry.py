"""The providers registry seam: configure(fake) swaps the registered providers; '"unset"' restores real."""
from datetime import datetime

from app import providers
from app.providers.base import Tokens


class FakePull:
    name = "whoop"
    kind = "pull"

    def authorize_url(self, state): return f"https://fake/auth?state={state}"
    def exchange_code(self, code): return Tokens("a", "r", None)
    def refresh(self, tokens): return tokens
    def fetch_recovery(self, since): return []
    def fetch_sleep(self, since): return []
    def fetch_workouts(self, since): return []
    def revoke(self, tokens): return None


class FakePush:
    name = "apple_health"
    kind = "push"

    def authorize_url(self, state): return ""
    def exchange_code(self, code): return Tokens("a", None, None)
    def refresh(self, tokens): return tokens
    def fetch_recovery(self, since): return []
    def fetch_sleep(self, since): return []
    def fetch_workouts(self, since): return []
    def revoke(self, tokens): return None


def test_configure_installs_a_fake_list():
    providers.configure([FakePull(), FakePush()])
    try:
        names = [p.name for p in providers.all_providers()]
        assert names == ["whoop", "apple_health"]
        assert providers.get("whoop").name == "whoop"
        assert providers.get("nope") is None
        assert [p.name for p in providers.pull_providers()] == ["whoop"]
    finally:
        providers.configure()


def test_configure_restores_the_real_registry():
    import importlib.util
    providers.configure([FakePull()])
    providers.configure()  # back to real
    if importlib.util.find_spec("app.providers.whoop") is None:
        # WhoopProvider not authored yet (earlier in the plan); real registry empty.
        assert providers.get("whoop") is None
        return
    assert providers.get("whoop") is not None
    assert providers.get("whoop").name == "whoop"
    assert "whoop" in [p.name for p in providers.pull_providers()]


def test_empty_fake_list_disables_everything():
    providers.configure([])
    try:
        assert providers.all_providers() == []
        assert providers.pull_providers() == []
        assert providers.get("whoop") is None
    finally:
        providers.configure()


# --- M5 widening tests: registry spans both fitness and email domains ---

class _PullFake:
    name = "whoop"
    kind = "pull"


class _EmailFake:
    name = "google"  # NO kind attribute — an email provider


def test_all_providers_and_get_span_both_domains():
    providers.configure([_PullFake(), _EmailFake()])
    try:
        names = {p.name for p in providers.all_providers()}
        assert names == {"whoop", "google"}
        assert providers.get("google").name == "google"
        assert providers.get("nope") is None
    finally:
        providers.configure("unset")


def test_pull_providers_excludes_kindless_email_provider():
    providers.configure([_PullFake(), _EmailFake()])
    try:
        pulls = providers.pull_providers()
        assert [p.name for p in pulls] == ["whoop"]  # email fake excluded, no crash
    finally:
        providers.configure("unset")
