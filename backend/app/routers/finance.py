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
    AccountsOut, BudgetOut, BudgetReallocate, BudgetsUpdate, FinanceStatus,
    FinanceSummary, HoldingOut, LinkComplete, LinkStart, LinkStartOut, TransactionOut,
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
