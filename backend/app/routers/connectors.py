"""M9 Slice 1 — Connectors read model.

GET /api/connectors is a pure read-time projection: it left-joins the static
connector catalog (_CATALOG below) over existing connection state —
provider_accounts rows (Google/WHOOP/Moodle), finance_items rows (Plaid), and
the contacts_sync_state row (macOS Contacts, M10) — and NEVER serializes
tokens.

The card SET comes from _CATALOG (always five), NOT providers.all_providers():
the test autouse fixture configures an EMPTY registry, and Plaid/macOS Contacts
have no provider_accounts writer at all. State is attached by matching the
catalog name against each store dict's "provider" key (or, for Plaid, the
finance items; for macOS Contacts, get_contacts_state()).
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
    ("macos_contacts", "Apple Contacts", "local"),
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
    if name == "macos_contacts":
        return _contacts_configured()
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


def _contacts_configured() -> bool:
    # Platform support comes from the macos_contacts seam, NOT raw sys.platform,
    # so configure(platform=…)/configure(fake_snapshot=…) drive the card's
    # configured/access/status deterministically on macOS dev + CI alike
    # (contract: Testing/CI seam). is_supported() honors an injected platform.
    from ..providers import macos_contacts

    return macos_contacts.is_supported()


def _contacts_access() -> str:
    from ..providers import macos_contacts

    return macos_contacts.probe_access(
        getattr(settings, "addressbook_root", macos_contacts.DEFAULT_ROOT)
    )


def _contacts_connector() -> ConnectorInfo:
    """macOS Contacts (auth_kind='local'): configured/access come from the
    macos_contacts seam (never store state); enabled/sync_status/last_sync_at/
    last_error mirror the persisted consent row; count is the imported-people
    total. Off a supported host (or FDA-ungated), the card never touches store
    state and access stays 'unknown'."""
    configured = _contacts_configured()
    access = _contacts_access() if configured else "unknown"
    state = store.get_contacts_state() if configured else {"enabled": False, "enabled_at": None}
    status = "connected" if (configured and state.get("enabled") and access == "granted") \
        else "not_connected"
    count = store.count_people(source="macos_contacts") if configured else None
    return ConnectorInfo(
        name="macos_contacts", label="Apple Contacts", auth_kind="local",
        configured=configured, status=status,
        connected_at=state.get("enabled_at"), provider_user_id=None,
        can_write_email=None, access=access, items=[],
        enabled=bool(state.get("enabled", False)),
        sync_status=state.get("status"),
        last_sync_at=state.get("last_sync_at"),
        last_error=state.get("last_error"),
        count=count,
    )


@router.get("", response_model=list[ConnectorInfo])
def list_connectors() -> list[ConnectorInfo]:
    """All five connectors with their current connection state. No tokens."""
    accounts = {a["provider"]: a for a in store.list_provider_accounts()}
    out: list[ConnectorInfo] = []
    for name, label, auth_kind in _CATALOG:
        if name == "plaid":
            out.append(_plaid_connector())
            continue
        if name == "macos_contacts":
            out.append(_contacts_connector())
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
