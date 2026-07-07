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
    NormalizedInvestmentTransaction,
    NormalizedItem,
    NormalizedLiability,
    NormalizedRecurringStream,
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
INVESTMENTS_TRANSACTIONS_GET = "/investments/transactions/get"
TRANSACTIONS_RECURRING_GET = "/transactions/recurring/get"
ITEM_REMOVE = "/item/remove"
LIABILITIES_GET = "/liabilities/get"

# Plaid error_codes that mean "this Item needs the user to re-auth" -> needs_reauth.
_AUTH_ERRORCODES = frozenset({
    "ITEM_LOGIN_REQUIRED", "INVALID_ACCESS_TOKEN", "INVALID_CREDENTIALS",
    "ITEM_LOCKED", "USER_SETUP_REQUIRED", "PENDING_EXPIRATION", "ACCESS_NOT_GRANTED",
})

# Plaid error_codes meaning "this Item doesn't have this product (yet)" -> empty
# pane, not a crash. PRODUCT_NOT_READY fires right after a fresh link while Plaid
# is still indexing recurring/investments — treat it as absent-for-now, not fatal.
_FEATURE_ABSENT_ERRORCODES = frozenset({
    "PRODUCTS_NOT_SUPPORTED", "NO_LIABILITY_ACCOUNTS", "NO_ACCOUNTS", "NO_INVESTMENT_ACCOUNTS",
    "PRODUCT_NOT_READY",
})

# kind -> (required products, additional_consented_products). A bank consents to
# investments and liabilities too, so a bank+brokerage/credit login surfaces
# holdings and liabilities panes.
_PRODUCTS_FOR_KIND = {
    "bank": (["transactions"], ["investments", "liabilities"]),
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
    def create_link_token(self, kind: str, access_token: str | None = None) -> dict:
        payload = {
            "client_name": "Scuffed OS",
            "language": "en",
            "country_codes": list(settings.plaid_country_codes),
            "user": {"client_user_id": settings.owner},
            "hosted_link": {},
        }
        if access_token:                    # update mode: repair an existing Item, no products
            payload["access_token"] = access_token
        else:
            products, additional = _PRODUCTS_FOR_KIND.get(kind, _PRODUCTS_FOR_KIND["bank"])
            payload["products"] = products
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

    def _account(self, a: dict, item_id: str) -> NormalizedAccount:
        bal = a.get("balances") or {}
        return NormalizedAccount(
            source="plaid", source_id=a.get("account_id", ""), item_id=item_id,
            name=a.get("name", ""), official_name=a.get("official_name"),
            mask=a.get("mask"), type=a.get("type", ""), subtype=a.get("subtype"),
            current_balance=_dec(bal.get("current")),
            available_balance=_dec(bal.get("available")),
            iso_currency=bal.get("iso_currency_code") or "USD",
        )

    def _security(self, sec: dict) -> NormalizedSecurity:
        return NormalizedSecurity(
            source="plaid", source_id=sec.get("security_id", ""),
            name=sec.get("name") or "", ticker_symbol=sec.get("ticker_symbol"),
            type=sec.get("type") or "", close_price=_dec(sec.get("close_price")),
            iso_currency=sec.get("iso_currency_code") or "USD",
            is_cash_equivalent=bool(sec.get("is_cash_equivalent")),
        )

    def get_holdings(self, access_token: str) -> tuple[list[NormalizedAccount],
                                                       list[NormalizedSecurity],
                                                       list[NormalizedHolding]]:
        data = self._call(INVESTMENTS_HOLDINGS_GET, {"access_token": access_token})
        item_id = (data.get("item") or {}).get("item_id", "")
        accounts = [self._account(a, item_id) for a in data.get("accounts") or []]
        securities = [self._security(sec) for sec in data.get("securities") or []]
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

    def get_investment_transactions(self, access_token: str, start: date, end: date) -> tuple[
        list[NormalizedAccount], list[NormalizedSecurity], list[NormalizedInvestmentTransaction]]:
        accounts: dict[str, NormalizedAccount] = {}
        securities: dict[str, NormalizedSecurity] = {}
        txns: list[NormalizedInvestmentTransaction] = []
        offset = 0
        while True:
            try:
                data = self._call(INVESTMENTS_TRANSACTIONS_GET, {
                    "access_token": access_token,
                    "start_date": start.isoformat(), "end_date": end.isoformat(),
                    "options": {"count": 500, "offset": offset},
                })
            except PlaidError as exc:
                # Feature absent on the very first page -> empty ledger, not a crash
                # (an Item without investments still runs its other product panes).
                if offset == 0 and any(code in str(exc) for code in _FEATURE_ABSENT_ERRORCODES):
                    return [], [], []
                raise
            item_id = (data.get("item") or {}).get("item_id", "")
            for a in data.get("accounts") or []:
                acc = self._account(a, item_id)
                accounts[acc.source_id] = acc
            for sec in data.get("securities") or []:
                s = self._security(sec)
                securities[s.source_id] = s
            page = data.get("investment_transactions") or []
            for t in page:
                txns.append(NormalizedInvestmentTransaction(
                    source="plaid", source_id=t.get("investment_transaction_id", ""),
                    item_id=item_id, account_id=t.get("account_id", ""),
                    security_id=t.get("security_id") or "", type=t.get("type", ""),
                    subtype=t.get("subtype", ""), name=t.get("name", ""),
                    quantity=_dec(t.get("quantity")) or Decimal("0"),
                    amount=_dec(t.get("amount")) or Decimal("0"),
                    price=_dec(t.get("price")), fees=_dec(t.get("fees")),
                    date=_date(t.get("date")) or date.today(),
                    iso_currency=t.get("iso_currency_code") or "USD"))
            offset += len(page)
            total = int(data.get("total_investment_transactions") or 0)
            if not page or offset >= total:
                break
        return list(accounts.values()), list(securities.values()), txns

    def _recurring_stream(self, s: dict, stream_type: str) -> NormalizedRecurringStream:
        pfc = s.get("personal_finance_category") or {}
        avg = s.get("average_amount") or {}
        last = s.get("last_amount") or {}
        return NormalizedRecurringStream(
            source="plaid", source_id=s.get("stream_id", ""),
            item_id="", account_id=s.get("account_id", ""), stream_type=stream_type,
            description=s.get("description", ""), merchant_name=s.get("merchant_name"),
            category_primary=pfc.get("primary", ""), category_detailed=pfc.get("detailed", ""),
            average_amount=_dec(avg.get("amount")) or Decimal("0"),
            last_amount=_dec(last.get("amount")) or Decimal("0"),
            frequency=s.get("frequency", ""),
            first_date=_date(s.get("first_date")), last_date=_date(s.get("last_date")),
            predicted_next_date=_date(s.get("predicted_next_date")),
            is_active=bool(s.get("is_active", True)), status=s.get("status", ""),
            iso_currency=(avg.get("iso_currency_code") or "USD"),
        )

    def get_recurring(self, access_token: str) -> list[NormalizedRecurringStream]:
        try:
            data = self._call(TRANSACTIONS_RECURRING_GET, {"access_token": access_token})
        except PlaidError as exc:
            if any(code in str(exc) for code in _FEATURE_ABSENT_ERRORCODES):
                return []
            raise
        out = [self._recurring_stream(s, "inflow") for s in data.get("inflow_streams") or []]
        out += [self._recurring_stream(s, "outflow") for s in data.get("outflow_streams") or []]
        return out

    def _liability(self, a: dict, liability_type: str) -> NormalizedLiability:
        aprs = a.get("aprs") or []
        apr = _dec((aprs[0] or {}).get("apr_percentage")) if aprs else None
        due = a.get("next_payment_due_date")
        pay = a.get("minimum_payment_amount")
        if pay is None:
            pay = a.get("next_monthly_payment")           # mortgage naming
        return NormalizedLiability(
            source="plaid", source_id=a.get("account_id", ""), item_id="",
            account_id=a.get("account_id", ""), liability_type=liability_type,
            last_statement_balance=_dec(a.get("last_statement_balance")),
            minimum_payment=_dec(pay), next_payment_due_date=_date(due),
            last_payment_amount=_dec(a.get("last_payment_amount")),
            last_payment_date=_date(a.get("last_payment_date")),
            apr_percentage=apr, iso_currency="USD",
        )

    def get_liabilities(self, access_token: str) -> list[NormalizedLiability]:
        try:
            data = self._call(LIABILITIES_GET, {"access_token": access_token})
        except PlaidError as exc:
            if any(code in str(exc) for code in _FEATURE_ABSENT_ERRORCODES):
                return []
            raise
        liabs = (data.get("liabilities") or {})
        out: list[NormalizedLiability] = []
        for kind in ("credit", "mortgage", "student"):
            for a in liabs.get(kind) or []:
                out.append(self._liability(a, kind))
        return out

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
