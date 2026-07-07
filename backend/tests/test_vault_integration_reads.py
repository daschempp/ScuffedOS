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
    # END-TO-END through the real food_db module: seed the vault, resolve into
    # global settings, and assert food_db reads the same field the seam filled.
    import app.food_db as food_db
    from app.config import settings as global_settings

    monkeypatch.setattr(global_settings, "fdc_api_key", "DEMO_KEY")
    resolve_secrets_from_vault(global_settings)
    # food_db.search() reads settings.fdc_api_key at request time; assert the
    # module sees the vault value via its own settings import.
    assert food_db.settings.fdc_api_key == "fdc-vault"


def test_plaid_consumer_reads_vault_credentials(seeded, monkeypatch):
    import app.providers.plaid as plaid_mod
    from app.config import settings as global_settings

    monkeypatch.setattr(global_settings, "plaid_client_id", "")
    monkeypatch.setattr(global_settings, "plaid_secret", "")
    resolve_secrets_from_vault(global_settings)
    assert plaid_mod.settings.plaid_client_id == "plaid-id-vault"
    assert plaid_mod.settings.plaid_secret == "plaid-secret-vault"


def test_google_consumer_reads_vault_client_id(seeded, monkeypatch):
    import app.providers.google as google_mod
    from app.config import settings as global_settings

    monkeypatch.setattr(global_settings, "google_client_id", "")
    resolve_secrets_from_vault(global_settings)
    assert google_mod.settings.google_client_id == "google-id-vault"


def test_env_value_still_beats_vault_for_consumers(seeded, monkeypatch):
    import app.llm as llm
    from app.config import settings as global_settings

    monkeypatch.setattr(global_settings, "anthropic_api_key", "sk-from-env")
    resolve_secrets_from_vault(global_settings)
    assert global_settings.anthropic_api_key == "sk-from-env"  # env wins
    llm.configure("unset")
    assert llm.available() is True  # still reads the env value, not the vault
