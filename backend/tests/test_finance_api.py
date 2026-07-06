"""M7 /api/finance/* — connect (Hosted Link), DB-only reads, local budget
writes, disconnect. FakePlaidProvider installed per test; no network."""
from decimal import Decimal

from app import providers
from app.providers.base import (
    NormalizedAccount, NormalizedHolding, NormalizedItem,
    NormalizedSecurity, NormalizedTransaction, TransactionsDelta,
)
from app.store import store


def test_finance_schemas_import():
    from app.schemas import (  # noqa: F401
        AccountsOut, BudgetOut, BudgetReallocate, BudgetsUpdate, FinanceStatus,
        FinanceSummary, HoldingOut, LinkComplete, LinkStart, LinkStartOut,
        NetWorth, TransactionOut,
    )
    assert LinkStart(kind="bank").kind == "bank"
