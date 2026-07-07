"""M8 Slice 2 secrets vault: AES-256-GCM round-trip, wrong-key GCM failure,
0600 perms, empty-vault default, and the CI-safe machine-id fallback. Every
test injects an explicit machine id so it round-trips on ubuntu CI with no
ioreg and no keyring backend. Nothing here touches the DB or the fresh_db
engine."""

import os
import stat

import pytest

from app import secrets as vaultmod
from app.secrets import SecretsVault, VaultDecryptError


def _vault(tmp_path, mid="unit-test-machine"):
    return SecretsVault(tmp_path, machine_id_override=mid, use_keyring=False)


def test_machine_id_env_override(monkeypatch):
    monkeypatch.setenv("SCUFFEDOS_VAULT_MACHINE_ID", "from-env")
    assert vaultmod.machine_id() == "from-env"


def test_machine_id_explicit_override_wins(monkeypatch):
    monkeypatch.setenv("SCUFFEDOS_VAULT_MACHINE_ID", "from-env")
    assert vaultmod.machine_id("explicit") == "explicit"


def test_machine_id_never_raises_without_ioreg(monkeypatch):
    # No env, and force the ioreg path to fail -> deterministic fallback string.
    monkeypatch.delenv("SCUFFEDOS_VAULT_MACHINE_ID", raising=False)
    monkeypatch.setattr(vaultmod, "_ioreg_platform_uuid", lambda: None)
    assert vaultmod.machine_id() == "dev-fallback-machine-id"


def test_empty_vault_reads_empty(tmp_path):
    assert _vault(tmp_path).read_all() == {}
    assert _vault(tmp_path).get("ANTHROPIC_API_KEY") is None


def test_roundtrip_set_get(tmp_path):
    v = _vault(tmp_path)
    v.set("ANTHROPIC_API_KEY", "sk-ant-123")
    v.set("OPENAI_API_KEY", "sk-oai-456")
    # A fresh instance on the same dir + machine id decrypts the same values.
    v2 = _vault(tmp_path)
    assert v2.get("ANTHROPIC_API_KEY") == "sk-ant-123"
    assert v2.get("OPENAI_API_KEY") == "sk-oai-456"
    assert v2.read_all() == {"ANTHROPIC_API_KEY": "sk-ant-123", "OPENAI_API_KEY": "sk-oai-456"}


def test_wrong_machine_id_fails_to_decrypt(tmp_path):
    _vault(tmp_path, mid="machine-A").set("K", "v")
    wrong = _vault(tmp_path, mid="machine-B")  # same salt file, different id
    with pytest.raises(VaultDecryptError):
        wrong.read_all()


def test_secrets_file_is_0600_and_dir_0700(tmp_path):
    v = _vault(tmp_path)
    v.set("K", "v")
    enc = tmp_path / "secrets.enc"
    assert enc.exists()
    assert stat.S_IMODE(enc.stat().st_mode) == 0o600
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700


def test_on_disk_format_is_nonce_ct_tag(tmp_path):
    v = _vault(tmp_path)
    v.set("K", "v")
    raw = (tmp_path / "secrets.enc").read_bytes()
    # 12-byte nonce prefix + AESGCM ciphertext(>=1) + 16-byte tag suffix.
    assert len(raw) >= 12 + 16 + 1


def test_present_masks_and_lists(tmp_path):
    v = _vault(tmp_path)
    v.set("ANTHROPIC_API_KEY", "sk-ant")
    v.set("OPENAI_API_KEY", "")  # explicitly-empty -> not present
    p = v.present()
    assert p["ANTHROPIC_API_KEY"] is True
    assert p["OPENAI_API_KEY"] is False


def test_set_overwrites_and_persists(tmp_path):
    v = _vault(tmp_path)
    v.set("K", "first")
    v.set("K", "second")
    assert _vault(tmp_path).get("K") == "second"


def test_salt_is_stable_across_instances(tmp_path):
    _vault(tmp_path).set("K", "v")
    salt1 = (tmp_path / "vault.salt").read_bytes()
    _vault(tmp_path).get("K")  # must not regenerate the salt
    salt2 = (tmp_path / "vault.salt").read_bytes()
    assert salt1 == salt2


def test_sequential_writes_use_fresh_nonces(tmp_path):
    # GCM nonce reuse under one key is catastrophic; every write_all must draw a
    # fresh 12-byte nonce. Two writes of the same plaintext must differ in the
    # nonce prefix (raw[:12]).
    v = _vault(tmp_path)
    v.set("K", "same-value")
    nonce1 = (tmp_path / "secrets.enc").read_bytes()[:12]
    v.set("K", "same-value")
    nonce2 = (tmp_path / "secrets.enc").read_bytes()[:12]
    assert nonce1 != nonce2


def test_derive_key_without_keyring_uses_file_key(tmp_path):
    # use_keyring=False must never touch keyring and returns a deterministic
    # file-derived key for a given (dir, machine id).
    v = SecretsVault(tmp_path, machine_id_override="k-off", use_keyring=False)
    k1 = v.derive_key()
    k2 = SecretsVault(tmp_path, machine_id_override="k-off", use_keyring=False).derive_key()
    assert k1 == k2
    assert len(k1) == 32


def test_derive_key_with_keyring_unavailable_degrades(tmp_path, monkeypatch):
    # use_keyring=True but the keyring backend raises -> silently degrade to the
    # file-derived key (this is the ubuntu-CI / locked-keychain path).
    import types

    fake = types.SimpleNamespace(
        get_password=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no backend")),
        set_password=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no backend")),
    )
    monkeypatch.setitem(__import__("sys").modules, "keyring", fake)
    v = SecretsVault(tmp_path, machine_id_override="k-degrade", use_keyring=True)
    file_key = SecretsVault(tmp_path, machine_id_override="k-degrade", use_keyring=False).derive_key()
    assert v.derive_key() == file_key


def test_vault_roundtrip_with_keyring_simulated(tmp_path, monkeypatch):
    # A fake in-memory keyring backend proves the keyring-wrapped path stores and
    # reuses one 32-byte hex item and round-trips a secret.
    import types

    store: dict[tuple[str, str], str] = {}
    fake = types.SimpleNamespace(
        get_password=lambda s, u: store.get((s, u)),
        set_password=lambda s, u, v: store.__setitem__((s, u), v),
    )
    monkeypatch.setitem(__import__("sys").modules, "keyring", fake)
    v = SecretsVault(tmp_path, machine_id_override="k-sim", use_keyring=True)
    v.set("K", "wrapped")
    assert len(store) == 1  # exactly one keyring item was written
    v2 = SecretsVault(tmp_path, machine_id_override="k-sim", use_keyring=True)
    assert v2.get("K") == "wrapped"


def test_keyring_malformed_entry_falls_back(tmp_path, monkeypatch, caplog):
    # A malformed keyring item (non-hex / wrong length) must not raise: degrade
    # to the file key and log a warning.
    import logging
    import types

    fake = types.SimpleNamespace(
        get_password=lambda *a, **k: "not-hex-zzzz",
        set_password=lambda *a, **k: None,
    )
    monkeypatch.setitem(__import__("sys").modules, "keyring", fake)
    v = SecretsVault(tmp_path, machine_id_override="k-bad", use_keyring=True)
    file_key = SecretsVault(tmp_path, machine_id_override="k-bad", use_keyring=False).derive_key()
    with caplog.at_level(logging.WARNING, logger="scuffed_os.secrets"):
        assert v.derive_key() == file_key
    assert any("not valid hex" in r.message for r in caplog.records)


def test_ioreg_timeout_falls_back(monkeypatch):
    # A hung ioreg (TimeoutExpired) must degrade to the fallback id, not raise.
    import subprocess as _sp

    monkeypatch.delenv("SCUFFEDOS_VAULT_MACHINE_ID", raising=False)

    def _boom(*a, **k):
        raise _sp.TimeoutExpired(cmd="ioreg", timeout=5.0)

    monkeypatch.setattr(vaultmod.subprocess, "run", _boom)
    assert vaultmod._ioreg_platform_uuid() is None
    assert vaultmod.machine_id() == "dev-fallback-machine-id"


def test_truncated_salt_raises_error(tmp_path):
    from app.secrets import SaltCorruptedError

    v = _vault(tmp_path)
    v.set("K", "v")  # creates a valid 16-byte salt + secrets.enc
    # Corrupt the salt to a truncated length; the next derive must refuse to
    # silently regenerate (which would orphan secrets.enc).
    (tmp_path / "vault.salt").write_bytes(b"\x00\x01\x02")
    with pytest.raises(SaltCorruptedError):
        _vault(tmp_path).read_all()


def test_salt_file_corruption_detected(tmp_path):
    from app.secrets import SaltCorruptedError

    # An empty salt file is corruption, not "unset" — must raise, not regenerate.
    v = _vault(tmp_path)
    v.set("K", "v")
    (tmp_path / "vault.salt").write_bytes(b"")
    with pytest.raises(SaltCorruptedError):
        _vault(tmp_path).read_all()
