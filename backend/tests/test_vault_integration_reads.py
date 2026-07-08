"""M8 Slice 2: prove the config seam transparently feeds every lazy integration
consumer. llm.py, food_db.py, memory_engine.py, providers/plaid.py and
providers/google.py all read settings.<field> at request time, so filling those
fields from the vault (Task 3) reaches them with ZERO change to those modules.
This test asserts the settings values the consumers read now come from the
vault when the field was empty."""

import pytest

from app import config as cfg
from app.config import resolve_secrets_from_vault
from app.secrets import SecretsVault


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    # Isolate the process-global cached vault (cfg._vault) so it can't leak
    # into/out of this test, mirroring test_config_vault_seam.py's pattern.
    monkeypatch.setattr(cfg, "_vault", None, raising=False)
    v = SecretsVault(tmp_path, machine_id_override="integ-read-test", use_keyring=False)
    v.write_all({
        "ANTHROPIC_API_KEY": "sk-ant-vault",
        "FDC_API_KEY": "fdc-vault",
        "PLAID_CLIENT_ID": "plaid-id-vault",
        "PLAID_SECRET": "plaid-secret-vault",
        "GOOGLE_CLIENT_ID": "google-id-vault",
    })
    monkeypatch.setattr(cfg, "get_vault", lambda: v)
    return v


def test_llm_consumer_reads_vault_anthropic_key(seeded, monkeypatch):
    # END-TO-END: resolve the vault into the GLOBAL settings the consumer reads,
    # then call the real consumer (llm.available()) so a typo in the field name
    # inside llm.py — e.g. settings.anthropic_api_ky — would fail this test.
    import app.llm as llm
    from app.config import settings as global_settings

    monkeypatch.setattr(global_settings, "anthropic_api_key", "")
    resolve_secrets_from_vault(global_settings)
    assert global_settings.anthropic_api_key == "sk-ant-vault"
    # available() returns True iff it read a non-empty settings.anthropic_api_key.
    llm.configure("unset")  # force the real settings-backed code path
    assert llm.available() is True


def test_food_db_consumer_reads_vault_fdc_key(seeded, monkeypatch):
    # END-TO-END through the real food_db.search() request-building code: the
    # configure(fake) seam used elsewhere short-circuits BEFORE the
    # settings.fdc_api_key read (it returns fake.search() directly), so it
    # can't catch a typo at food_db.py:67. Instead leave the module in its
    # real "unset" (network) mode and intercept at the httpx.get() boundary —
    # the actual line that reads settings.fdc_api_key — so a rename there
    # (e.g. fdc_api_key -> fdc_api_ky) raises AttributeError and fails this test.
    import app.food_db as food_db
    from app.config import settings as global_settings

    monkeypatch.setattr(global_settings, "fdc_api_key", "DEMO_KEY")
    resolve_secrets_from_vault(global_settings)
    assert global_settings.fdc_api_key == "fdc-vault"

    captured = {}

    class FakeGetResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"foods": []}

    def fake_get(url, params=None, timeout=None):
        captured["params"] = params
        return FakeGetResponse()

    monkeypatch.setattr("httpx.get", fake_get)
    food_db.configure("unset")  # force the real settings-backed request path
    result = food_db.search("chicken wrap", limit=3)
    assert result == []
    # The real request builder read settings.fdc_api_key and put it on the wire.
    assert captured["params"]["api_key"] == "fdc-vault"


def test_plaid_consumer_reads_vault_credentials(seeded, monkeypatch):
    # END-TO-END through the real PlaidProvider._call() POST-body builder
    # (plaid.py:133): use the same FakePlaidHTTP transport seam the provider's
    # own tests use, drive a real provider method through it, and assert the
    # vault-seeded credentials landed in the POST body the fake transport
    # received — a rename of plaid_client_id/plaid_secret at that line would
    # leave the body's client_id/secret missing or wrong and fail this test.
    import app.providers.plaid as plaid_mod
    from app.config import settings as global_settings
    from tests.fakes import FakePlaidHTTP

    monkeypatch.setattr(global_settings, "plaid_client_id", "")
    monkeypatch.setattr(global_settings, "plaid_secret", "")
    resolve_secrets_from_vault(global_settings)
    assert global_settings.plaid_client_id == "plaid-id-vault"
    assert global_settings.plaid_secret == "plaid-secret-vault"

    http = FakePlaidHTTP(responses={"/link/token/create": {
        "link_token": "link-1", "hosted_link_url": "https://plaid/hl"}})
    p = plaid_mod.PlaidProvider()
    p.configure(fake_http=http)
    p.create_link_token("bank")
    url, body = http.posts[0]
    assert url.endswith("/link/token/create")
    # The real _call() request builder read settings.plaid_client_id/plaid_secret.
    assert body["client_id"] == "plaid-id-vault"
    assert body["secret"] == "plaid-secret-vault"


def test_google_consumer_reads_vault_client_id(seeded, monkeypatch):
    # END-TO-END through the real GoogleProvider.authorize_url() builder
    # (google.py:202) — a pure, no-network URL builder, so we call it
    # directly: a rename of google_client_id at that line would leave
    # client_id out of the URL (or raise AttributeError) and fail this test.
    import app.providers.google as google_mod
    from app.config import settings as global_settings
    from urllib.parse import parse_qs, urlparse

    monkeypatch.setattr(global_settings, "google_client_id", "")
    resolve_secrets_from_vault(global_settings)
    assert global_settings.google_client_id == "google-id-vault"

    p = google_mod.GoogleProvider()
    url = p.authorize_url("state123")
    q = parse_qs(urlparse(url).query)
    assert q["client_id"] == ["google-id-vault"]


def test_env_value_still_beats_vault_for_consumers(seeded, monkeypatch):
    import app.llm as llm
    from app.config import settings as global_settings

    monkeypatch.setattr(global_settings, "anthropic_api_key", "sk-from-env")
    resolve_secrets_from_vault(global_settings)
    assert global_settings.anthropic_api_key == "sk-from-env"  # env wins
    llm.configure("unset")
    assert llm.available() is True  # still reads the env value, not the vault
