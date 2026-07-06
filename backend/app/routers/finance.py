"""Finance API (M7 Plaid): Hosted-Link connect + DB-only reads + local budget
writes. Reads serve the finance_* tables only (never a live Plaid call).
Connect is a two-step Hosted-Link handshake (start -> user finishes on Plaid's
page -> complete), so it lives here, not on the shared /api/oauth/* router.
The app never writes to a bank — budgets are the only mutation, and they're local.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from .. import finance_sync, providers
from ..providers.plaid import PlaidAuthError, PlaidError
from ..schemas import (
    AccountsOut, BillOut, BudgetOut, BudgetReallocate, BudgetsUpdate, FinanceStatus,
    FinanceSummary, HoldingOut, InvestmentTxnOut, LinkComplete, LinkStart, LinkStartOut,
    ReauthStartOut, SubscriptionOut, TransactionOut,
)
from ..store import store

router = APIRouter(prefix="/api/finance", tags=["finance"])
logger = logging.getLogger("scuffed_os.finance")


def _this_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


@router.post("/link/start", response_model=LinkStartOut)
def link_start(payload: LinkStart) -> dict:
    """Mint a Hosted-Link token for the chosen kind (bank -> transactions;
    investments -> investments). The client opens hosted_link_url in a new tab."""
    provider = providers.get("plaid")
    if provider is None:
        raise HTTPException(status_code=502, detail="Plaid is unavailable")
    try:
        data = provider.create_link_token(payload.kind)
    except (PlaidError, PlaidAuthError) as exc:
        logger.warning("plaid link/start failed: %s", exc)
        raise HTTPException(status_code=502, detail="Plaid rejected the request") from exc
    return {"hosted_link_url": data.get("hosted_link_url", ""),
            "link_token": data.get("link_token", "")}


@router.post("/link/complete", response_model=FinanceStatus)
def link_complete(payload: LinkComplete) -> dict:
    """Poll the Hosted-Link session for the public_token, exchange it, store the
    Item server-side, and kick one sync. 409 if the user hasn't finished yet."""
    provider = providers.get("plaid")
    if provider is None:
        raise HTTPException(status_code=502, detail="Plaid is unavailable")
    try:
        public_token = provider.get_link_public_token(payload.link_token)
    except (PlaidError, PlaidAuthError) as exc:
        logger.warning("plaid link/complete poll failed: %s", exc)
        raise HTTPException(status_code=502, detail="Plaid rejected the request") from exc
    if not public_token:
        raise HTTPException(status_code=409, detail="Link not finished yet")
    try:
        access_token, _item_id = provider.exchange_public_token(public_token)
        item = provider.get_item(access_token)
    except (PlaidError, PlaidAuthError) as exc:
        logger.warning("plaid link/complete exchange failed: %s", exc)
        raise HTTPException(status_code=502, detail="Plaid rejected the request") from exc
    if not item.products:
        item.products = ["transactions"]
    store.upsert_finance_item(item, access_token)
    finance_sync.tick()
    return store.finance_status()


@router.get("/status", response_model=FinanceStatus)
def status() -> dict:
    """Linked institutions + connection state. No tokens/cursors serialized."""
    return store.finance_status()


@router.get("/summary", response_model=FinanceSummary)
def summary(month: str | None = Query(default=None)) -> dict:
    return store.finance_summary(month)


@router.get("/accounts", response_model=AccountsOut)
def accounts() -> dict:
    return {"accounts": store.list_finance_accounts(), "networth": store.finance_networth()}


@router.get("/transactions", response_model=list[TransactionOut])
def transactions(days: int | None = Query(default=None),
                 account_id: str | None = Query(default=None),
                 category: str | None = Query(default=None)) -> list[dict]:
    return store.finance_transactions(days, account_id, category)


@router.get("/holdings", response_model=list[HoldingOut])
def holdings() -> list[dict]:
    return store.finance_holdings()


@router.get("/subscriptions", response_model=list[SubscriptionOut])
def subscriptions() -> list[dict]:
    return store.finance_subscriptions()


@router.get("/bills", response_model=list[BillOut])
def bills() -> list[dict]:
    return store.finance_bills()


@router.get("/investment-transactions", response_model=list[InvestmentTxnOut])
def investment_transactions(days: int | None = Query(default=None)) -> list[dict]:
    return store.finance_investment_transactions(days)


@router.get("/budgets", response_model=list[BudgetOut])
def budgets(month: str | None = Query(default=None)) -> list[dict]:
    return store.finance_budgets(month or _this_month())


@router.put("/budgets", response_model=list[BudgetOut])
def save_budgets(payload: BudgetsUpdate) -> list[dict]:
    return store.upsert_budgets(payload.month, [b.model_dump() for b in payload.budgets])


@router.post("/budgets/reallocate", response_model=list[BudgetOut])
def reallocate(payload: BudgetReallocate) -> list[dict]:
    return store.reallocate_budget(payload.month, payload.from_category,
                                   payload.to_category, payload.amount)


@router.post("/items/{item_id}/disconnect", response_model=FinanceStatus)
def disconnect(item_id: str) -> dict:
    """Remove one linked Item at Plaid (best-effort) then delete its local data.
    Deletion is the user-facing guarantee, so a failed remote remove never blocks it."""
    provider = providers.get("plaid")
    token = store.get_finance_item_token(item_id)
    if token and provider is not None:
        try:
            provider.remove_item(token)
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.warning("plaid remove_item failed for %s, deleting anyway: %s", item_id, exc)
    if not store.delete_finance_item(item_id):
        raise HTTPException(status_code=404, detail=f"No linked item '{item_id}'")
    return store.finance_status()


@router.post("/items/{item_id}/reauth/start", response_model=ReauthStartOut)
def reauth_start(item_id: str) -> dict:
    """Mint an update-mode Hosted Link to repair an expired Item in place."""
    provider = providers.get("plaid")
    if provider is None:
        raise HTTPException(status_code=502, detail="Plaid is unavailable")
    token = store.get_finance_item_token(item_id)
    if not token:
        raise HTTPException(status_code=404, detail=f"No linked item '{item_id}'")
    item = store.get_finance_item(item_id)
    kind = "investments" if (item and item.get("products") == ["investments"]) else "bank"
    try:
        data = provider.create_link_token(kind, access_token=token)
    except (PlaidError, PlaidAuthError) as exc:
        logger.warning("plaid reauth/start failed: %s", exc)
        raise HTTPException(status_code=502, detail="Plaid rejected the request") from exc
    return {"hosted_link_url": data.get("hosted_link_url", ""),
            "link_token": data.get("link_token", "")}


@router.post("/items/{item_id}/reauth/complete", response_model=FinanceStatus)
def reauth_complete(item_id: str) -> dict:
    """Optimistically mark the Item active and sync. If reauth didn't actually
    succeed, the next tick re-flips it to needs_reauth."""
    if store.get_finance_item(item_id) is None:
        raise HTTPException(status_code=404, detail=f"No linked item '{item_id}'")
    store.set_finance_item_status(item_id, "active")
    finance_sync.tick()
    return store.finance_status()


@router.post("/sync")
def sync_now() -> dict:
    """Run one finance sync pass now. Reads never depend on it."""
    count = finance_sync.tick()
    return {"synced": count, "items": [i["item_id"] for i in store.list_finance_items()]}
