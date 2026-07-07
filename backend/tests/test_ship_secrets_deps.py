"""M8 Slice 2: the secrets vault depends on `cryptography` (AES-256-GCM + HKDF)
and, in the packaged app only, `keyring` (wrap the single vault key). Both must
be importable in the backend env so vault code never fails at import. keyring's
*backend* may be absent on ubuntu CI — that is handled in app/secrets.py, not
here; here we only assert the modules import."""

import importlib.util


def test_cryptography_importable():
    assert importlib.util.find_spec("cryptography") is not None
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF  # noqa: F401


def test_keyring_importable():
    # The module must import even where no OS backend is configured (CI);
    # app/secrets.py degrades to a file-only key when keyring has no backend.
    assert importlib.util.find_spec("keyring") is not None
    import keyring  # noqa: F401
