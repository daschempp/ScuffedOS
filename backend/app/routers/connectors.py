"""M9 Slice 1 — Connectors read model.

GET /api/connectors is a pure read-time projection: it left-joins the static
connector catalog (_CATALOG below) over existing connection state —
provider_accounts rows (Google/WHOOP/Moodle) and finance_items rows (Plaid) —
and NEVER serializes tokens. No new tables; alembic head stays 0009.

The card SET comes from _CATALOG (always four), NOT providers.all_providers():
the test autouse fixture configures an EMPTY registry, and Plaid has no
provider_accounts writer at all. State is attached by matching the catalog name
against each store dict's "provider" key (or, for Plaid, the finance items).
"""
from __future__ import annotations

from ..config import settings
from ..schemas import ConnectorInfo, ConnectorItem
from ..store import store
from fastapi import APIRouter

router = APIRouter(prefix="/api/connectors", tags=["connectors"])

# name -> (label, auth_kind). Authoritative catalog; mirrors settings._INTEGRATIONS.
# auth_kind is deliberately NOT provider.kind (that means sync direction).
_CATALOG: list[tuple[str, str, str]] = [
    ("google", "Google / Gmail", "oauth"),
    ("whoop", "WHOOP", "oauth"),
    ("moodle", "Moodle", "token"),
    ("plaid", "Plaid", "link"),
]


def _configured(name: str) -> bool:
    """App credentials present so a connect can even start. Reads vault-resolved
    settings (resolve ran at config import; a secrets PUT re-resolves), so
    runtime cred additions flip this without a restart. Moodle needs no creds —
    the pasted wstoken IS the credential — so it is always configured."""
    if name == "google":
        return bool(settings.google_client_id) and bool(settings.google_client_secret)
    if name == "whoop":
        return bool(settings.whoop_client_id) and bool(settings.whoop_client_secret)
    if name == "plaid":
        return bool(settings.plaid_client_id) and bool(settings.plaid_secret)
    if name == "moodle":
        return True
    return False


def _plaid_connector() -> ConnectorInfo:
    """Plaid has NO provider_accounts row — its state derives ONLY from
    finance_items. Connector status: any item needs_reauth -> needs_reauth;
    else >=1 item -> connected; else not_connected. Each item's stored 'active'
    maps to the connector-facing 'connected'."""
    raw = store.list_finance_items()
    items = [
        ConnectorItem(
            item_id=it["item_id"],
            institution_name=it["institution_name"],
            status="needs_reauth" if it["status"] == "needs_reauth" else "connected",
            last_sync_at=it["last_sync_at"],
        )
        for it in raw
    ]
    if any(it["status"] == "needs_reauth" for it in raw):
        status = "needs_reauth"
    elif raw:
        status = "connected"
    else:
        status = "not_connected"
    return ConnectorInfo(
        name="plaid", label="Plaid", auth_kind="link",
        configured=_configured("plaid"), status=status,
        connected_at=None, provider_user_id=None, can_write_email=None, items=items,
    )


@router.get("", response_model=list[ConnectorInfo])
def list_connectors() -> list[ConnectorInfo]:
    """All four connectors with their current connection state. No tokens."""
    accounts = {a["provider"]: a for a in store.list_provider_accounts()}
    out: list[ConnectorInfo] = []
    for name, label, auth_kind in _CATALOG:
        if name == "plaid":
            out.append(_plaid_connector())
            continue
        acc = accounts.get(name)
        if acc is None:
            out.append(ConnectorInfo(
                name=name, label=label, auth_kind=auth_kind,
                configured=_configured(name), status="not_connected",
                connected_at=None, provider_user_id=None,
                can_write_email=None, items=[],
            ))
        else:
            out.append(ConnectorInfo(
                name=name, label=label, auth_kind=auth_kind,
                configured=_configured(name), status=acc["status"],
                connected_at=acc["connected_at"],
                provider_user_id=acc["provider_user_id"],
                # can_write_email is google-only; the store emits False for the
                # others, so null it here to match ConnectorInfo's bool|None.
                can_write_email=acc["can_write_email"] if name == "google" else None,
                items=[],
            ))
    return out
