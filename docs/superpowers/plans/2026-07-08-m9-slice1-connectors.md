# M9 Slice 1 — Settings › Connectors (unified sign-in surface) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all four connector sign-ins (Google, WHOOP, Moodle, Plaid) into one surface — Settings › Connectors — backed by a new read-only `GET /api/connectors` projection, and slim the four data screens down to empty-state / needs-reauth deep-links.

**Architecture:** A new backend router projects existing connection state (no new tables — alembic head stays 0009) as a left-join of a static four-connector catalog over `provider_accounts` (Google/WHOOP/Moodle) and `finance_items` (Plaid). The OAuth callback stops 302-redirecting to a SPA the backend can't serve and returns inline success/error HTML instead (deleting the now-dead `success_redirect` hook). The frontend Settings screen becomes tabbed (Connectors | API keys); the four data screens lose their connect UI and render calm empty states that deep-link to the tab.

**Tech Stack:** FastAPI + Pydantic + SQLAlchemy (backend, pytest via TestClient + in-memory SQLite); React 18 + Vite (frontend, no test harness — verified by `npm run build` + a manual checklist).

**Spec:** `docs/superpowers/specs/2026-07-08-settings-connectors-design.md` (§6, §6a, §7, §8, §13). This plan implements **Slice 1 only**. Slices 2 (packaged sign-in) and 3 (signing + WHOOP) are planned separately later.

## Global Constraints

*(Every task's requirements implicitly include this section. Values are verified against the live tree at branch `m9-connectors-design`, tip `ea09485`.)*

- **Test baseline:** `674 passed, 1 skipped`. Run the full backend suite after every backend task and report the count; keep it green. (The spec's "671" predates three tests added on main; 674 is the real number.)
- **No new tables, no migration** — alembic head stays `0009`. `GET /api/connectors` is a pure read-time projection.
- **No tokens/scopes/meta ever serialized** by `GET /api/connectors` — same rule as `_provider_account_dict` (store.py:423) and `_finance_item_dict` (store.py:577).
- **Backend tests run through existing seams only, zero network:** the autouse `no_external_services` fixture (conftest.py:35) calls `providers.configure([])` — **the provider registry is EMPTY by default in every test.** The connectors endpoint does not read the registry (it drives its card set from a static catalog), so most connectors tests need no `configure`; tests that exercise OAuth *callback* behavior still `providers.configure([FakeProvider()])`. `fresh_db` (conftest.py:23) gives a clean store per test; the `client` fixture (conftest.py:73) is `TestClient(app)`.
- **No frontend test harness** — frontend tasks are verified by `npm run build` green (run from `frontend/`) plus the manual checklist in each task. Do not introduce a test harness (spec §14).
- **Config field-name traps (verified config.py):** `google_client_id` / `google_client_secret`, `whoop_client_id` / `whoop_client_secret`, `plaid_client_id` / **`plaid_secret`** (NOT `plaid_client_secret`; vault key `PLAID_SECRET`). Moodle has **zero** credential fields → it is **always** `configured=True` (its pasted wstoken IS the credential). `configured` reads vault-resolved settings directly (resolve ran at import; a secrets PUT re-resolves) — no extra vault call.
- **Naming traps:** the new catalog field is **`auth_kind`** ('oauth'|'token'|'link') — do NOT reuse `provider.kind` (that means sync direction). Client-facing item id is **`item_id`** (= `FinanceItem.source_id`), never `source_id` outside raw ORM. Stored status literals are `provider_accounts.status ∈ {connected, needs_reauth}` and `finance_items.status ∈ {active, needs_reauth}` — **never write `connected` into the DB** (finance_sync skips items whose status != 'active'). `active` maps to the connector-facing `connected` only in the projection.
- **Slice-2 boundary — do NOT touch in Slice 1:** `test_oauth.py:41` (the `_STATES` str→tuple assertion) and `test_email_config.py:12` (the `google_redirect_uri` default assertion). Both match the tree today and only change in Slice 2 (§9). Editing them here breaks the baseline early.
- **Order-of-ops (Task 3 before Task 4):** rewrite the callback's `impl.success_redirect()` call site (Task 3) BEFORE deleting the `success_redirect` methods (Task 4), or the callback raises `AttributeError`.
- **Frontend prop threading:** `SettingsScreen` and all four data screens currently take **no props**. Adding `onOpenConnectors` / tab props requires BOTH the App.jsx mount-line edit AND the component-signature edit — miss either and the deep-link is dead.

---

## File Structure

**Backend — created:**
- `backend/app/routers/connectors.py` — the `GET /api/connectors` read model (static catalog + left-join + `configured`/Plaid-status derivation).
- `backend/tests/test_connectors.py` — projection tests.

**Backend — modified:**
- `backend/app/schemas.py` — add `ConnectorItem`, `ConnectorInfo`.
- `backend/app/main.py` — import + mount the new router.
- `backend/app/routers/oauth.py` — callback returns HTML (§6a); drop `RedirectResponse`, add `HTMLResponse` + `html`.
- `backend/app/providers/base.py`, `google.py`, `whoop.py`, `moodle.py` — delete `success_redirect`.
- `backend/tests/test_oauth.py` — rewrite the three callback behavior-lock tests + add the §13 error-page tests.
- `backend/tests/fakes.py`, `backend/tests/test_moodle_provider.py`, `backend/tests/test_providers_base.py`, `backend/tests/test_whoop_provider.py`, `backend/tests/test_google_oauth.py` — delete `success_redirect` fakes/string-assert tests.

**Frontend — created:**
- `frontend/src/screens/ApiKeysPanel.jsx` — the existing secrets UI, moved out of SettingsScreen.
- `frontend/src/screens/ConnectorsPanel.jsx` — the new connector-cards surface.
- `frontend/src/components/ConnectorEmptyState.jsx` — shared not-connected card + needs-reauth banner for the data screens.

**Frontend — modified:**
- `frontend/src/lib/api.js` — add `getConnectors`.
- `frontend/src/App.jsx` — lift `settingsTab`, add `onOpenConnectors`, thread props.
- `frontend/src/screens/SettingsScreen.jsx` — becomes a thin tab shell.
- `frontend/src/screens/{Email,Fitness,School,Finance}Screen.jsx` — slim down (§8).

---

## Task 1: Connector schemas (`ConnectorItem`, `ConnectorInfo`)

**Files:**
- Modify: `backend/app/schemas.py` (add after the OAuth schema block, ~line 410 — `ConnectUrl` closes the block)
- Test: `backend/tests/test_connectors_schema.py` (create)

**Interfaces:**
- Produces: `ConnectorItem(item_id: str, institution_name: str, status: Literal["connected","needs_reauth"], last_sync_at: datetime | None)`; `ConnectorInfo(name: Literal["google","whoop","moodle","plaid"], label: str, auth_kind: Literal["oauth","token","link"], configured: bool, status: Literal["not_connected","connected","needs_reauth"], connected_at: datetime | None, provider_user_id: str | None, can_write_email: bool | None, items: List[ConnectorItem])`.
- Consumes: nothing. `Literal`, `datetime`, `List` are already imported in schemas.py (used by `ProviderStatus`/`FinanceStatus`).

**Why a new schema (not reuse `ProviderStatus`):** `ProviderStatus.connected_at` is non-optional (schemas.py:393) — a not-connected projection would 500 — AND its `status` is `Literal["connected","needs_reauth"]` with no `not_connected` member (schemas.py:391). `ConnectorInfo.status` is a 3-member superset.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_connectors_schema.py`:

```python
"""M9 Slice 1 — ConnectorInfo/ConnectorItem schema shape."""
import pytest
from pydantic import ValidationError

from app.schemas import ConnectorInfo, ConnectorItem


def test_connector_info_allows_not_connected_with_null_timestamps():
    info = ConnectorInfo(
        name="google", label="Google / Gmail", auth_kind="oauth",
        configured=False, status="not_connected",
    )
    assert info.connected_at is None
    assert info.provider_user_id is None
    assert info.can_write_email is None
    assert info.items == []


def test_connector_info_rejects_unknown_status():
    with pytest.raises(ValidationError):
        ConnectorInfo(
            name="google", label="Google", auth_kind="oauth",
            configured=True, status="bogus",
        )


def test_connector_item_status_is_connector_vocabulary():
    item = ConnectorItem(
        item_id="itm1", institution_name="Chase",
        status="connected", last_sync_at=None,
    )
    assert item.status == "connected"
    with pytest.raises(ValidationError):
        ConnectorItem(item_id="i", institution_name="x", status="active", last_sync_at=None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_connectors_schema.py -v`
Expected: FAIL with `ImportError: cannot import name 'ConnectorInfo'`.

- [ ] **Step 3: Add the schemas**

In `backend/app/schemas.py`, immediately after the `ConnectUrl` class (the end of the OAuth schema block, ~line 413), add:

```python
# ---- M9 Connectors (Slice 1) — unified read model for Settings › Connectors ----
class ConnectorItem(BaseModel):
    """One linked institution (Plaid only). The stored 'active' literal is
    mapped to the connector-facing 'connected' at projection time."""
    item_id: str
    institution_name: str
    status: Literal["connected", "needs_reauth"]
    last_sync_at: datetime | None = None


class ConnectorInfo(BaseModel):
    """One connector card. `status` is a 3-member superset of
    ProviderStatus.status (adds 'not_connected', which a provider_accounts row
    can never express). Tokens/scopes are NEVER included — same rule as
    _provider_account_dict."""
    name: Literal["google", "whoop", "moodle", "plaid"]
    label: str
    auth_kind: Literal["oauth", "token", "link"]
    configured: bool
    status: Literal["not_connected", "connected", "needs_reauth"]
    connected_at: datetime | None = None
    provider_user_id: str | None = None
    can_write_email: bool | None = None   # google only; None for the others
    items: List[ConnectorItem] = []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_connectors_schema.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas.py backend/tests/test_connectors_schema.py
git commit -m "feat(connectors): ConnectorInfo/ConnectorItem read schemas (M9 s1)"
```

---

## Task 2: `GET /api/connectors` router + projection + mount

**Files:**
- Create: `backend/app/routers/connectors.py`
- Modify: `backend/app/main.py:25-38` (import) and `backend/app/main.py:143` (mount)
- Test: `backend/tests/test_connectors.py` (create)

**Interfaces:**
- Consumes: `ConnectorInfo`, `ConnectorItem` (Task 1); `store.list_provider_accounts() -> list[dict]` keyed on `"provider"` with `_provider_account_dict` fields (`provider, status, connected_at, last_sync_at, provider_user_id, can_write_email`); `store.list_finance_items() -> list[dict]` with `_finance_item_dict` fields (`item_id, institution_name, status, products, connected_at, last_sync_at`); `settings.{google_client_id,google_client_secret,whoop_client_id,whoop_client_secret,plaid_client_id,plaid_secret}`.
- Produces: `GET /api/connectors -> list[ConnectorInfo]`, always four entries ordered `google, whoop, moodle, plaid`.

**Load-bearing design (from spec §6 + verified tree):** the card SET is driven by the module's own `_CATALOG` (authoritative, always four) — NOT `providers.all_providers()`, which returns `[]` under the test autouse fixture and never contains Plaid (Plaid has no `provider_accounts` writer). State is attached by matching `_CATALOG` name against `store.list_provider_accounts()` dicts' `"provider"` key; Plaid state derives solely from `store.list_finance_items()`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_connectors.py`:

```python
"""M9 Slice 1 — GET /api/connectors read-model projection."""
import json
from datetime import datetime, timezone

from app.config import settings
from app.providers.base import NormalizedItem, Tokens
from app.store import store


def _get(client):
    res = client.get("/api/connectors")
    assert res.status_code == 200
    return {c["name"]: c for c in res.json()}


def test_all_four_present_not_connected_on_empty_db(client):
    body = client.get("/api/connectors").json()
    assert [c["name"] for c in body] == ["google", "whoop", "moodle", "plaid"]
    assert [c["auth_kind"] for c in body] == ["oauth", "oauth", "token", "link"]
    for c in body:
        assert c["status"] == "not_connected"
        assert c["connected_at"] is None
        assert c["items"] == []


def test_moodle_always_configured_others_not_without_creds(client):
    body = _get(client)
    assert body["moodle"]["configured"] is True
    assert body["google"]["configured"] is False
    assert body["whoop"]["configured"] is False
    assert body["plaid"]["configured"] is False


def test_configured_flips_when_creds_present(client, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "gid")
    monkeypatch.setattr(settings, "google_client_secret", "gsecret")
    monkeypatch.setattr(settings, "plaid_client_id", "pid")
    monkeypatch.setattr(settings, "plaid_secret", "psecret")
    body = _get(client)
    assert body["google"]["configured"] is True
    assert body["plaid"]["configured"] is True
    assert body["whoop"]["configured"] is False  # only whoop creds still absent


def test_connected_google_projects_can_write_email(client):
    store.upsert_provider_account(
        "google",
        Tokens(
            access_token="a", refresh_token="r", expires_at=None,
            scopes=(
                "https://www.googleapis.com/auth/gmail.modify "
                "https://www.googleapis.com/auth/gmail.send"
            ),
            provider_user_id="g1",
        ),
    )
    g = _get(client)["google"]
    assert g["status"] == "connected"
    assert g["connected_at"] is not None
    assert g["provider_user_id"] == "g1"
    assert g["can_write_email"] is True


def test_google_needs_reauth_projects_through(client):
    store.upsert_provider_account(
        "google", Tokens(access_token="a", refresh_token="r", expires_at=None,
                          scopes="", provider_user_id="g1"),
    )
    store.set_provider_status("google", "needs_reauth")
    assert _get(client)["google"]["status"] == "needs_reauth"


def test_non_google_can_write_email_is_null_not_false(client):
    store.upsert_provider_account(
        "whoop", Tokens(access_token="a", refresh_token="r", expires_at=None,
                        scopes="read:recovery", provider_user_id="w1"),
    )
    w = _get(client)["whoop"]
    assert w["status"] == "connected"
    assert w["can_write_email"] is None   # store emits False for whoop; projection nulls it


def test_plaid_items_nested_and_status_derived(client):
    store.upsert_finance_item(
        NormalizedItem(item_id="itm1", institution_id="ins_1",
                       institution_name="Chase", products=["transactions"]),
        access_token="tok1",
    )
    store.upsert_finance_item(
        NormalizedItem(item_id="itm2", institution_id="ins_2",
                       institution_name="Fidelity", products=["investments"]),
        access_token="tok2",
    )
    p = _get(client)["plaid"]
    assert p["status"] == "connected"
    assert {i["item_id"] for i in p["items"]} == {"itm1", "itm2"}
    assert all(i["status"] == "connected" for i in p["items"])  # 'active' -> 'connected'

    store.set_finance_item_status("itm2", "needs_reauth")
    p2 = _get(client)["plaid"]
    assert p2["status"] == "needs_reauth"
    statuses = {i["item_id"]: i["status"] for i in p2["items"]}
    assert statuses == {"itm1": "connected", "itm2": "needs_reauth"}


def test_no_token_material_in_response(client):
    store.upsert_provider_account(
        "whoop", Tokens(access_token="secret-access", refresh_token="secret-refresh",
                        expires_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
                        scopes="read:recovery", provider_user_id="w1"),
    )
    store.upsert_finance_item(
        NormalizedItem(item_id="itm1", institution_id="ins_1",
                       institution_name="Chase", products=["transactions"]),
        access_token="plaid-secret-token",
    )
    raw = json.dumps(client.get("/api/connectors").json())
    for leak in ("secret-access", "secret-refresh", "plaid-secret-token",
                 "access_token", "refresh_token", "scopes"):
        assert leak not in raw
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_connectors.py -v`
Expected: FAIL — `GET /api/connectors` returns 404 (router not mounted).

- [ ] **Step 3: Create the router**

Create `backend/app/routers/connectors.py`:

```python
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
```

- [ ] **Step 4: Mount the router in main.py**

In `backend/app/main.py`, add `connectors` to the import tuple (keep the block tidy — insert after `calendar,` on line 27):

```python
from .routers import (
    assistant,
    calendar,
    connectors,
    email,
    finance,
    fitness,
    habits,
    memory,
    moodle,
    nutrition,
    oauth,
    settings as settings_router,
    tasks,
)
```

Then add the mount next to the others (after `app.include_router(finance.router)` on line 143):

```python
app.include_router(finance.router)
app.include_router(connectors.router)
app.include_router(settings_router.router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_connectors.py -v`
Expected: PASS (8 passed).

- [ ] **Step 6: Run the full suite**

Run: `cd backend && python -m pytest`
Expected: `685 passed, 1 skipped` (674 baseline + 3 from Task 1 + 8 from Task 2). Report the exact number; it must be all green.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/connectors.py backend/app/main.py backend/tests/test_connectors.py
git commit -m "feat(connectors): GET /api/connectors read-model projection (M9 s1)"
```

---

## Task 3: OAuth callback returns HTML (§6a) + rewrite the callback tests

**Files:**
- Modify: `backend/app/routers/oauth.py` (imports :17-18; module docstring :1-11 and :76-79; callback :70-96)
- Modify: `backend/tests/test_oauth.py` (rewrite the three callback tests :82-135; add the §13 error-page tests)

**Interfaces:**
- Consumes: existing `_consume_state`, `providers.get`, `store.upsert_provider_account`, provider `exchange_code`/`fetch_profile`/`on_connected`.
- Produces: `GET /auth/{provider}/callback` now returns `HTMLResponse` — 200 on success, 400 on any error path (invalid/expired state, `error` param, missing `code`, exchange failure). Signature: `oauth_callback(provider, code: str | None = None, error: str | None = None, state: str = Query(...))`. State is consumed on **every** path. `success_redirect` is no longer called (deleted in Task 4).

**Why (verified):** today `code: str = Query(...)` is required, so Google's `access_denied` redirect (error + no code) 422s before handler code runs; and the callback 302-redirects via `impl.success_redirect()` to a SPA path the backend cannot serve (no StaticFiles). Grep confirmed **no** frontend `?connected=`/`screen=` consumer survives — the frontend change here is nil.

- [ ] **Step 1: Rewrite the three callback tests to expect HTML (write the failing tests first)**

In `backend/tests/test_oauth.py`, replace `test_callback_exchanges_persists_and_triggers_immediate_sync` (lines 82-106), `test_callback_with_bad_state_is_400_and_persists_nothing` (109-123), and `test_callback_state_is_single_use` (126-135) with:

```python
def test_callback_success_renders_html_and_persists_and_syncs(client, monkeypatch):
    from app import fitness_sync

    fake = FakeProvider()
    providers.configure([fake])
    ticks: list[object] = []
    monkeypatch.setattr(fitness_sync, "tick", lambda now=None: ticks.append(now) or 0)

    state = _state_of(client.get("/api/oauth/connect/whoop").json()["authorize_url"])
    res = client.get(f"/auth/whoop/callback?code=the-code&state={state}", follow_redirects=False)
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "close this tab" in res.text.lower()

    assert fake.exchanged == ["the-code"]
    accounts = store.list_provider_accounts()
    assert [a["provider"] for a in accounts] == ["whoop"]
    assert accounts[0]["status"] == "connected"
    assert accounts[0]["provider_user_id"] == "whoop-user-1"
    assert len(ticks) == 1                 # WhoopProvider.on_connected -> fitness_sync.tick
    assert state not in oauth._STATES


def test_callback_with_bad_state_renders_error_html_and_persists_nothing(client, monkeypatch):
    from app import fitness_sync

    fake = FakeProvider()
    providers.configure([fake])
    monkeypatch.setattr(fitness_sync, "tick", lambda now=None: 0)

    res = client.get("/auth/whoop/callback?code=x&state=forged-state", follow_redirects=False)
    assert res.status_code == 400
    assert "text/html" in res.headers["content-type"]
    assert fake.exchanged == []
    assert store.list_provider_accounts() == []


def test_callback_state_is_single_use(client, monkeypatch):
    from app import fitness_sync

    providers.configure([FakeProvider()])
    monkeypatch.setattr(fitness_sync, "tick", lambda now=None: 0)
    state = _state_of(client.get("/api/oauth/connect/whoop").json()["authorize_url"])
    first = client.get(f"/auth/whoop/callback?code=a&state={state}", follow_redirects=False)
    assert first.status_code == 200
    replay = client.get(f"/auth/whoop/callback?code=a&state={state}", follow_redirects=False)
    assert replay.status_code == 400   # state already consumed -> error page


def test_callback_access_denied_renders_error_without_422(client, monkeypatch):
    # Google's access_denied redirect carries error and NO code. The old
    # required `code` param would 422 before handler code ran; §6a must render
    # the inline error page instead. State is still consumed.
    from app import fitness_sync

    fake = FakeProvider()
    providers.configure([fake])
    monkeypatch.setattr(fitness_sync, "tick", lambda now=None: 0)
    state = _state_of(client.get("/api/oauth/connect/whoop").json()["authorize_url"])
    res = client.get(f"/auth/whoop/callback?error=access_denied&state={state}", follow_redirects=False)
    assert res.status_code == 400
    assert "text/html" in res.headers["content-type"]
    assert fake.exchanged == []
    assert store.list_provider_accounts() == []
    assert state not in oauth._STATES        # consumed even on the error path


def test_callback_missing_code_renders_error(client, monkeypatch):
    from app import fitness_sync

    fake = FakeProvider()
    providers.configure([fake])
    monkeypatch.setattr(fitness_sync, "tick", lambda now=None: 0)
    state = _state_of(client.get("/api/oauth/connect/whoop").json()["authorize_url"])
    res = client.get(f"/auth/whoop/callback?state={state}", follow_redirects=False)
    assert res.status_code == 400
    assert fake.exchanged == []
```

- [ ] **Step 2: Run the callback tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_oauth.py -k callback -v`
Expected: FAIL — old handler still 302s / requires `code` (access_denied 422s), success asserts 200 fail.

- [ ] **Step 3: Rewrite the callback handler**

In `backend/app/routers/oauth.py`:

(a) Replace the import on line 18 and add `html`; update line 17 stays (`Query` still used):

```python
import html as _html
import logging
import secrets

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
```

(b) Add the two page helpers just above the callback (after `_status_dict`, before `@router.get("/connect/...")` is fine; place directly above `oauth_callback`):

```python
def _callback_page(title: str, message: str, *, status_code: int) -> HTMLResponse:
    # Inline styles only (no <style> block) so there are no CSS braces to escape;
    # title/message are server-built and any reflected query value is escaped by
    # the caller.
    body = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{title}</title></head>"
        "<body style=\"font-family:-apple-system,system-ui,sans-serif;display:flex;"
        "min-height:100vh;margin:0;align-items:center;justify-content:center;background:#faf9f7\">"
        "<main style=\"max-width:28rem;padding:2rem;text-align:center;color:#1c1a17\">"
        f"<h1 style=\"font-size:1.25rem;margin:0 0 .5rem\">{title}</h1>"
        f"<p style=\"margin:0;color:#57534e;line-height:1.5\">{message}</p>"
        "</main></body></html>"
    )
    return HTMLResponse(content=body, status_code=status_code)


def _callback_success() -> HTMLResponse:
    return _callback_page(
        "✓ Connected",
        "You can close this tab and return to ScuffedOS.",
        status_code=200,
    )


def _callback_error(reason: str) -> HTMLResponse:
    return _callback_page(
        "Sign-in didn’t finish",
        f"{reason} Start again from Settings › Connectors.",
        status_code=400,
    )
```

(c) Replace the callback handler (lines 70-96) with:

```python
@auth_router.get("/auth/{provider}/callback")
def oauth_callback(
    provider: str,
    code: str | None = None,
    error: str | None = None,
    state: str = Query(...),
) -> HTMLResponse:
    """OAuth redirect target (outside /api). Consume the one-time CSRF state on
    EVERY path, then either exchange the code (success) or render an inline
    error page. The backend serves no SPA, so there is no redirect back into the
    app — the user closes the tab and the Connectors tab's poll (Slice 2) picks
    up the flip. Tokens never leave the server."""
    issued_for = _consume_state(state)
    if issued_for is None or issued_for != provider:
        return _callback_error("This sign-in link has expired or is invalid.")
    if error is not None or code is None:
        detail = _html.escape(error) if error else "no authorization code was returned"
        return _callback_error(f"The provider reported: {detail}.")
    impl = providers.get(provider)
    if impl is None:
        return _callback_error(f"Unknown provider ‘{_html.escape(provider)}’.")
    try:
        tokens = impl.exchange_code(code)
        fetch_profile = getattr(impl, "fetch_profile", None)
        if fetch_profile is not None and tokens.provider_user_id is None:
            uid = fetch_profile(tokens)
            if uid is not None:
                tokens.provider_user_id = uid
        store.upsert_provider_account(provider, tokens)
        impl.on_connected()   # immediate domain sync/backfill (fresh account → backfill)
    except Exception as exc:  # noqa: BLE001 — surface exchange failure as the error page
        logger.warning("oauth callback exchange failed for %s: %s", provider, exc)
        return _callback_error("The sign-in could not be completed.")
    return _callback_success()
```

(d) Update the module docstring (lines 1-11) — the `success_redirect (where to land)` clause and the "bounce back to the provider's screen" description are now false. Change the relevant sentence to:

```python
"""Shared OAuth router (M5, callback reworked M9) — provider-registry-driven
connect/callback/disconnect/status, extracted from routers/fitness.py so a
second OAuth domain (email) reuses the plumbing. Domain-specific behavior lives
behind the OAuthProvider hooks: on_connected (kick the domain sync),
on_disconnect (delete the domain's data). The callback renders inline
success/error HTML (the backend serves no SPA); tokens never leave the server.
```

(Keep the rest of the docstring — the two-routers paragraph — unchanged.)

- [ ] **Step 4: Run the callback tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_oauth.py -v`
Expected: PASS. (The `success_redirect` string-assert tests in *other* files still pass — those methods still exist until Task 4.)

- [ ] **Step 5: Run the full suite**

Run: `cd backend && python -m pytest`
Expected: all green (baseline + Task 1/2 additions + the 2 new callback tests). Report the count.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/oauth.py backend/tests/test_oauth.py
git commit -m "feat(connectors): OAuth callback returns inline HTML, handles error/denied (M9 s1 §6a)"
```

---

## Task 4: Delete the dead `success_redirect` hook

**Files (delete `success_redirect` from each):**
- Modify: `backend/app/providers/base.py:179` (protocol method)
- Modify: `backend/app/providers/google.py:302-303`, `whoop.py:170-172` (3 lines — has a docstring), `moodle.py:415-416`
- Modify: `backend/tests/fakes.py:150-151`, `:388-389`, `:491-492` (fake impls)
- Modify: `backend/tests/test_moodle_provider.py:92`, `backend/tests/test_providers_base.py:76` (inline-fake methods)
- Modify: `backend/tests/test_whoop_provider.py:10-11` (+ docstring :3), `backend/tests/test_google_oauth.py:191-192` (delete the whole string-assert test functions)

**Interfaces:** removes `OAuthProvider.success_redirect` entirely. `OAuthProvider` is `@runtime_checkable` but `success_redirect` is a plain method (not isinstance-checked), so removing it is safe — no isinstance guard depends on it. The only production caller (oauth.py:96) was already rewritten in Task 3.

**Precise deletion note (verified — do NOT use a naive "def + next line" rule):** `whoop.py` has a one-line docstring between signature and return, so it is a **3-line** delete (170-172); `google.py` (302-303) and `moodle.py` (415-416) are bare 2-line deletes. In `test_whoop_provider.py` and `test_google_oauth.py`, delete the entire test *function* (not just the assert). Do NOT touch adjacent `on_connected` hooks in fakes — they are load-bearing (`FakeProvider.on_connected` kicks `fitness_sync.tick`; the success test asserts `len(ticks)==1`).

- [ ] **Step 1: Delete the protocol method + all three real impls**

Read each file, confirm the range, and delete:
- `base.py`: the `success_redirect` declaration at line 179 (and its docstring/`...` body if present — delete the whole method).
- `google.py:302-303`: `def success_redirect(self) -> str:` + its `return ...`.
- `whoop.py:170-172`: `def success_redirect(self) -> str:` + docstring line 171 + `return ...` line 172.
- `moodle.py:415-416`: `def success_redirect(self) -> str:` + its `return ...`.

- [ ] **Step 2: Delete the fake impls**

- `tests/fakes.py`: the three `success_redirect` method defs at 150-151, 388-389, 491-492 (each is `def success_redirect(self)` + its `return`). Leave the neighboring `on_connected` methods intact.
- `tests/test_moodle_provider.py:92` and `tests/test_providers_base.py:76`: the inline-fake `success_redirect` method (delete the `def` + its return line).

- [ ] **Step 3: Delete the string-assert tests**

- `tests/test_whoop_provider.py`: delete the test function spanning lines 10-11 (the one asserting the `success_redirect` string) and fix the module docstring on line 3 if it references `success_redirect`.
- `tests/test_google_oauth.py`: delete the test function spanning lines 191-192.

- [ ] **Step 4: Grep to prove nothing references it**

Run: `cd backend && grep -rn "success_redirect" app/ tests/`
Expected: **no output** (empty). If anything remains in `app/` or `tests/`, delete it. (Ignore any matches under `.claude/worktrees/**` or `src-tauri/target/**` — those are stale copies; the grep above is scoped to `app/`+`tests/` so it won't see them.)

- [ ] **Step 5: Run the full suite**

Run: `cd backend && python -m pytest`
Expected: all green (two fewer tests than after Task 3 — the two string-assert tests were deleted). Report the count.

- [ ] **Step 6: Commit**

```bash
git add backend/app/providers/base.py backend/app/providers/google.py backend/app/providers/whoop.py backend/app/providers/moodle.py backend/tests/fakes.py backend/tests/test_moodle_provider.py backend/tests/test_providers_base.py backend/tests/test_whoop_provider.py backend/tests/test_google_oauth.py
git commit -m "refactor(connectors): delete dead success_redirect hook + its tests (M9 s1 §6a)"
```

*(Backend is now complete and shippable on its own: `GET /api/connectors` live, callback reworked, suite green.)*

---

## Task 5: Frontend scaffolding — `getConnectors` + App.jsx state & prop threading

**Files:**
- Modify: `frontend/src/lib/api.js` (add `getConnectors` after the oauth block, ~line 178)
- Modify: `frontend/src/App.jsx` (state ~line 73; mount lines 117/121/124/125/126)

**Interfaces:**
- Produces: `api.getConnectors() -> Promise<ConnectorInfo[]>`; `App` provides `settingsTab` ('connectors'|'keys', default 'connectors'), `setSettingsTab`, and `onOpenConnectors()`; passes `tab`/`onTabChange` to `<SettingsScreen/>` and `onOpenConnectors` to the four data screens.
- Note: the receiving components don't destructure these props until Tasks 6/8/9. Passing unknown props to a function component is harmless — the build stays green and behavior is unchanged this task.

- [ ] **Step 1: Add the api helper**

In `frontend/src/lib/api.js`, after the `oauthDisconnect` line (178), add:

```javascript
  // M9 Connectors — unified read model for Settings › Connectors. One card per
  // connector (google/whoop/moodle/plaid) with status + configured + Plaid items.
  getConnectors: () => request('/api/connectors'),
```

- [ ] **Step 2: Lift settingsTab + onOpenConnectors in App.jsx**

In `frontend/src/App.jsx`, after `const [screen, setScreen] = React.useState('home')` (line 73), add:

```javascript
  const [settingsTab, setSettingsTab] = React.useState('connectors')
  const onOpenConnectors = () => { setScreen('settings'); setSettingsTab('connectors') }
```

- [ ] **Step 3: Thread the props into the mount lines**

Change the five mount lines in the `body` if/else (lines 117-126):

```javascript
  else if (screen === 'finance') body = <FinanceScreen onOpenConnectors={onOpenConnectors} />
  ...
  else if (screen === 'fitness') body = <FitnessScreen onOpenConnectors={onOpenConnectors} />
  ...
  else if (screen === 'email') body = <EmailScreen onOpenConnectors={onOpenConnectors} />
  else if (screen === 'school') body = <SchoolScreen onOpenConnectors={onOpenConnectors} />
  else if (screen === 'settings') body = <SettingsScreen tab={settingsTab} onTabChange={setSettingsTab} />
```

(Leave the other `body = ...` lines unchanged.)

- [ ] **Step 4: Build**

Run: `cd frontend && npm run build`
Expected: build succeeds; no visible behavior change yet.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.js frontend/src/App.jsx
git commit -m "feat(connectors): api.getConnectors + App settingsTab/onOpenConnectors wiring (M9 s1)"
```

---

## Task 6: SettingsScreen becomes a tab shell; extract the secrets UI into ApiKeysPanel

**Files:**
- Create: `frontend/src/screens/ApiKeysPanel.jsx`
- Modify: `frontend/src/screens/SettingsScreen.jsx` (becomes a thin shell)

**Interfaces:**
- Consumes: `SettingsScreen({ tab, onTabChange })` from Task 5.
- Produces: `<ApiKeysPanel/>` (the existing secrets UI, unchanged behavior incl. vault-locked recovery + first-run nudge + the M8 "Add keys" expand); a tabbed `SettingsScreen` rendering `ApiKeysPanel` under `keys` and a `ConnectorsPanel` **stub** under `connectors` (the real panel lands in Task 7).

**Why an extraction (spec §7 + critic):** the two full-component early returns (vault-locked, first-run nudge) short-circuit before the main render. Moving them wholesale into `ApiKeysPanel` lets the tab bar render *above* them in the shell — so the Connectors tab is reachable even when the vault is locked or empty. There is no Tabs primitive in the kit; the tab bar is built inline from `Button` + local styling.

- [ ] **Step 1: Create ApiKeysPanel by moving the current secrets UI**

Create `frontend/src/screens/ApiKeysPanel.jsx`. **Move** the entire body of the current `SettingsScreen` (SettingsScreen.jsx lines 7-183: the imports it needs, all `React.useState`/`useCallback`/`useEffect`, the handlers, the two early-return branches, and the main `return`) into a new component `export function ApiKeysPanel()`. The code is identical to today's `SettingsScreen` function body — only the function name changes. Keep the file header comment describing it as the API-keys/secrets panel. Concretely, the new file is:

```javascript
/* Scuffed OS — Settings › API keys panel (M8 Slice 2, extracted M9 Slice 1).
   Shows which integrations are configured (masked presence only), lets the user
   paste/update keys, nudges first-run onboarding, and surfaces the vault
   re-authenticate recovery path. Was SettingsScreen's body before M9 split
   Settings into Connectors | API keys tabs. */
import React from 'react'
import { Card, Button } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'
import { api } from '../lib/api.js'

export function ApiKeysPanel() {
  // <<< paste SettingsScreen.jsx lines 13-182 VERBATIM here (the state,
  //     refresh/effects, handlers, the vault_ok===false early return, the
  //     first-run nudge early return, and the main return). Do not modify them. >>>
}
```

Verify by diffing: `ApiKeysPanel`'s body must be byte-identical to the old `SettingsScreen` body (lines 13-182). The vault-locked recovery card, the first-run nudge with the "Add keys" expand (`setEdits(all)`), and the integrations map all move together.

- [ ] **Step 2: Rewrite SettingsScreen as the tab shell**

Replace the entire contents of `frontend/src/screens/SettingsScreen.jsx` with:

```javascript
/* Scuffed OS — Settings shell (M9 Slice 1). Two tabs: Connectors (unified
   sign-in surface) and API keys (the M8 secrets UI, now ApiKeysPanel). The tab
   bar renders ABOVE ApiKeysPanel's vault-locked / first-run early returns so
   Connectors stays reachable even when the vault is locked or empty. */
import React from 'react'
import { ApiKeysPanel } from './ApiKeysPanel.jsx'
import { ConnectorsPanel } from './ConnectorsPanel.jsx'

const TABS = [
  { id: 'connectors', label: 'Connectors' },
  { id: 'keys', label: 'API keys' },
]

export function SettingsScreen({ tab = 'connectors', onTabChange }) {
  const active = tab === 'keys' ? 'keys' : 'connectors'
  return (
    <div className="kit-stack" style={{ gap: 'var(--gutter)' }}>
      <div role="tablist" className="kit-inline" style={{ gap: 4, borderBottom: '1px solid var(--paper-300)', paddingBottom: 0 }}>
        {TABS.map((t) => {
          const on = active === t.id
          return (
            <button
              key={t.id}
              role="tab"
              aria-selected={on}
              onClick={() => onTabChange && onTabChange(t.id)}
              style={{
                appearance: 'none', border: 'none', background: 'none', cursor: 'pointer',
                padding: '8px 14px', marginBottom: -1,
                fontFamily: 'var(--font-display)', fontSize: 'var(--text-sm)',
                color: on ? 'var(--text-strong)' : 'var(--text-muted)',
                borderBottom: on ? '2px solid var(--accent-text)' : '2px solid transparent',
              }}
            >
              {t.label}
            </button>
          )
        })}
      </div>
      {active === 'keys' ? <ApiKeysPanel /> : <ConnectorsPanel onOpenKeys={() => onTabChange && onTabChange('keys')} />}
    </div>
  )
}
```

- [ ] **Step 3: Add a temporary ConnectorsPanel stub so the build resolves**

Create `frontend/src/screens/ConnectorsPanel.jsx` as a stub (replaced fully in Task 7):

```javascript
/* Scuffed OS — Settings › Connectors panel (stub; real cards land in Task 7). */
import React from 'react'
import { Card } from '../components/ui.jsx'

export function ConnectorsPanel() {
  return <Card variant="flat"><p className="kit-muted">Connectors — coming in the next step.</p></Card>
}
```

- [ ] **Step 4: Build**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 5: Manual checklist (run the app; see the run-scuffedos skill)**

- [ ] Settings shows two tabs; **Connectors** is selected by default.
- [ ] **API keys** tab renders the existing secrets UI unchanged.
- [ ] With a **locked vault** (`vault_ok:false`), the API-keys tab shows the "Re-authenticate" card AND the **Connectors** tab is still selectable (the tab bar is not short-circuited).
- [ ] With **nothing configured**, the API-keys tab shows the first-run nudge, and its **Add keys** button still expands all key inputs (the M8 53cea3b behavior).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/screens/ApiKeysPanel.jsx frontend/src/screens/SettingsScreen.jsx frontend/src/screens/ConnectorsPanel.jsx
git commit -m "feat(connectors): Settings tab shell + ApiKeysPanel extraction (M9 s1 §7)"
```

---

## Task 7: ConnectorsPanel — the four connector cards

**Files:**
- Modify: `frontend/src/screens/ConnectorsPanel.jsx` (replace the stub with the real panel)

**Interfaces:**
- Consumes: `api.getConnectors()`, `api.settingsGetSecrets()` (for `vault_ok`), `api.oauthConnect(name)`, `api.oauthDisconnect(name)`, `api.moodleConnect({ token })`, `api.financeLinkStart(kind)`, `api.financeLinkComplete(linkToken)`, `api.financeReauthStart(itemId)`, `api.financeReauthComplete(itemId)`, `api.financeDisconnect(itemId)`. `ConnectorsPanel({ onOpenKeys })`.
- Produces: one card per connector (ordered google/whoop/moodle/plaid) with status chip, connected hint, and modality-specific actions; destructive disconnect behind an inline confirm; not-configured gating; a vault-locked warning strip.

**Behavior spec (§7 + verified transport):**
- Card set + order come straight from `getConnectors()` (backend already orders google/whoop/moodle/plaid).
- **Status chip:** Connected · Needs re-auth · Not connected.
- **Google/WHOOP:** Connect (or **Reconnect** when `needs_reauth`) calls `oauthConnect(name)` then the **card** navigates `window.location = authorize_url` (keep navigation at the card layer — Slice 2 swaps only this line for the system-browser opener). Disconnect calls `oauthDisconnect(name)` behind the destructive confirm. Google, when connected and `can_write_email === false`, shows an "Enable email actions" affordance that re-runs Connect (scope upgrade).
- **Moodle:** an inline password field + Connect calling `moodleConnect({ token })`; on `needs_reauth`, the same field with "paste a fresh key" copy. Reproduce SchoolScreen's wstoken help `<ol>` (SchoolScreen.jsx:96-102) so the guidance survives the form's deletion in Task 9. Disconnect calls `oauthDisconnect('moodle')` behind the confirm.
- **Plaid:** "Link bank account" / "Link investment account" call `financeLinkStart('bank'|'investments')` (note the plural `investments` — matches the existing kind value), open `hosted_link_url` in a new tab, then show a **manual "Finish linking" button** (the existing FinanceScreen pattern, ported verbatim): clicking it calls `financeLinkComplete(link_token)`, which returns 409 → "still waiting" until Plaid is done. One sub-row per `items[]` institution with its status chip, **Reconnect** (`financeReauthStart(item_id)` → open tab → same Finish-linking button → `financeReauthComplete(item_id)`), and **Disconnect** (`financeDisconnect(item_id)`, destructive confirm). (The automatic ~2s poll is Slice 2, §9 — not here.)
- **Not configured** (`configured === false`, Moodle exempt): Connect disabled with an "Add API keys first →" button calling `onOpenKeys`.
- **Vault locked** (`settingsGetSecrets().vault_ok === false`): render a warning strip — "OAuth connects need credentials the vault can't currently serve" — and disable OAuth/Plaid Connect (Moodle paste still works: it writes the DB, not the vault).
- **Destructive disconnect:** clicking Disconnect flips the card/row into an inline confirm naming the wiped data ("This deletes all synced <emails|grades|workouts|transactions for this account> from ScuffedOS."), with Disconnect / Cancel. No modal system.

- [ ] **Step 1: Replace the stub with the full panel**

Replace the entire contents of `frontend/src/screens/ConnectorsPanel.jsx` with:

```javascript
/* Scuffed OS — Settings › Connectors (M9 Slice 1). The single surface where all
   four sign-ins (Google, WHOOP, Moodle, Plaid) are connected, reconnected, and
   disconnected. Reads GET /api/connectors for state + settingsGetSecrets for
   vault_ok. Navigation to OAuth authorize URLs stays at the card layer so
   Slice 2 can swap only that one line for the system-browser opener. */
import React from 'react'
import { Card, Button } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'
import { api } from '../lib/api.js'

const WIPE_COPY = {
  google: 'all synced emails',
  whoop: 'all synced workouts and recovery data',
  moodle: 'all synced courses, grades and deadlines',
  plaid: 'all synced transactions for this account',
}

function StatusChip({ status }) {
  const map = {
    connected: ['Connected', 'var(--green-600)'],
    needs_reauth: ['Needs re-auth', 'var(--clay-600)'],
    not_connected: ['Not connected', 'var(--text-muted)'],
  }
  const [label, color] = map[status] || map.not_connected
  return <span className="kit-muted" style={{ fontSize: 'var(--text-sm)', color }}>{label}</span>
}

// Open an OAuth/hosted-link URL. Slice 2 swaps this single function for the
// Tauri system-browser opener under isTauri().
function openExternal(url, { sameWindow = false } = {}) {
  if (sameWindow) window.location = url
  else window.open(url, '_blank', 'noopener')
}

export function ConnectorsPanel({ onOpenKeys }) {
  const [connectors, setConnectors] = React.useState(null)
  const [vaultOk, setVaultOk] = React.useState(true)
  const [error, setError] = React.useState('')
  const [busy, setBusy] = React.useState('')          // name/item currently acting
  const [confirming, setConfirming] = React.useState('')  // name or item_id awaiting confirm
  const [moodleToken, setMoodleToken] = React.useState('')
  const [pendingLink, setPendingLink] = React.useState(null)  // {link_token} | {reauthItemId} after a Plaid button
  const [linkMsg, setLinkMsg] = React.useState('')

  const refresh = React.useCallback(() => {
    api.getConnectors()
      .then((c) => { setConnectors(c); setError('') })
      .catch((e) => setError(e?.message || 'Failed to load connectors'))
    api.settingsGetSecrets()
      .then((s) => setVaultOk(s.vault_ok !== false))
      .catch(() => setVaultOk(true))
  }, [])

  React.useEffect(() => { refresh() }, [refresh])

  const connectOAuth = (name) => {
    setBusy(name)
    api.oauthConnect(name)
      .then((r) => openExternal(r.authorize_url, { sameWindow: true }))
      .catch((e) => { setError(e?.message || 'Connect failed'); setBusy('') })
  }

  const disconnectOAuth = (name) => {
    setBusy(name)
    api.oauthDisconnect(name)
      .then(() => { setConfirming(''); refresh() })
      .catch((e) => setError(e?.message || 'Disconnect failed'))
      .finally(() => setBusy(''))
  }

  const connectMoodle = () => {
    if (!moodleToken.trim()) return
    setBusy('moodle')
    api.moodleConnect({ token: moodleToken.trim() })
      .then(() => { setMoodleToken(''); refresh() })
      .catch((e) => setError(e?.message || 'Moodle connect failed'))
      .finally(() => setBusy(''))
  }

  // Plaid uses the EXISTING manual "Finish linking" pattern (ported verbatim
  // from FinanceScreen — NOT an auto-poll): open the hosted tab, the user
  // finishes there, then clicks Finish linking; link/complete returns 409 until
  // Plaid is done, surfaced as a "still waiting" message (ApiError.status===409).
  const startLink = (kind) => {
    setLinkMsg('')
    api.financeLinkStart(kind).then((r) => {
      if (r?.hosted_link_url) {
        openExternal(r.hosted_link_url)
        setPendingLink({ link_token: r.link_token })
        setLinkMsg('Finish linking in the Plaid tab, then click “Finish linking”.')
      }
    }).catch((e) => setError(e?.message || 'Could not start the link flow'))
  }
  const reauthItem = (itemId) => {
    setLinkMsg('')
    api.financeReauthStart(itemId).then((r) => {
      if (r?.hosted_link_url) {
        openExternal(r.hosted_link_url)
        setPendingLink({ reauthItemId: itemId })
        setLinkMsg('Finish reconnecting in the Plaid tab, then click “Finish linking”.')
      }
    }).catch((e) => setError(e?.message || 'Could not start reconnect'))
  }
  const finishLink = () => {
    if (!pendingLink) return
    const done = pendingLink.reauthItemId
      ? api.financeReauthComplete(pendingLink.reauthItemId)
      : api.financeLinkComplete(pendingLink.link_token)
    done.then(() => { setPendingLink(null); setLinkMsg(''); refresh() })
      .catch((e) => setLinkMsg(e?.status === 409
        ? 'Still waiting — finish in the Plaid tab, then try again.'
        : 'Linking failed. Try again.'))
  }

  if (error && !connectors) {
    return <Card variant="flat"><p className="kit-row__title">{error}</p></Card>
  }
  if (!connectors) {
    return <Card variant="flat"><p className="kit-muted">Loading connectors…</p></Card>
  }

  const connectDisabled = (c) => busy === c.name || (c.auth_kind !== 'token' && (!c.configured || !vaultOk))

  return (
    <div className="kit-stack" style={{ gap: 'var(--gutter)' }}>
      {error && (
        <Card variant="flat" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Icon name="alert-triangle" /><p className="kit-row__title">{error}</p>
        </Card>
      )}
      {!vaultOk && (
        <Card variant="flat" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Icon name="alert-triangle" />
          <p className="kit-muted">The secrets vault can’t be unlocked on this machine, so OAuth
            connects are disabled until you re-enter keys in the API keys tab. Moodle (paste-token) still works.</p>
        </Card>
      )}

      {connectors.map((c) => (
        <Card
          key={c.name}
          title={c.label}
          action={<StatusChip status={c.status} />}
        >
          <div className="kit-stack" style={{ marginTop: 4, gap: 12 }}>
            {c.connected_at && (
              <p className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>
                Connected {new Date(c.connected_at).toLocaleDateString()}
                {c.provider_user_id ? ` · ${c.provider_user_id}` : ''}
              </p>
            )}

            {/* Not-configured gate (OAuth/Plaid only; Moodle exempt) */}
            {c.auth_kind !== 'token' && !c.configured && (
              <div className="kit-inline" style={{ gap: 8, alignItems: 'center' }}>
                <span className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>API keys required.</span>
                <Button variant="secondary" size="sm" onClick={onOpenKeys}>Add API keys first →</Button>
              </div>
            )}

            {/* OAuth connectors: Google / WHOOP */}
            {c.auth_kind === 'oauth' && (
              <div className="kit-inline" style={{ gap: 8 }}>
                {c.status === 'not_connected' && (
                  <Button variant="primary" size="sm" disabled={connectDisabled(c)}
                    onClick={() => connectOAuth(c.name)}>Connect</Button>
                )}
                {c.status === 'needs_reauth' && (
                  <Button variant="primary" size="sm" disabled={connectDisabled(c)}
                    onClick={() => connectOAuth(c.name)}>Reconnect</Button>
                )}
                {c.status === 'connected' && c.name === 'google' && c.can_write_email === false && (
                  <Button variant="secondary" size="sm" disabled={connectDisabled(c)}
                    onClick={() => connectOAuth(c.name)}>Enable email actions</Button>
                )}
                {c.status !== 'not_connected' && confirming !== c.name && (
                  <Button variant="secondary" size="sm" disabled={busy === c.name}
                    onClick={() => setConfirming(c.name)}>Disconnect</Button>
                )}
              </div>
            )}

            {/* Token connector: Moodle */}
            {c.auth_kind === 'token' && (
              <div className="kit-stack" style={{ gap: 8 }}>
                {c.status !== 'connected' && (
                  <>
                    <p className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>
                      {c.status === 'needs_reauth' ? 'Your key expired — paste a fresh one.' : 'Paste your Moodle security key (wstoken).'}
                    </p>
                    <ol className="kit-muted" style={{ fontSize: 'var(--text-sm)', margin: 0, paddingLeft: 18, lineHeight: 1.6 }}>
                      <li>Open Moodle → your profile → <b>Preferences</b> → <b>Security keys</b>.</li>
                      <li>Copy the key for the <b>Moodle mobile web service</b>.</li>
                      <li>Paste it below and Connect.</li>
                    </ol>
                    <div className="kit-inline" style={{ gap: 8 }}>
                      <input type="password" autoComplete="off" placeholder="Paste wstoken"
                        value={moodleToken} onChange={(e) => setMoodleToken(e.target.value)}
                        style={{ flex: 1, padding: '8px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--paper-300)', fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)' }} />
                      <Button variant="primary" size="sm" disabled={busy === 'moodle' || !moodleToken.trim()}
                        onClick={connectMoodle}>Connect</Button>
                    </div>
                  </>
                )}
                {c.status === 'connected' && confirming !== c.name && (
                  <div className="kit-inline"><Button variant="secondary" size="sm"
                    onClick={() => setConfirming(c.name)}>Disconnect</Button></div>
                )}
              </div>
            )}

            {/* Link connector: Plaid (manual Finish-linking pattern) */}
            {c.auth_kind === 'link' && (
              <div className="kit-stack" style={{ gap: 10 }}>
                <div className="kit-inline" style={{ gap: 8 }}>
                  <Button variant="primary" size="sm" disabled={connectDisabled(c)}
                    onClick={() => startLink('bank')}>Link bank account</Button>
                  <Button variant="secondary" size="sm" disabled={connectDisabled(c)}
                    onClick={() => startLink('investments')}>Link investment account</Button>
                </div>
                {pendingLink && (
                  <div className="kit-inline" style={{ gap: 8, alignItems: 'center' }}>
                    <Button variant="primary" size="sm" iconLeft={<Icon name="check" />} onClick={finishLink}>Finish linking</Button>
                    {linkMsg && <span className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>{linkMsg}</span>}
                  </div>
                )}
                {c.items.map((it) => (
                  <div key={it.item_id} className="kit-inline" style={{ justifyContent: 'space-between', alignItems: 'center', gap: 8, borderTop: '1px solid var(--paper-200)', paddingTop: 8 }}>
                    <div>
                      <span className="kit-row__title" style={{ fontSize: 'var(--text-sm)' }}>{it.institution_name}</span>{' '}
                      <StatusChip status={it.status} />
                    </div>
                    {confirming === it.item_id ? (
                      <div className="kit-inline" style={{ gap: 6 }}>
                        <span className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>Delete this account’s transactions?</span>
                        <Button variant="primary" size="sm" disabled={busy === it.item_id}
                          onClick={() => { setBusy(it.item_id); api.financeDisconnect(it.item_id).then(() => { setConfirming(''); refresh() }).catch((e) => setError(e?.message || 'Disconnect failed')).finally(() => setBusy('')) }}>Disconnect</Button>
                        <Button variant="secondary" size="sm" onClick={() => setConfirming('')}>Cancel</Button>
                      </div>
                    ) : (
                      <div className="kit-inline" style={{ gap: 6 }}>
                        {it.status === 'needs_reauth' && (
                          <Button variant="secondary" size="sm" onClick={() => reauthItem(it.item_id)}>Reconnect</Button>
                        )}
                        <Button variant="secondary" size="sm" onClick={() => setConfirming(it.item_id)}>Disconnect</Button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {/* Destructive confirm for connector-level (google/whoop/moodle) disconnect */}
            {confirming === c.name && (
              <Card variant="flat" style={{ background: 'var(--clay-100)' }}>
                <p className="kit-row__title" style={{ fontSize: 'var(--text-sm)' }}>
                  This deletes {WIPE_COPY[c.name]} from ScuffedOS.
                </p>
                <div className="kit-inline" style={{ gap: 8, marginTop: 8 }}>
                  <Button variant="primary" size="sm" disabled={busy === c.name}
                    onClick={() => disconnectOAuth(c.name)}>Disconnect</Button>
                  <Button variant="secondary" size="sm" onClick={() => setConfirming('')}>Cancel</Button>
                </div>
              </Card>
            )}
          </div>
        </Card>
      ))}
    </div>
  )
}
```

*(Note: Moodle disconnect reuses `oauthDisconnect('moodle')` — Moodle is a registered OAuthProvider on the shared router; `disconnectOAuth` already routes there.)*

- [ ] **Step 2: Build**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 3: Manual checklist**

- [ ] Four cards render in order Google, WHOOP, Moodle, Plaid, each with a status chip.
- [ ] With no creds: Google/WHOOP/Plaid Connect is disabled with "Add API keys first →" (clicking switches to the API keys tab); Moodle shows the paste field + wstoken help.
- [ ] Connecting Google navigates to the consent URL; after consent the callback page says "close this tab"; returning to the tab and refreshing shows Connected.
- [ ] Plaid: "Link bank account" opens the hosted tab and reveals a "Finish linking" button; clicking it before finishing shows "Still waiting…"; after finishing, the institution appears as a sub-row with a status chip + Reconnect/Disconnect.
- [ ] Disconnect shows the inline confirm naming the wiped data; Cancel dismisses; Disconnect clears the card to Not connected.
- [ ] With a locked vault: the warning strip shows and OAuth/Plaid Connect is disabled; the Moodle paste field is still usable.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/screens/ConnectorsPanel.jsx
git commit -m "feat(connectors): ConnectorsPanel — four connector cards + destructive confirm (M9 s1 §7)"
```

---

## Task 8: EmailScreen + FitnessScreen slim down (§8)

**Files:**
- Create: `frontend/src/components/ConnectorEmptyState.jsx`
- Modify: `frontend/src/screens/EmailScreen.jsx`, `frontend/src/screens/FitnessScreen.jsx`

**Interfaces:**
- Produces: `NotConnectedCard({ icon, title, blurb, onOpenConnectors })` and `NeedsReauthBanner({ onOpenConnectors })` — the two shared replacements for every deleted connect block.
- Consumes: `onOpenConnectors` prop (threaded in Task 5; each screen must now destructure it).

**Rule (§8):** each screen keys its empty/needs_reauth state on its **own** provider entry — Email(google)/School(moodle)/Finance(Plaid) already do; **only FitnessScreen keys on the aggregate `connected` flag (line 50) and must switch to its own `whoop` entry.** Do NOT "fix" the others. Each deleted not-connected early return must be *replaced* by an empty-state in the same slot, or the connected render falls through and crashes on null data.

- [ ] **Step 1: Create the shared empty-state component**

Create `frontend/src/components/ConnectorEmptyState.jsx`:

```javascript
/* Scuffed OS — shared connector empty/needs-reauth states (M9 Slice 1). Data
   screens render these in place of their old inline connect UI; both deep-link
   to Settings › Connectors via onOpenConnectors. */
import React from 'react'
import { Card, Button } from './ui.jsx'
import { Icon } from '../lib/Icon.jsx'

export function NotConnectedCard({ icon = 'unplug', title, blurb, onOpenConnectors }) {
  return (
    <Card variant="flat" style={{ textAlign: 'center', padding: '48px 24px' }}>
      <div style={{ display: 'inline-flex', width: 56, height: 56, borderRadius: 'var(--radius-lg)', background: 'var(--accent-soft)', color: 'var(--accent-text)', alignItems: 'center', justifyContent: 'center', marginBottom: 14 }}>
        <Icon name={icon} />
      </div>
      <h3 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-xl)', color: 'var(--text-strong)', margin: '0 0 6px' }}>{title}</h3>
      <p className="kit-muted" style={{ maxWidth: 380, margin: '0 auto 18px' }}>{blurb}</p>
      <Button variant="primary" iconLeft={<Icon name="settings" />} onClick={onOpenConnectors}>
        Set up in Settings › Connectors
      </Button>
    </Card>
  )
}

export function NeedsReauthBanner({ onOpenConnectors }) {
  return (
    <Card variant="flat" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
      <span className="kit-statline__ico" style={{ background: 'var(--clay-100)', color: 'var(--clay-600)' }}>
        <Icon name="alert-triangle" />
      </span>
      <p className="kit-muted" style={{ flex: 1 }}>Connection needs re-authorizing — fix it in Settings › Connectors.</p>
      <Button variant="secondary" size="sm" onClick={onOpenConnectors}>Open Connectors</Button>
    </Card>
  )
}
```

- [ ] **Step 2: EmailScreen — accept the prop, delete the connect UI, add the empty/reauth/read-only states**

In `frontend/src/screens/EmailScreen.jsx` (read + confirm ranges before editing — verified against the tree):
1. Change the signature `export function EmailScreen()` → `export function EmailScreen({ onOpenConnectors })`.
2. Add the import: `import { NotConnectedCard, NeedsReauthBanner } from '../components/ConnectorEmptyState.jsx'`.
3. **Delete** `connect()` (line 93).
4. **Delete** the not-connected CTA card block (lines 208-219) and, in its early-return slot, render:
   ```javascript
   <NotConnectedCard title="Email isn’t connected"
     blurb="Connect your Google account to see and act on your inbox here."
     onOpenConnectors={onOpenConnectors} icon="mail" />
   ```
5. **Delete** the needs_reauth banner + enable-write banner block (lines 280-300). Replace with: the one-line `<NeedsReauthBanner onOpenConnectors={onOpenConnectors} />` for the needs_reauth case, and — for the connected-but-read-only case (`canWrite === false`) — a one-line banner:
   ```javascript
   <Card variant="flat" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
     <Icon name="pen-line" />
     <p className="kit-muted" style={{ flex: 1 }}>Email actions are read-only — enable them in Settings › Connectors.</p>
     <Button variant="secondary" size="sm" onClick={onOpenConnectors}>Open Connectors</Button>
   </Card>
   ```
   **Preserve** the `canWrite` derivation (line 55) and its other three usages (lines 244 compose overlay, 325 Compose button, 357 reply/forward bar) — only the :291 enable-write banner is removed.

- [ ] **Step 3: FitnessScreen — accept the prop, switch off the aggregate flag, delete the connect UI**

In `frontend/src/screens/FitnessScreen.jsx`:
1. `export function FitnessScreen()` → `export function FitnessScreen({ onOpenConnectors })`; add the `ConnectorEmptyState` import.
2. **Change line 50** from the aggregate `const connected = !!status?.connected` to its own WHOOP entry:
   ```javascript
   const whoop = status?.providers?.find((p) => p.provider === 'whoop')
   const connected = !!whoop
   const needsReauth = whoop?.status === 'needs_reauth'
   ```
3. **Delete** `connect()` and `disconnect()` handlers — lines **56-65** (connect 56-60, disconnect 61-65; the closing `}` is on line 65 — deleting only 56-64 orphans it). `sync()` at line 66 stays.
4. **Delete** the not-connected CTA block (lines 101-112); render `<NotConnectedCard title="Fitness isn’t connected" blurb="Connect WHOOP to see recovery, sleep, strain and workouts." onOpenConnectors={onOpenConnectors} icon="activity" />` in its slot.
5. **Delete** the needs_reauth banner block (lines 123-132); render `<NeedsReauthBanner onOpenConnectors={onOpenConnectors} />` when `needsReauth`.
6. **Delete** the disconnect `IconButton` on line 152 — but **preserve** the Sync `IconButton` on line 151 in the same action block (surgical single-line delete).
7. **Preserve** the vitals/rings derivation (lines 114-119).

- [ ] **Step 4: Build**

Run: `cd frontend && npm run build`
Expected: build succeeds with no unused-variable errors (confirm no orphaned `connect`/`disconnect` references remain).

- [ ] **Step 5: Manual checklist**

- [ ] EmailScreen not-connected → the empty-state card; its button opens Settings › Connectors.
- [ ] EmailScreen connected + read-only → the "Email actions are read-only" banner; Compose/reply still work when write is enabled.
- [ ] FitnessScreen not-connected → empty-state; needs_reauth → the one-line banner; connected → rings/vitals render; the Sync button still works and there is no Disconnect button on the screen.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ConnectorEmptyState.jsx frontend/src/screens/EmailScreen.jsx frontend/src/screens/FitnessScreen.jsx
git commit -m "feat(connectors): Email + Fitness screens deep-link to Connectors (M9 s1 §8)"
```

---

## Task 9: SchoolScreen + FinanceScreen slim down (§8)

**Files:**
- Modify: `frontend/src/screens/SchoolScreen.jsx`, `frontend/src/screens/FinanceScreen.jsx`

**Interfaces:** consumes `onOpenConnectors` (threaded in Task 5) + `NotConnectedCard`/`NeedsReauthBanner` (Task 8).

**FinanceScreen deletion is the trap-heavy one (verified against the tree — the spec's §8 ranges are incomplete here):**
- Handler deletion `49-79 minus sync()` is **non-contiguous**: `sync()` is line **78**. Delete **49-77 AND 79**, skipping 78.
- The `<span>` at lines 130-133 wraps two buttons: line **131 is the "Add" button** wired to the deleted `startLink('bank')` — **delete line 131** too, keeping the span wrapper (130,133) and the Sync button (132).
- Two orphaned JSX consts NOT in the spec's ranges: `ConnectButtons` (lines 89-94) and `FinishLink` (lines 95-100) reference the deleted `startLink`/`finishLink` and are used only by deleted UI — **delete both** or the build breaks.
- Dead state after deletion: `pendingLink`/`linkMsg` (lines 28-29) and `needsReauth` (line 47) — remove them.

- [ ] **Step 1: SchoolScreen — accept the prop, delete the paste form + reauth cards**

In `frontend/src/screens/SchoolScreen.jsx` (read + confirm ranges first):
1. `export function SchoolScreen()` → `export function SchoolScreen({ onOpenConnectors })`; add the `ConnectorEmptyState` import.
2. **Delete** `connect()` (line 58) and the now-dead `token`/`connectError` state (lines 27-28).
3. **Delete** the paste-key form block (lines 73-105). Render in its slot `<NotConnectedCard title="School isn’t connected" blurb="Connect Moodle to see your courses, deadlines and grades." onOpenConnectors={onOpenConnectors} icon="graduation-cap" />`. (The wstoken help `<ol>` that lived at 96-102 was already reproduced in the Connectors Moodle card in Task 7 — it is safe to delete here.)
4. **Delete** the double reauth cards (lines 120-146); render `<NeedsReauthBanner onOpenConnectors={onOpenConnectors} />` when `needsReauth`.
5. **Decide the needs_reauth pane gate** (line 159, currently `{!syncing && !needsReauth && (...)}`): keep it as-is so a needs_reauth connection shows only the banner (matches today's behavior — panes hidden during needs_reauth). Do not widen it.

- [ ] **Step 2: FinanceScreen — accept the prop, surgical deletes, preserve sync()**

In `frontend/src/screens/FinanceScreen.jsx` (read + confirm every range first — the deletes are non-contiguous):
1. `export function FinanceScreen()` → `export function FinanceScreen({ onOpenConnectors })`; add the `ConnectorEmptyState` import.
2. **Delete** the handlers on lines **49-77 and 79** (`startLink`, `reauth`, `finishLink`, `disconnect`) — **skip line 78 (`sync()` — preserve)**.
3. **Delete** the orphaned JSX consts `ConnectButtons` (89-94) and `FinishLink` (95-100).
4. **Delete** the dead state `pendingLink`/`linkMsg` (28-29) and `needsReauth` (47).
5. **Delete** the not-connected connect card (lines 103-116); render `<NotConnectedCard title="Finance isn’t connected" blurb="Link a bank or investment account to see balances, transactions and budgets." onOpenConnectors={onOpenConnectors} icon="wallet" />` in its slot.
6. **Delete** the per-item Reconnect/Disconnect chips (lines 126-127) and the pendingLink/finish + inline needs_reauth block (lines 135-145). For needs_reauth, render `<NeedsReauthBanner onOpenConnectors={onOpenConnectors} />`.
7. In the span at lines 130-133: **delete line 131 (the "Add" button)**; **preserve** the span wrapper and the Sync button (line 132) + `sync()`.

- [ ] **Step 3: Build**

Run: `cd frontend && npm run build`
Expected: build succeeds — no references to `startLink`/`finishLink`/`reauth`/`disconnect`/`ConnectButtons`/`FinishLink`/`pendingLink`/`linkMsg`/`needsReauth` remain in FinanceScreen; no `connect`/`token`/`connectError` remain in SchoolScreen.

- [ ] **Step 4: Manual checklist**

- [ ] SchoolScreen not-connected → empty-state; needs_reauth → banner only (panes hidden as before); connected → courses/deadlines/grades render.
- [ ] FinanceScreen not-connected → empty-state; connected → balances/transactions/budgets render and the **Sync** button still works; there is no per-item Add/Reconnect/Disconnect UI on the screen (that lives in the Connectors tab now).
- [ ] From each of the four data screens, the "Set up in Settings › Connectors" button lands on the Connectors tab.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/screens/SchoolScreen.jsx frontend/src/screens/FinanceScreen.jsx
git commit -m "feat(connectors): School + Finance screens deep-link to Connectors (M9 s1 §8)"
```

---

## Final acceptance (spec §16, Slice 1)

Run once all tasks are complete:

- [ ] `cd backend && python -m pytest` → all green; report the count (baseline 674/1 + the connectors additions − 2 deleted string tests).
- [ ] `cd frontend && npm run build` → green.
- [ ] From a fresh DB in dev: all four connectors appear in Settings › Connectors as **Not connected**; each can be connected (post-consent landing = the §6a HTML page, then return to the app), re-authed, and disconnected (with the destructive confirm) entirely from the tab; the four data screens show empty states keyed on their own provider; **no data-screen connect UI remains**.
- [ ] Update `MEMORY.md` / the Scuffed OS implementation memory: M9 Slice 1 executed (branch, commit, suite count); Slice 2/3 still to plan.
