"""M8 Ship/Tauri — machine-bound AES-256-GCM secrets vault (spec §4.5, §7).

Store of record: <app_support>/secrets.enc, dir 0700 / file 0600, on-disk
format nonce(12) || ciphertext || tag (AESGCM appends the 16-byte tag to the
ciphertext). The 32-byte key is HKDF-SHA256 over the Mac IOPlatformUUID plus a
per-install random salt (vault.salt). Machine-bound, prompt-free, survives
rebuilds. A decrypt failure (GCM auth fail / machine id changed) raises
VaultDecryptError, which the Settings screen turns into a re-authenticate flow
instead of crashing.

CI/dev safety: the machine id is injectable (constructor arg or the
SCUFFEDOS_VAULT_MACHINE_ID env var) so unit tests round-trip on ubuntu with no
ioreg; keyring wrapping is engaged only when use_keyring is set AND a backend
exists, otherwise it degrades to the file-derived key. Nothing here touches the
DB or imports app.config, so it is safe to construct from the config seam.

On-disk format (secrets.enc): 12-byte random nonce || AES-256-GCM ciphertext ||
16-byte auth tag. The nonce is fresh per encryption (secrets.token_bytes); the
tag is appended by AESGCM.encrypt(). read_all() slices raw[:12] as the nonce and
raw[12:] as the blob (ciphertext + tag). A fresh nonce every write is REQUIRED —
GCM nonce reuse under the same key is catastrophic; if a nonce pool is ever
added, it must never be shared with this vault.
"""

from __future__ import annotations

import json
import logging
import os
import secrets as _secrets
import subprocess
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_log = logging.getLogger("scuffed_os.secrets")

# The canonical set of secret field names the vault stores. Mirrors the
# secret-bearing config fields; the config seam (Task 3) maps settings fields to
# these keys. Kept here so the vault, the API, and the seam agree on one list.
SECRET_KEYS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "FDC_API_KEY",
    "WHOOP_CLIENT_ID",
    "WHOOP_CLIENT_SECRET",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "PLAID_CLIENT_ID",
    "PLAID_SECRET",
)

_HKDF_INFO = b"scuffedos-secrets-vault-v1"
_KEYRING_SERVICE = "scuffedos-vault"
_KEYRING_USER = "master-key"
_NONCE_LEN = 12


class VaultDecryptError(Exception):
    """The vault could not be decrypted (bad GCM tag / machine id changed)."""


class SaltCorruptedError(VaultDecryptError):
    """The per-install salt file exists but is not the expected 16 bytes.

    Subclasses VaultDecryptError so existing swallow/recover paths (the config
    seam, the Settings vault_ok banner) treat it as a decrypt failure and route
    to the re-authenticate flow, rather than silently regenerating a salt (which
    would derive a different key and orphan the existing ciphertext)."""


def _ioreg_platform_uuid() -> str | None:
    """Parse IOPlatformUUID from `ioreg -rd1 -c IOPlatformExpertDevice`.

    Returns None on any non-macOS / missing-binary / parse failure / timeout so
    callers fall back to a deterministic dev id. A slow boot (ioreg hanging) is
    explicitly caught as subprocess.TimeoutExpired and logged, so a wedged ioreg
    degrades to the fallback id instead of blocking startup forever.
    """
    try:
        out = subprocess.run(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True, text=True, timeout=5.0,
        )
    except subprocess.TimeoutExpired:
        _log.warning("ioreg timed out; using fallback machine id")
        return None
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    for line in out.stdout.splitlines():
        if "IOPlatformUUID" in line:
            # line looks like: "IOPlatformUUID" = "XXXXXXXX-....-...."
            parts = line.split('"')
            for i, tok in enumerate(parts):
                if tok == "IOPlatformUUID" and i + 2 < len(parts):
                    val = parts[i + 2].strip()
                    return val or None
    return None


def machine_id(override: str | None = None) -> str:
    """Stable per-machine id, with a CI/dev-safe fallback chain.

    Precedence: explicit override > SCUFFEDOS_VAULT_MACHINE_ID env > macOS
    IOPlatformUUID > a fixed dev string (so ubuntu CI is deterministic and this
    NEVER raises).
    """
    if override:
        return override
    env = os.environ.get("SCUFFEDOS_VAULT_MACHINE_ID")
    if env:
        return env
    uuid = _ioreg_platform_uuid()
    if uuid:
        return uuid
    return "dev-fallback-machine-id"


class SecretsVault:
    def __init__(
        self,
        root: str | os.PathLike,
        *,
        machine_id_override: str | None = None,
        use_keyring: bool = False,
    ) -> None:
        self.root = Path(os.path.expanduser(str(root)))
        self._mid_override = machine_id_override
        self._use_keyring = use_keyring

    # ---- paths ----
    @property
    def enc_path(self) -> Path:
        return self.root / "secrets.enc"

    @property
    def salt_path(self) -> Path:
        return self.root / "vault.salt"

    # ---- directory / salt ----
    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass  # best-effort on exotic filesystems

    def _salt(self) -> bytes:
        self._ensure_root()
        if self.salt_path.exists():
            existing = self.salt_path.read_bytes()
            # A truncated/corrupt salt must NOT be silently regenerated: a new
            # salt derives a different key and orphans secrets.enc forever. Raise
            # so the Settings re-auth path recovers instead of losing the vault.
            if len(existing) != 16:
                raise SaltCorruptedError(
                    f"vault.salt is {len(existing)} bytes, expected 16"
                )
            return existing
        salt = _secrets.token_bytes(16)
        self._atomic_write(self.salt_path, salt, mode=0o600)
        # _atomic_write does os.replace (atomic on POSIX) so a crash leaves
        # either the old or the new file, never a partial one; re-read and
        # verify the persisted bytes match before deriving a key over them.
        persisted = self.salt_path.read_bytes()
        if persisted != salt:
            raise SaltCorruptedError("vault.salt failed to persist correctly")
        return salt

    # ---- key derivation ----
    def _derive_file_key(self) -> bytes:
        salt = self._salt()
        hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=_HKDF_INFO)
        return hkdf.derive(machine_id(self._mid_override).encode("utf-8"))

    def derive_key(self) -> bytes:
        """32-byte AES key. In the packaged app (use_keyring), the file-derived
        key is stored in one keyring item so the OS encrypts it at rest; a
        keyring failure degrades silently to the file-derived key."""
        file_key = self._derive_file_key()
        if not self._use_keyring:
            return file_key
        try:
            import keyring

            stored = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USER)
            if stored:
                # Validate the stored item is well-formed 32-byte hex before we
                # trust it; a malformed entry (partial write, tampering) must
                # degrade to the file-derived key, not raise or return garbage.
                try:
                    key = bytes.fromhex(stored)
                except ValueError:
                    _log.warning(
                        "keyring vault-key item is not valid hex; "
                        "falling back to file-derived key"
                    )
                    return file_key
                if len(key) != 32:
                    _log.warning(
                        "keyring vault-key item is %d bytes, expected 32; "
                        "falling back to file-derived key", len(key)
                    )
                    return file_key
                return key
            keyring.set_password(_KEYRING_SERVICE, _KEYRING_USER, file_key.hex())
            return file_key
        except Exception:
            # No backend (CI) / locked keychain / any keyring error -> file key.
            return file_key

    # ---- atomic write helper (explicit mode via os.open) ----
    @staticmethod
    def _atomic_write(path: Path, data: bytes, *, mode: int) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        os.chmod(tmp, mode)  # umask can mask create mode; force it
        os.replace(tmp, path)
        os.chmod(path, mode)

    # ---- encrypt / decrypt ----
    def read_all(self) -> dict[str, str]:
        if not self.enc_path.exists():
            return {}
        raw = self.enc_path.read_bytes()
        if len(raw) < _NONCE_LEN + 16:
            raise VaultDecryptError("secrets.enc is truncated")
        nonce, blob = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
        # derive_key() may raise SaltCorruptedError (a VaultDecryptError subclass)
        # via _salt(); let that propagate UNCHANGED so callers can distinguish a
        # corrupt salt from a bad GCM tag. Only wrap genuine crypto/decrypt
        # errors below.
        key = self.derive_key()
        try:
            plaintext = AESGCM(key).decrypt(nonce, blob, None)
        except VaultDecryptError:
            raise  # already the right type (e.g. bubbled up); don't re-wrap
        except Exception as exc:  # InvalidTag and friends
            raise VaultDecryptError(str(exc)) from exc
        try:
            data = json.loads(plaintext.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise VaultDecryptError("vault plaintext is not valid JSON") from exc
        return {str(k): str(v) for k, v in data.items()}

    def write_all(self, values: dict[str, str]) -> None:
        self._ensure_root()
        nonce = _secrets.token_bytes(_NONCE_LEN)
        plaintext = json.dumps(values, separators=(",", ":")).encode("utf-8")
        blob = AESGCM(self.derive_key()).encrypt(nonce, plaintext, None)
        self._atomic_write(self.enc_path, nonce + blob, mode=0o600)

    # ---- convenience ----
    def get(self, key: str) -> str | None:
        return self.read_all().get(key) or None

    def set(self, key: str, value: str) -> None:
        values = self.read_all()
        values[key] = value
        self.write_all(values)

    def update(self, patch: dict[str, str]) -> None:
        values = self.read_all()
        values.update({k: v for k, v in patch.items()})
        self.write_all(values)

    def present(self) -> dict[str, bool]:
        """Presence map over the canonical SECRET_KEYS — True iff a non-empty
        value is stored. Never returns raw secret values."""
        stored = {}
        try:
            stored = self.read_all()
        except VaultDecryptError:
            stored = {}
        return {k: bool(stored.get(k)) for k in SECRET_KEYS}
