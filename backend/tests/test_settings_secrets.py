"""M8 Slice 2 Settings API: GET returns masked presence only (never raw
values); PUT writes into the machine-bound vault and never echoes secrets. The
vault is redirected to a tmp dir via the config get_vault seam so no real
~/Library path is touched and it round-trips on CI."""

import pytest

from app import config as cfg
from app.secrets import SecretsVault


@pytest.fixture
def tmp_vault(tmp_path, monkeypatch):
    v = SecretsVault(tmp_path, machine_id_override="settings-api-test", use_keyring=False)
    monkeypatch.setattr(cfg, "get_vault", lambda: v)
    return v


def test_get_secrets_empty_presence(client, tmp_vault):
    res = client.get("/api/settings/secrets")
    assert res.status_code == 200
    body = res.json()
    assert body["vault_ok"] is True
    anth = body["integrations"]["anthropic"]
    keys = {k["key"]: k["present"] for k in anth["keys"]}
    assert keys["ANTHROPIC_API_KEY"] is False


def test_put_secret_then_present_true(client, tmp_vault):
    res = client.put("/api/settings/secrets",
                     json={"values": {"ANTHROPIC_API_KEY": "sk-ant-xyz"}})
    assert res.status_code == 200
    body = res.json()
    keys = {k["key"]: k["present"] for k in body["integrations"]["anthropic"]["keys"]}
    assert keys["ANTHROPIC_API_KEY"] is True
    # And it persisted to the vault (still never echoed as a raw value).
    assert tmp_vault.get("ANTHROPIC_API_KEY") == "sk-ant-xyz"


def test_get_never_returns_raw_values(client, tmp_vault):
    tmp_vault.set("PLAID_SECRET", "super-secret-value")
    res = client.get("/api/settings/secrets")
    assert "super-secret-value" not in res.text


def test_put_rejects_unknown_key(client, tmp_vault):
    res = client.put("/api/settings/secrets",
                     json={"values": {"NOT_A_REAL_KEY": "x"}})
    # Assert only the HTTP status; the error-envelope shape is version/
    # middleware-dependent and would make this test brittle.
    assert res.status_code == 422


def test_put_empty_value_blanks_presence(client, tmp_vault):
    tmp_vault.set("OPENAI_API_KEY", "sk-oai")
    res = client.put("/api/settings/secrets",
                     json={"values": {"OPENAI_API_KEY": ""}})
    assert res.status_code == 200
    keys = {k["key"]: k["present"] for k in res.json()["integrations"]["openai"]["keys"]}
    assert keys["OPENAI_API_KEY"] is False


def test_put_updates_running_settings(client, tmp_vault):
    from app.config import settings
    settings.anthropic_api_key = ""
    client.put("/api/settings/secrets", json={"values": {"ANTHROPIC_API_KEY": "sk-live"}})
    assert settings.anthropic_api_key == "sk-live"


def test_get_reports_vault_not_ok_on_decrypt_failure(client, tmp_path, monkeypatch):
    from app.secrets import VaultDecryptError

    class _Boom:
        def present(self):
            raise VaultDecryptError("bad tag")
        def read_all(self):
            raise VaultDecryptError("bad tag")

    monkeypatch.setattr(cfg, "get_vault", lambda: _Boom())
    res = client.get("/api/settings/secrets")
    assert res.status_code == 200
    assert res.json()["vault_ok"] is False


def test_put_decrypt_failure_is_422(client, tmp_path, monkeypatch):
    # A foreign/corrupt vault (machine changed) is a client-recoverable state,
    # surfaced as 422 (re-authenticate), not a blanket 503.
    from app.secrets import VaultDecryptError

    class _Boom:
        def update(self, patch):
            raise VaultDecryptError("bad tag")

    monkeypatch.setattr(cfg, "get_vault", lambda: _Boom())
    res = client.put("/api/settings/secrets",
                     json={"values": {"ANTHROPIC_API_KEY": "sk"}})
    assert res.status_code == 422


def test_put_revalidates_vault_write(client, tmp_path, monkeypatch):
    # update() reports success but the value never persisted (read_all returns
    # stale data) -> the endpoint must re-read, detect the mismatch, and 503
    # rather than falsely reporting success.
    class _Stale:
        def update(self, patch):
            return None  # pretend the write succeeded

        def read_all(self):
            return {}  # but nothing actually persisted

    monkeypatch.setattr(cfg, "get_vault", lambda: _Stale())
    res = client.put("/api/settings/secrets",
                     json={"values": {"ANTHROPIC_API_KEY": "sk-live"}})
    assert res.status_code == 503


def test_put_ioerror_returns_503(client, tmp_path, monkeypatch):
    # A disk-level failure (e.g. ENOSPC, permission revoked mid-write) surfaces
    # as 503, not 500 -- it's a server/environment fault the client can retry.
    class _Boom:
        def update(self, patch):
            raise OSError("disk full")

    monkeypatch.setattr(cfg, "get_vault", lambda: _Boom())
    res = client.put("/api/settings/secrets",
                     json={"values": {"ANTHROPIC_API_KEY": "sk"}})
    assert res.status_code == 503


def test_put_generic_error_returns_500(client, tmp_path, monkeypatch):
    # Any other unexpected error falls through to the catch-all -> 500.
    class _Boom:
        def update(self, patch):
            raise RuntimeError("something unexpected")

    monkeypatch.setattr(cfg, "get_vault", lambda: _Boom())
    res = client.put("/api/settings/secrets",
                     json={"values": {"ANTHROPIC_API_KEY": "sk"}})
    assert res.status_code == 500


def test_put_empty_value_write_unverifiable_returns_503(client, tmp_path, monkeypatch):
    # Blanking a key (PUT "") whose vault write silently fails must 503, not
    # falsely report success. Before the A1 fix, `if v and ...` skipped
    # revalidation entirely for empty values.
    class _Stale:
        def update(self, patch):
            return None  # pretend the write succeeded

        def read_all(self):
            return {"ANTHROPIC_API_KEY": "sk-old-stale-value"}  # never cleared

    monkeypatch.setattr(cfg, "get_vault", lambda: _Stale())
    res = client.put("/api/settings/secrets",
                     json={"values": {"ANTHROPIC_API_KEY": ""}})
    assert res.status_code == 503


def test_concurrent_puts_dont_lose_updates(client, tmp_vault):
    # Two simultaneous PUTs of different keys against a real tmp vault must both
    # persist; the write lock serializes the read-modify-write so neither
    # clobbers the other.
    import threading

    barrier = threading.Barrier(2)

    def _put(key, val):
        barrier.wait()
        client.put("/api/settings/secrets", json={"values": {key: val}})

    t1 = threading.Thread(target=_put, args=("ANTHROPIC_API_KEY", "sk-a"))
    t2 = threading.Thread(target=_put, args=("OPENAI_API_KEY", "sk-o"))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert tmp_vault.get("ANTHROPIC_API_KEY") == "sk-a"
    assert tmp_vault.get("OPENAI_API_KEY") == "sk-o"
