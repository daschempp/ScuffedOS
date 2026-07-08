"""M8 Slice 2 — Settings/secrets API.

GET returns which integrations are configured, as PRESENCE booleans only —
never raw secret values (spec §4.5). PUT writes new values into the
machine-bound vault, then re-resolves the running settings so the live process
picks them up without a restart. Grouped by integration for the Settings UI.
"""
from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import config as _cfg
from ..config import SECRET_FIELD_MAP, settings
from ..secrets import SECRET_KEYS, VaultDecryptError

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Serialize the read-modify-write in put_secrets so concurrent PUTs can't lose
# updates. The vault's update() is read_all -> merge -> write_all, which is not
# atomic across requests; this lock makes the whole sequence critical-section.
_vault_write_lock = threading.Lock()

# Presentation grouping: integration id -> (label, [vault keys]).
_INTEGRATIONS: dict[str, tuple[str, list[str]]] = {
    "anthropic": ("Anthropic", ["ANTHROPIC_API_KEY"]),
    "openai": ("OpenAI (embeddings)", ["OPENAI_API_KEY"]),
    "usda": ("USDA FoodData Central", ["FDC_API_KEY"]),
    "whoop": ("WHOOP", ["WHOOP_CLIENT_ID", "WHOOP_CLIENT_SECRET"]),
    "google": ("Google / Gmail / Calendar", ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]),
    "plaid": ("Plaid", ["PLAID_CLIENT_ID", "PLAID_SECRET"]),
}


class SecretKeyState(BaseModel):
    key: str
    present: bool


class IntegrationState(BaseModel):
    label: str
    keys: list[SecretKeyState]


class SecretsStateOut(BaseModel):
    integrations: dict[str, IntegrationState]
    vault_ok: bool


class SecretsUpdateIn(BaseModel):
    values: dict[str, str]


def _state() -> SecretsStateOut:
    # Probe with read_all(), NOT present(): present() intentionally swallows a
    # decrypt failure and returns an all-absent map, which would report
    # vault_ok=True on a genuinely corrupt/foreign vault (incl. a SaltCorrupted
    # salt) and never surface the re-auth banner. read_all() raises, so a decrypt
    # failure here correctly flips vault_ok=False.
    vault_ok = True
    try:
        stored = _cfg.get_vault().read_all()
        presence = {k: bool(stored.get(k)) for k in SECRET_KEYS}
    except VaultDecryptError:  # includes SaltCorruptedError
        vault_ok = False
        presence = {k: False for k in SECRET_KEYS}
    except Exception:
        vault_ok = False
        presence = {k: False for k in SECRET_KEYS}
    integrations = {
        iid: IntegrationState(
            label=label,
            keys=[SecretKeyState(key=k, present=bool(presence.get(k))) for k in keys],
        )
        for iid, (label, keys) in _INTEGRATIONS.items()
    }
    return SecretsStateOut(integrations=integrations, vault_ok=vault_ok)


@router.get("/secrets", response_model=SecretsStateOut)
def get_secrets() -> SecretsStateOut:
    """Masked presence of every integration secret. Never returns raw values."""
    return _state()


@router.put("/secrets", response_model=SecretsStateOut)
def put_secrets(body: SecretsUpdateIn) -> SecretsStateOut:
    """Write new secret values into the vault, then re-resolve running settings.

    A process-wide lock serializes read-modify-write so concurrent PUTs cannot
    lose each other's updates (SecretsVault.update() does read_all -> merge ->
    write_all, which is not atomic across requests). After the write, the vault
    is re-read and the written keys are verified present so a silent persistence
    failure surfaces as a 503 instead of a false success.
    """
    unknown = [k for k in body.values if k not in SECRET_KEYS]
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown secret key(s): {', '.join(unknown)}")
    patch = dict(body.values)
    with _vault_write_lock:
        try:
            _cfg.get_vault().update(patch)
        except VaultDecryptError as exc:
            # Bad credentials / machine changed: this is a client-recoverable
            # state (re-authenticate), not a server fault -> 422.
            raise HTTPException(
                status_code=422,
                detail=f"vault decrypt failed; re-authenticate: {exc}",
            )
        # Order matters: IOError/OSError must be caught before the catch-all
        # Exception below, or disk failures would surface as 500 not 503.
        except (IOError, OSError) as exc:
            raise HTTPException(status_code=503, detail=f"vault write failed: {exc}")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"unexpected vault error: {exc}")
        # Re-read and verify every written value (including empty-string
        # blanks) actually persisted; if not, the write silently failed and we
        # must not report success.
        try:
            reread = _cfg.get_vault().read_all()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"vault write unverifiable: {exc}")
        for k, v in patch.items():
            if reread.get(k) != v:
                raise HTTPException(
                    status_code=503,
                    detail=f"vault write did not persist key {k}",
                )
        # A PUT can also repair a previously non-empty field; force those keys so
        # the running process reflects the new value even if it was already set.
        for k, v in patch.items():
            field = next((f for f, vk in SECRET_FIELD_MAP.items() if vk == k), None)
            if field is not None:
                setattr(settings, field, v)
        _cfg.resolve_secrets_from_vault(settings)
    return _state()
