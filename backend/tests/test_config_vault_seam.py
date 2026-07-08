"""M8 Slice 2 config seam: the vault fills a secret field ONLY when it is empty,
so env/.env/test values always win and the suite is unaffected. A decrypt
failure is swallowed (logged), never raised, so a foreign/corrupt vault can't
crash startup. Uses a tmp vault via an injected machine id — no ioreg, CI-safe."""

from app import config as cfg
from app.config import Settings
from app.secrets import SecretsVault


def _seed_vault(tmp_path, values, mid="seam-test"):
    v = SecretsVault(tmp_path, machine_id_override=mid, use_keyring=False)
    v.write_all(values)
    return SecretsVault(tmp_path, machine_id_override=mid, use_keyring=False)


def test_empty_field_is_filled_from_vault(tmp_path, monkeypatch):
    vault = _seed_vault(tmp_path, {"ANTHROPIC_API_KEY": "sk-from-vault"})
    monkeypatch.setattr(cfg, "get_vault", lambda: vault)
    s = Settings(anthropic_api_key="")
    cfg.resolve_secrets_from_vault(s)
    assert s.anthropic_api_key == "sk-from-vault"


def test_nonempty_field_is_not_overridden(tmp_path, monkeypatch):
    vault = _seed_vault(tmp_path, {"ANTHROPIC_API_KEY": "sk-from-vault"})
    monkeypatch.setattr(cfg, "get_vault", lambda: vault)
    s = Settings(anthropic_api_key="sk-from-env")
    cfg.resolve_secrets_from_vault(s)
    assert s.anthropic_api_key == "sk-from-env"  # env wins


def test_fdc_demo_key_default_is_overridden(tmp_path, monkeypatch):
    # fdc_api_key ships as "DEMO_KEY"; the seam treats the DEMO_KEY sentinel as
    # "unset" so a real vault key replaces it.
    vault = _seed_vault(tmp_path, {"FDC_API_KEY": "real-fdc-key"})
    monkeypatch.setattr(cfg, "get_vault", lambda: vault)
    s = Settings()  # fdc_api_key == "DEMO_KEY"
    cfg.resolve_secrets_from_vault(s)
    assert s.fdc_api_key == "real-fdc-key"


def test_decrypt_failure_is_swallowed(tmp_path, monkeypatch):
    from app.secrets import VaultDecryptError

    class _Boom:
        def read_all(self):
            raise VaultDecryptError("bad tag")

    monkeypatch.setattr(cfg, "get_vault", lambda: _Boom())
    s = Settings(anthropic_api_key="")
    # Must not raise; field stays empty.
    cfg.resolve_secrets_from_vault(s)
    assert s.anthropic_api_key == ""


def test_map_covers_all_nine_secret_fields():
    assert set(cfg.SECRET_FIELD_MAP.values()) == {
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "FDC_API_KEY",
        "WHOOP_CLIENT_ID", "WHOOP_CLIENT_SECRET",
        "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
        "PLAID_CLIENT_ID", "PLAID_SECRET",
    }


def test_vault_isolation_per_test(tmp_path, monkeypatch):
    # The process-wide vault global (cfg._vault) must not leak a tmp vault from
    # one test into the next. Redirect via get_vault (a function patch, not the
    # global), reset the cached global, and assert a second, differently-seeded
    # vault does not see the first test's data.
    monkeypatch.setattr(cfg, "_vault", None, raising=False)
    vault_a = _seed_vault(tmp_path / "a", {"ANTHROPIC_API_KEY": "sk-a"}, mid="iso-a")
    monkeypatch.setattr(cfg, "get_vault", lambda: vault_a)
    assert cfg.get_vault().read_all() == {"ANTHROPIC_API_KEY": "sk-a"}
    vault_b = _seed_vault(tmp_path / "b", {"OPENAI_API_KEY": "sk-b"}, mid="iso-b")
    monkeypatch.setattr(cfg, "get_vault", lambda: vault_b)
    assert "ANTHROPIC_API_KEY" not in cfg.get_vault().read_all()
