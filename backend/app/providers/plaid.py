"""PlaidProvider — read-only, hand-rolled Plaid REST over httpx (no vendor SDK,
repo rule). Plaid field/endpoint names are confined to THIS module; everything
past it speaks the normalized dataclasses in base.py.

NOT an OAuthProvider: connecting is Hosted Link (a token exchange, no redirect
code flow), and there is no refresh (access tokens are long-lived). Multi-Item:
every data method takes one Item's access_token. Plaid returns errors as HTTP
4xx JSON with an `error_code`; auth codes (ITEM_LOGIN_REQUIRED, …) raise
PlaidAuthError (an AuthError subclass) which finance_sync turns into an Item's
status='needs_reauth'; other codes raise PlaidError (a RuntimeError).

The http layer is a test seam mirroring moodle.py/google.py: configure(
fake_http=obj) installs a fake exposing .post(url, json=...); configure()
restores the lazy real httpx.Client.

[confirm-against-live] — endpoint paths, personal_finance_category values,
security `type` values, account subtypes, and the Hosted-Link result shape in
get_link_public_token are confirmed at the live gate; the constant NAMES are
frozen by the interface contract.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, InvalidOperation

from ..config import settings
from .base import (
    AuthError,
    NormalizedAccount,
    NormalizedHolding,
    NormalizedItem,
    NormalizedSecurity,
    NormalizedTransaction,
    TransactionsDelta,
)

log = logging.getLogger("scuffed_os.plaid")

# Endpoint paths (Plaid REST).
LINK_TOKEN_CREATE = "/link/token/create"
LINK_TOKEN_GET = "/link/token/get"
ITEM_PUBLIC_TOKEN_EXCHANGE = "/item/public_token/exchange"
ITEM_GET = "/item/get"
INSTITUTIONS_GET_BY_ID = "/institutions/get_by_id"
ACCOUNTS_GET = "/accounts/get"
TRANSACTIONS_SYNC = "/transactions/sync"
INVESTMENTS_HOLDINGS_GET = "/investments/holdings/get"
ITEM_REMOVE = "/item/remove"

# Plaid error_codes that mean "this Item needs the user to re-auth" -> needs_reauth.
_AUTH_ERRORCODES = frozenset({
    "ITEM_LOGIN_REQUIRED", "INVALID_ACCESS_TOKEN", "INVALID_CREDENTIALS",
    "ITEM_LOCKED", "USER_SETUP_REQUIRED", "PENDING_EXPIRATION", "ACCESS_NOT_GRANTED",
})

# kind -> (required products, additional_consented_products). A bank consents to
# investments too, so a bank+brokerage login surfaces holdings.
_PRODUCTS_FOR_KIND = {
    "bank": (["transactions"], ["investments"]),
    "investments": (["investments"], []),
}

_INTEREST_PRODUCTS = ("transactions", "investments")


def _dec(x) -> Decimal | None:
    if x is None:
        return None
    try:
        return Decimal(str(x))
    except (InvalidOperation, ValueError):
        return None


def _date(x) -> date | None:
    if not x:
        return None
    try:
        return date.fromisoformat(str(x)[:10])
    except ValueError:
        return None


class PlaidError(RuntimeError):
    """Non-auth Plaid error (finance_sync logs-and-skips)."""


class PlaidAuthError(AuthError):
    """Item-auth Plaid error (error_code in _AUTH_ERRORCODES) -> needs_reauth."""


class PlaidProvider:
    name = "plaid"   # NO `kind` attr — excluded from pull_providers (like Moodle/Google)

    def __init__(self) -> None:
        self._http: object | str = "unset"
        self._client = None

    # ---- http seam ----
    def configure(self, fake_http: object | str = "unset") -> None:
        self._http = fake_http
        self._client = None

    def _transport(self):
        if self._http != "unset":
            return self._http
        if self._client is None:
            import httpx
            self._client = httpx.Client(timeout=20.0)
        return self._client

    def _host(self) -> str:
        env = settings.plaid_env if settings.plaid_env in ("sandbox", "production") else "production"
        return f"https://{env}.plaid.com"

    def _call(self, path: str, payload: dict) -> dict:
        body = {"client_id": settings.plaid_client_id, "secret": settings.plaid_secret, **payload}
        res = self._transport().post(f"{self._host()}{path}", json=body)
        status = getattr(res, "status_code", 200)
        data = res.json() or {}
        if status >= 400:
            code = data.get("error_code", "")
            msg = data.get("error_message") or code or f"HTTP {status}"
            if code in _AUTH_ERRORCODES:
                raise PlaidAuthError(f"{code}: {msg}")
            raise PlaidError(f"{code}: {msg}")
        return data

    # ---- connect (Hosted Link) ----
    def create_link_token(self, kind: str) -> dict:
        products, additional = _PRODUCTS_FOR_KIND.get(kind, _PRODUCTS_FOR_KIND["bank"])
        payload = {
            "client_name": "Scuffed OS",
            "language": "en",
            "country_codes": list(settings.plaid_country_codes),
            "user": {"client_user_id": settings.owner},
            "products": products,
            "hosted_link": {},
        }
        if additional:
            payload["additional_consented_products"] = additional
        data = self._call(LINK_TOKEN_CREATE, payload)
        return {
            "link_token": data.get("link_token", ""),
            "hosted_link_url": data.get("hosted_link_url", ""),
            "expiration": data.get("expiration"),
        }

    def exchange_public_token(self, public_token: str) -> tuple[str, str]:
        data = self._call(ITEM_PUBLIC_TOKEN_EXCHANGE, {"public_token": public_token})
        return data.get("access_token", ""), data.get("item_id", "")

    def get_item(self, access_token: str) -> NormalizedItem:
        data = self._call(ITEM_GET, {"access_token": access_token})
        item = data.get("item") or {}
        inst_id = item.get("institution_id") or ""
        supported = set(item.get("billed_products") or []) | set(item.get("available_products") or [])
        products = [p for p in _INTEREST_PRODUCTS if p in supported]
        name = ""
        if inst_id:
            try:
                inst = self._call(INSTITUTIONS_GET_BY_ID, {
                    "institution_id": inst_id,
                    "country_codes": list(settings.plaid_country_codes),
                })
                name = (inst.get("institution") or {}).get("name") or ""
            except PlaidError:
                name = ""
        return NormalizedItem(item_id=item.get("item_id", ""), institution_id=inst_id,
                              institution_name=name, products=products)

    # ---- data ----
    def get_accounts(self, access_token: str) -> list[NormalizedAccount]:
        data = self._call(ACCOUNTS_GET, {"access_token": access_token})
        item_id = (data.get("item") or {}).get("item_id", "")
        out = []
        for a in data.get("accounts") or []:
            bal = a.get("balances") or {}
            out.append(NormalizedAccount(
                source="plaid", source_id=a.get("account_id", ""), item_id=item_id,
                name=a.get("name", ""), official_name=a.get("official_name"),
                mask=a.get("mask"), type=a.get("type", ""), subtype=a.get("subtype"),
                current_balance=_dec(bal.get("current")),
                available_balance=_dec(bal.get("available")),
                iso_currency=bal.get("iso_currency_code") or "USD",
            ))
        return out

    def _txn(self, t: dict) -> NormalizedTransaction:
        pfc = t.get("personal_finance_category") or {}
        return NormalizedTransaction(
            source="plaid", source_id=t.get("transaction_id", ""),
            account_id=t.get("account_id", ""), item_id=t.get("item_id", ""),
            name=t.get("name", ""), merchant_name=t.get("merchant_name"),
            amount=_dec(t.get("amount")) or Decimal("0"),
            iso_currency=t.get("iso_currency_code") or "USD",
            date=_date(t.get("date")) or date.today(),
            authorized_date=_date(t.get("authorized_date")),
            pending=bool(t.get("pending")),
            category_primary=pfc.get("primary", ""), category_detailed=pfc.get("detailed", ""),
            payment_channel=t.get("payment_channel", ""),
        )

    def sync_transactions(self, access_token: str, cursor: str | None) -> TransactionsDelta:
        payload = {"access_token": access_token}
        if cursor:
            payload["cursor"] = cursor
        data = self._call(TRANSACTIONS_SYNC, payload)
        return TransactionsDelta(
            added=[self._txn(t) for t in data.get("added") or []],
            modified=[self._txn(t) for t in data.get("modified") or []],
            removed=[r.get("transaction_id", "") for r in data.get("removed") or []],
            next_cursor=data.get("next_cursor", ""),
            has_more=bool(data.get("has_more")),
        )

    def get_holdings(self, access_token: str) -> tuple[list[NormalizedAccount],
                                                       list[NormalizedSecurity],
                                                       list[NormalizedHolding]]:
        data = self._call(INVESTMENTS_HOLDINGS_GET, {"access_token": access_token})
        item_id = (data.get("item") or {}).get("item_id", "")
        accounts = []
        for a in data.get("accounts") or []:
            bal = a.get("balances") or {}
            accounts.append(NormalizedAccount(
                source="plaid", source_id=a.get("account_id", ""), item_id=item_id,
                name=a.get("name", ""), official_name=a.get("official_name"),
                mask=a.get("mask"), type=a.get("type", ""), subtype=a.get("subtype"),
                current_balance=_dec(bal.get("current")),
                available_balance=_dec(bal.get("available")),
                iso_currency=bal.get("iso_currency_code") or "USD",
            ))
        securities = []
        for sec in data.get("securities") or []:
            securities.append(NormalizedSecurity(
                source="plaid", source_id=sec.get("security_id", ""),
                name=sec.get("name") or "", ticker_symbol=sec.get("ticker_symbol"),
                type=sec.get("type") or "", close_price=_dec(sec.get("close_price")),
                iso_currency=sec.get("iso_currency_code") or "USD",
                is_cash_equivalent=bool(sec.get("is_cash_equivalent")),
            ))
        holdings = []
        for h in data.get("holdings") or []:
            holdings.append(NormalizedHolding(
                source="plaid", item_id=item_id, account_id=h.get("account_id", ""),
                security_id=h.get("security_id", ""),
                quantity=_dec(h.get("quantity")) or Decimal("0"),
                cost_basis=_dec(h.get("cost_basis")),
                institution_value=_dec(h.get("institution_value")) or Decimal("0"),
                institution_price=_dec(h.get("institution_price")),
                iso_currency=h.get("iso_currency_code") or "USD",
            ))
        return accounts, securities, holdings

    def get_link_public_token(self, link_token: str) -> str | None:
        """Poll /link/token/get for a Hosted-Link public_token. Returns None
        until the user finishes on Plaid's page. [confirm-against-live] shape."""
        data = self._call(LINK_TOKEN_GET, {"link_token": link_token})
        for sess in data.get("link_sessions") or []:
            results = sess.get("results") or {}
            for r in results.get("item_add_results") or []:
                pt = r.get("public_token")
                if pt:
                    return pt
        return None

    def remove_item(self, access_token: str) -> None:
        self._call(ITEM_REMOVE, {"access_token": access_token})
