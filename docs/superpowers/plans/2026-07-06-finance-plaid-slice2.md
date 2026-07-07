# M7 Finance Slice-2 "Recurring & Bills" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take the M7 Finance screen's two remaining sample panels (Subscriptions, Bills) live from Plaid, add investment transaction history and expanded budget categories, surface bills/renewals on the Calendar via read-time merge, and replace the duplicate-item "Reconnect" with real update-mode reauth.

**Architecture:** Extends the shipped slice-1 seam (provider → registry → `finance_sync` → `store` → `routers/finance` → `FinanceScreen`). Three new Plaid read endpoints (`/transactions/recurring/get`, `/liabilities/get`, `/investments/transactions/get`) flow through three new normalized dataclasses into three new tables (migration `0009`), then out through new store reads. Bills/renewals join the Calendar the same read-time way Moodle deadlines already do (`events_between` append; no `events`/`tasks` write). Reads never touch live Plaid.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy 2.0 / Alembic / hand-rolled `httpx` Plaid client (no `plaid-python`), pytest with SQLite-in-memory + `FakePlaidHTTP`/`FakePlaidProvider`; React (Vite) frontend verified with `npm run build`.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-07-06-finance-plaid-slice2-design.md`. **Branch:** `m7-finance-plaid-slice2` (already created off `m7-finance-plaid-slice1`).
- **No `plaid-python` SDK** — hand-rolled `httpx`; **all Plaid endpoint/field names confined to `providers/plaid.py`**; everything downstream speaks normalized dataclasses.
- **Read-only against Plaid.** The only mutation is local budgets. No bank writes, no transfers, no autonomous assistant writes — a permanent non-goal.
- **Money is `Numeric(16, 2)`; quantities `Numeric(24, 8)`; prices `Numeric(20, 8)` — never float.** Aware-UTC `DateTime(timezone=True)`, `default=utcnow`. Unique `(owner, source, source_id)` with `source="plaid"`.
- **`[confirm-against-live]`** on all new Plaid payload shapes, the subscription-vs-bill classifier, and new budget-bucket PFC mappings — resolved at the live gate, not in this plan.
- **Budget palette:** `kit.css` defines only `clay/honey/plum/sky/green` (`-600`) plus `slate` (already used by "Other"). Draw all category colors from these six; repeats are acceptable. Do **not** invent tokens.
- **TDD, DRY, YAGNI, frequent commits.** Run tests from `backend/`: `cd backend && python -m pytest …`. After the final task, run the **full** suite and report the pass count (user rule). Commit trailer on every commit: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

### Task 1: Migration `0009` + three ORM models

**Files:**
- Modify: `backend/app/models.py` (append after `FinanceBudget`, ~line 695)
- Create: `backend/alembic/versions/0009_finance_recurring.py`
- Modify: `backend/tests/test_migrations.py:37-38` (add three tables to `ALL_TABLES`)
- Test: `backend/tests/test_finance_models.py` (append)

**Interfaces:**
- Produces: ORM models `FinanceRecurring`, `FinanceLiability`, `FinanceInvestmentTransaction` (tables `finance_recurring`, `finance_liabilities`, `finance_investment_transactions`); alembic revision `"0009"`, `down_revision = "0008"`.

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_finance_models.py`:

```python
def test_slice2_models_persist_and_roundtrip():
    from datetime import date
    from app.db import Base, make_engine, make_session_factory
    from app.models import (
        FinanceRecurring, FinanceLiability, FinanceInvestmentTransaction,
    )
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s, s.begin():
        s.add(FinanceRecurring(owner="me", source="plaid", source_id="str1",
                               item_id="itm1", account_id="a1", stream_type="outflow",
                               description="Netflix", merchant_name="Netflix",
                               category_primary="ENTERTAINMENT", frequency="MONTHLY",
                               average_amount=Decimal("15.49"), last_amount=Decimal("15.49"),
                               last_date=date(2026, 6, 12), predicted_next_date=date(2026, 7, 12),
                               is_active=True, status="MATURE", iso_currency="USD"))
        s.add(FinanceLiability(owner="me", source="plaid", source_id="cc1",
                               item_id="itm1", account_id="cc1", liability_type="credit",
                               last_statement_balance=Decimal("1250.00"),
                               minimum_payment=Decimal("35.00"),
                               next_payment_due_date=date(2026, 7, 15),
                               apr_percentage=Decimal("19.99"), iso_currency="USD"))
        s.add(FinanceInvestmentTransaction(owner="me", source="plaid", source_id="it1",
                                           item_id="itm1", account_id="brk", security_id="s1",
                                           type="buy", subtype="buy", name="BUY BTC",
                                           quantity=Decimal("0.01"), amount=Decimal("600.00"),
                                           price=Decimal("60000"), fees=Decimal("1.50"),
                                           date=date(2026, 6, 10), iso_currency="USD"))
    with Session() as s:
        assert s.query(FinanceRecurring).one().average_amount == Decimal("15.49")
        assert s.query(FinanceLiability).one().next_payment_due_date == date(2026, 7, 15)
        assert s.query(FinanceInvestmentTransaction).one().quantity == Decimal("0.01")
    engine.dispose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_finance_models.py::test_slice2_models_persist_and_roundtrip -v`
Expected: FAIL with `ImportError: cannot import name 'FinanceRecurring'`.

- [ ] **Step 3: Add the three models** — append to `backend/app/models.py` after `FinanceBudget`:

```python
class FinanceRecurring(Base):
    """A Plaid recurring stream (/transactions/recurring/get). stream_type splits
    inflow (income) vs outflow (subscriptions/bills). NOT a bank write source."""

    __tablename__ = "finance_recurring"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id",
                         name="uq_finance_recurring_owner_source_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)        # 'plaid'
    source_id: Mapped[str] = mapped_column(String(128), index=True)    # Plaid stream_id
    item_id: Mapped[str] = mapped_column(String(128), index=True)
    account_id: Mapped[str] = mapped_column(String(128), index=True)
    stream_type: Mapped[str] = mapped_column(String(16), default="outflow")  # inflow|outflow
    description: Mapped[str] = mapped_column(String(255), default="")
    merchant_name: Mapped[str | None] = mapped_column(String(255))
    category_primary: Mapped[str] = mapped_column(String(64), default="")
    category_detailed: Mapped[str] = mapped_column(String(128), default="")
    average_amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=0)
    last_amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=0)
    frequency: Mapped[str] = mapped_column(String(24), default="")
    first_date: Mapped[date | None] = mapped_column(Date)
    last_date: Mapped[date | None] = mapped_column(Date)
    predicted_next_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(24), default="")
    iso_currency: Mapped[str] = mapped_column(String(8), default="USD")
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FinanceLiability(Base):
    """Loan/credit-card terms (/liabilities/get). Keyed by the account it describes."""

    __tablename__ = "finance_liabilities"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id",
                         name="uq_finance_liabilities_owner_source_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)        # 'plaid'
    source_id: Mapped[str] = mapped_column(String(128), index=True)    # = account_id
    item_id: Mapped[str] = mapped_column(String(128), index=True)
    account_id: Mapped[str] = mapped_column(String(128), index=True)
    liability_type: Mapped[str] = mapped_column(String(16), default="credit")  # credit|mortgage|student
    last_statement_balance: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    minimum_payment: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    next_payment_due_date: Mapped[date | None] = mapped_column(Date)
    last_payment_amount: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    last_payment_date: Mapped[date | None] = mapped_column(Date)
    apr_percentage: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    iso_currency: Mapped[str] = mapped_column(String(8), default="USD")
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FinanceInvestmentTransaction(Base):
    """An investment buy/sell/dividend/fee (/investments/transactions/get)."""

    __tablename__ = "finance_investment_transactions"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id",
                         name="uq_finance_investment_transactions_owner_source_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)        # 'plaid'
    source_id: Mapped[str] = mapped_column(String(128), index=True)    # investment_transaction_id
    item_id: Mapped[str] = mapped_column(String(128), index=True)
    account_id: Mapped[str] = mapped_column(String(128), index=True)
    security_id: Mapped[str] = mapped_column(String(128), index=True, default="")
    type: Mapped[str] = mapped_column(String(32), default="")
    subtype: Mapped[str] = mapped_column(String(48), default="")
    name: Mapped[str] = mapped_column(Text, default="")
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=0)
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=0)
    price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    fees: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    date: Mapped[date] = mapped_column(Date, index=True)
    iso_currency: Mapped[str] = mapped_column(String(8), default="USD")
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)
```

- [ ] **Step 4: Create the migration** — `backend/alembic/versions/0009_finance_recurring.py`:

```python
"""Finance slice 2 (M7): recurring streams, liabilities, investment transactions.

Three tables keyed (owner, source, source_id) = ('plaid', <id>) for idempotent
upsert. Read-only against Plaid.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

JSONField = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "finance_recurring",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("item_id", sa.String(length=128), nullable=False),
        sa.Column("account_id", sa.String(length=128), nullable=False),
        sa.Column("stream_type", sa.String(length=16), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("merchant_name", sa.String(length=255), nullable=True),
        sa.Column("category_primary", sa.String(length=64), nullable=False),
        sa.Column("category_detailed", sa.String(length=128), nullable=False),
        sa.Column("average_amount", sa.Numeric(16, 2), nullable=False),
        sa.Column("last_amount", sa.Numeric(16, 2), nullable=False),
        sa.Column("frequency", sa.String(length=24), nullable=False),
        sa.Column("first_date", sa.Date(), nullable=True),
        sa.Column("last_date", sa.Date(), nullable=True),
        sa.Column("predicted_next_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("iso_currency", sa.String(length=8), nullable=False),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "source", "source_id",
                            name="uq_finance_recurring_owner_source_source_id"),
    )
    op.create_index(op.f("ix_finance_recurring_owner"), "finance_recurring", ["owner"])
    op.create_index(op.f("ix_finance_recurring_source"), "finance_recurring", ["source"])
    op.create_index(op.f("ix_finance_recurring_source_id"), "finance_recurring", ["source_id"])
    op.create_index(op.f("ix_finance_recurring_item_id"), "finance_recurring", ["item_id"])
    op.create_index(op.f("ix_finance_recurring_account_id"), "finance_recurring", ["account_id"])

    op.create_table(
        "finance_liabilities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("item_id", sa.String(length=128), nullable=False),
        sa.Column("account_id", sa.String(length=128), nullable=False),
        sa.Column("liability_type", sa.String(length=16), nullable=False),
        sa.Column("last_statement_balance", sa.Numeric(16, 2), nullable=True),
        sa.Column("minimum_payment", sa.Numeric(16, 2), nullable=True),
        sa.Column("next_payment_due_date", sa.Date(), nullable=True),
        sa.Column("last_payment_amount", sa.Numeric(16, 2), nullable=True),
        sa.Column("last_payment_date", sa.Date(), nullable=True),
        sa.Column("apr_percentage", sa.Numeric(8, 4), nullable=True),
        sa.Column("iso_currency", sa.String(length=8), nullable=False),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "source", "source_id",
                            name="uq_finance_liabilities_owner_source_source_id"),
    )
    op.create_index(op.f("ix_finance_liabilities_owner"), "finance_liabilities", ["owner"])
    op.create_index(op.f("ix_finance_liabilities_source"), "finance_liabilities", ["source"])
    op.create_index(op.f("ix_finance_liabilities_source_id"), "finance_liabilities", ["source_id"])
    op.create_index(op.f("ix_finance_liabilities_item_id"), "finance_liabilities", ["item_id"])
    op.create_index(op.f("ix_finance_liabilities_account_id"), "finance_liabilities", ["account_id"])

    op.create_table(
        "finance_investment_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("item_id", sa.String(length=128), nullable=False),
        sa.Column("account_id", sa.String(length=128), nullable=False),
        sa.Column("security_id", sa.String(length=128), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("subtype", sa.String(length=48), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("amount", sa.Numeric(16, 2), nullable=False),
        sa.Column("price", sa.Numeric(20, 8), nullable=True),
        sa.Column("fees", sa.Numeric(16, 2), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("iso_currency", sa.String(length=8), nullable=False),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "source", "source_id",
                            name="uq_finance_investment_transactions_owner_source_source_id"),
    )
    op.create_index(op.f("ix_finance_investment_transactions_owner"),
                    "finance_investment_transactions", ["owner"])
    op.create_index(op.f("ix_finance_investment_transactions_source"),
                    "finance_investment_transactions", ["source"])
    op.create_index(op.f("ix_finance_investment_transactions_source_id"),
                    "finance_investment_transactions", ["source_id"])
    op.create_index(op.f("ix_finance_investment_transactions_item_id"),
                    "finance_investment_transactions", ["item_id"])
    op.create_index(op.f("ix_finance_investment_transactions_account_id"),
                    "finance_investment_transactions", ["account_id"])
    op.create_index(op.f("ix_finance_investment_transactions_date"),
                    "finance_investment_transactions", ["date"])


def downgrade() -> None:
    op.drop_table("finance_investment_transactions")
    op.drop_table("finance_liabilities")
    op.drop_table("finance_recurring")
```

- [ ] **Step 5: Register the tables in `ALL_TABLES`** — `backend/tests/test_migrations.py`, extend the finance lines (37-38):

```python
    "finance_items", "finance_accounts", "finance_transactions",
    "finance_securities", "finance_holdings", "finance_budgets",
    "finance_recurring", "finance_liabilities", "finance_investment_transactions",
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_finance_models.py::test_slice2_models_persist_and_roundtrip tests/test_migrations.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/0009_finance_recurring.py backend/tests/test_migrations.py backend/tests/test_finance_models.py
git commit -m "feat(finance): slice-2 tables — recurring, liabilities, investment transactions (migration 0009)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Normalized dataclasses + protocol methods

**Files:**
- Modify: `backend/app/providers/base.py` (add after `TransactionsDelta`, ~line 287; extend `PlaidProvider` protocol ~line 306)
- Test: `backend/tests/test_finance_models.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `NormalizedRecurringStream(source, source_id, item_id, account_id, stream_type, description, merchant_name, category_primary="", category_detailed="", average_amount=Decimal("0"), last_amount=Decimal("0"), frequency="", first_date=None, last_date=None, predicted_next_date=None, is_active=True, status="", iso_currency="USD")`
  - `NormalizedLiability(source, source_id, item_id, account_id, liability_type, last_statement_balance=None, minimum_payment=None, next_payment_due_date=None, last_payment_amount=None, last_payment_date=None, apr_percentage=None, iso_currency="USD")`
  - `NormalizedInvestmentTransaction(source, source_id, item_id, account_id, security_id, type, subtype="", name="", quantity=Decimal("0"), amount=Decimal("0"), price=None, fees=None, date=None, iso_currency="USD")`
  - `PlaidProvider` protocol gains: `get_recurring(access_token) -> list[NormalizedRecurringStream]`, `get_liabilities(access_token) -> list[NormalizedLiability]`, `get_investment_transactions(access_token, start, end) -> tuple[list[NormalizedAccount], list[NormalizedSecurity], list[NormalizedInvestmentTransaction]]`, and `create_link_token(kind, access_token=None) -> dict`.

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_finance_models.py`:

```python
def test_slice2_normalized_dataclasses_construct():
    from datetime import date
    from app.providers.base import (
        NormalizedRecurringStream, NormalizedLiability, NormalizedInvestmentTransaction,
    )
    r = NormalizedRecurringStream(source="plaid", source_id="str1", item_id="itm1",
                                  account_id="a1", stream_type="outflow", description="Netflix",
                                  merchant_name="Netflix", average_amount=Decimal("15.49"),
                                  frequency="MONTHLY", predicted_next_date=date(2026, 7, 12))
    assert r.stream_type == "outflow" and r.average_amount == Decimal("15.49")
    liab = NormalizedLiability(source="plaid", source_id="cc1", item_id="itm1", account_id="cc1",
                               liability_type="credit", minimum_payment=Decimal("35"),
                               next_payment_due_date=date(2026, 7, 15))
    assert liab.liability_type == "credit"
    it = NormalizedInvestmentTransaction(source="plaid", source_id="it1", item_id="itm1",
                                         account_id="brk", security_id="s1", type="buy",
                                         quantity=Decimal("0.01"), amount=Decimal("600"),
                                         date=date(2026, 6, 10))
    assert it.type == "buy" and it.quantity == Decimal("0.01")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_finance_models.py::test_slice2_normalized_dataclasses_construct -v`
Expected: FAIL with `ImportError: cannot import name 'NormalizedRecurringStream'`.

- [ ] **Step 3: Add the dataclasses** — in `backend/app/providers/base.py`, after `TransactionsDelta` (before the `@runtime_checkable class PlaidProvider`):

```python
@dataclass
class NormalizedRecurringStream:           # /transactions/recurring/get
    source: str                            # 'plaid'
    source_id: str                         # Plaid stream_id
    item_id: str
    account_id: str
    stream_type: str                       # 'inflow' | 'outflow'
    description: str
    merchant_name: str | None
    category_primary: str = ""
    category_detailed: str = ""
    average_amount: Decimal = Decimal("0")
    last_amount: Decimal = Decimal("0")
    frequency: str = ""                    # WEEKLY|BIWEEKLY|SEMI_MONTHLY|MONTHLY|ANNUALLY|UNKNOWN
    first_date: date | None = None
    last_date: date | None = None
    predicted_next_date: date | None = None
    is_active: bool = True
    status: str = ""
    iso_currency: str = "USD"


@dataclass
class NormalizedLiability:                  # /liabilities/get
    source: str                            # 'plaid'
    source_id: str                         # = account_id it describes
    item_id: str
    account_id: str
    liability_type: str                    # 'credit' | 'mortgage' | 'student'
    last_statement_balance: Decimal | None = None
    minimum_payment: Decimal | None = None
    next_payment_due_date: date | None = None
    last_payment_amount: Decimal | None = None
    last_payment_date: date | None = None
    apr_percentage: Decimal | None = None
    iso_currency: str = "USD"


@dataclass
class NormalizedInvestmentTransaction:      # /investments/transactions/get
    source: str                            # 'plaid'
    source_id: str                         # investment_transaction_id
    item_id: str
    account_id: str
    security_id: str
    type: str                              # buy|sell|cash|fee|transfer|...
    subtype: str = ""
    name: str = ""
    quantity: Decimal = Decimal("0")
    amount: Decimal = Decimal("0")
    price: Decimal | None = None
    fees: Decimal | None = None
    date: date | None = None
    iso_currency: str = "USD"
```

- [ ] **Step 4: Extend the `PlaidProvider` protocol** — in `backend/app/providers/base.py`, update `create_link_token` signature and add three methods inside `class PlaidProvider(Protocol)`:

```python
    def create_link_token(self, kind: str, access_token: str | None = None) -> dict: ...
    def get_recurring(self, access_token: str) -> list["NormalizedRecurringStream"]: ...
    def get_liabilities(self, access_token: str) -> list["NormalizedLiability"]: ...
    def get_investment_transactions(self, access_token: str, start: "date", end: "date") -> tuple[
        list["NormalizedAccount"], list["NormalizedSecurity"],
        list["NormalizedInvestmentTransaction"]]: ...
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_finance_models.py -v`
Expected: PASS (all model tests, including slice-1 ones).

- [ ] **Step 6: Commit**

```bash
git add backend/app/providers/base.py backend/tests/test_finance_models.py
git commit -m "feat(finance): normalized recurring/liability/investment-txn dataclasses + protocol

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `PlaidProvider.get_recurring`

**Files:**
- Modify: `backend/app/providers/plaid.py` (endpoint constant ~line 49; import ~line 28; method after `get_holdings`)
- Test: `backend/tests/test_plaid_provider.py` (append)

**Interfaces:**
- Consumes: `NormalizedRecurringStream` (Task 2), `_dec`/`_date` helpers, `_call`.
- Produces: `PlaidProvider.get_recurring(access_token) -> list[NormalizedRecurringStream]`.

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_plaid_provider.py`:

```python
def test_get_recurring_parses_inflow_and_outflow():
    http = FakePlaidHTTP(responses={"/transactions/recurring/get": {
        "inflow_streams": [{"stream_id": "in1", "account_id": "a1", "description": "Payroll",
                            "merchant_name": "Acme", "frequency": "BIWEEKLY",
                            "personal_finance_category": {"primary": "INCOME", "detailed": "INCOME_WAGES"},
                            "average_amount": {"amount": 2500, "iso_currency_code": "USD"},
                            "last_amount": {"amount": 2500, "iso_currency_code": "USD"},
                            "last_date": "2026-06-15", "predicted_next_date": "2026-06-29",
                            "is_active": True, "status": "MATURE"}],
        "outflow_streams": [{"stream_id": "out1", "account_id": "a1", "description": "Netflix",
                             "merchant_name": "Netflix", "frequency": "MONTHLY",
                             "personal_finance_category": {"primary": "ENTERTAINMENT",
                                                           "detailed": "ENTERTAINMENT_STREAMING"},
                             "average_amount": {"amount": 15.49, "iso_currency_code": "USD"},
                             "last_amount": {"amount": 15.49, "iso_currency_code": "USD"},
                             "last_date": "2026-06-12", "predicted_next_date": "2026-07-12",
                             "is_active": True, "status": "MATURE"}]}})
    p = _provider(http)
    streams = p.get_recurring("tok")
    by_id = {s.source_id: s for s in streams}
    assert by_id["in1"].stream_type == "inflow"
    assert by_id["out1"].stream_type == "outflow"
    assert by_id["out1"].average_amount == Decimal("15.49")
    assert by_id["out1"].category_primary == "ENTERTAINMENT"
    assert by_id["out1"].predicted_next_date.isoformat() == "2026-07-12"
    _, body = http.posts[0]
    assert body["access_token"] == "tok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_plaid_provider.py::test_get_recurring_parses_inflow_and_outflow -v`
Expected: FAIL with `AttributeError: 'PlaidProvider' object has no attribute 'get_recurring'`.

- [ ] **Step 3: Implement** — in `backend/app/providers/plaid.py`:

Add the import (extend the `from .base import (...)` block) `NormalizedRecurringStream,`. Add the endpoint constant near the others:

```python
TRANSACTIONS_RECURRING_GET = "/transactions/recurring/get"
```

Add the method after `get_holdings`:

```python
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
        data = self._call(TRANSACTIONS_RECURRING_GET, {"access_token": access_token})
        out = [self._recurring_stream(s, "inflow") for s in data.get("inflow_streams") or []]
        out += [self._recurring_stream(s, "outflow") for s in data.get("outflow_streams") or []]
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_plaid_provider.py::test_get_recurring_parses_inflow_and_outflow -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers/plaid.py backend/tests/test_plaid_provider.py
git commit -m "feat(finance): PlaidProvider.get_recurring (/transactions/recurring/get)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: `PlaidProvider.get_liabilities` + liabilities consent

**Files:**
- Modify: `backend/app/providers/plaid.py` (constant + feature-absent set + method; `_PRODUCTS_FOR_KIND` bank tuple)
- Modify: `backend/tests/test_plaid_provider.py` (append + update the existing bank-link assertion)

**Interfaces:**
- Consumes: `NormalizedLiability` (Task 2), `PlaidError`.
- Produces: `PlaidProvider.get_liabilities(access_token) -> list[NormalizedLiability]` (returns `[]` when the item lacks the product). Bank links now consent `additional_consented_products=["investments", "liabilities"]`.

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_plaid_provider.py`:

```python
def test_get_liabilities_flattens_types():
    http = FakePlaidHTTP(responses={"/liabilities/get": {"liabilities": {
        "credit": [{"account_id": "cc1", "last_statement_balance": 1250.0,
                    "minimum_payment_amount": 35.0, "next_payment_due_date": "2026-07-15",
                    "last_payment_amount": 200.0, "last_payment_date": "2026-06-10",
                    "aprs": [{"apr_percentage": 19.99, "apr_type": "purchase_apr"}]}],
        "mortgage": [{"account_id": "mg1", "next_monthly_payment": 1800.0,
                      "next_payment_due_date": "2026-07-01"}],
        "student": []}}})
    p = _provider(http)
    liabs = {l.account_id: l for l in p.get_liabilities("tok")}
    assert liabs["cc1"].liability_type == "credit"
    assert liabs["cc1"].minimum_payment == Decimal("35")
    assert liabs["cc1"].apr_percentage == Decimal("19.99")
    assert liabs["mg1"].liability_type == "mortgage"


def test_get_liabilities_feature_absent_returns_empty():
    http = FakePlaidHTTP(
        responses={"/liabilities/get": {"error_code": "PRODUCTS_NOT_SUPPORTED",
                                        "error_message": "no liabilities"}},
        status={"/liabilities/get": 400})
    p = _provider(http)
    assert p.get_liabilities("tok") == []


def test_get_liabilities_auth_error_still_raises():
    http = FakePlaidHTTP(
        responses={"/liabilities/get": {"error_code": "ITEM_LOGIN_REQUIRED", "error_message": "reauth"}},
        status={"/liabilities/get": 400})
    p = _provider(http)
    with pytest.raises(PlaidAuthError):
        p.get_liabilities("tok")
```

Also **update** the existing `test_create_link_token_bank_requests_transactions` assertion (bank now consents liabilities too):

```python
    assert body["additional_consented_products"] == ["investments", "liabilities"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_plaid_provider.py::test_get_liabilities_flattens_types tests/test_plaid_provider.py::test_create_link_token_bank_requests_transactions -v`
Expected: FAIL (missing `get_liabilities`; bank assertion mismatch).

- [ ] **Step 3: Implement** — in `backend/app/providers/plaid.py`:

Extend the `from .base import (...)` with `NormalizedLiability,`. Update the bank tuple and add constants:

```python
_PRODUCTS_FOR_KIND = {
    "bank": (["transactions"], ["investments", "liabilities"]),
    "investments": (["investments"], []),
}

LIABILITIES_GET = "/liabilities/get"

# Plaid error_codes meaning "this Item doesn't have this product" -> empty pane, not a crash.
_FEATURE_ABSENT_ERRORCODES = frozenset({
    "PRODUCTS_NOT_SUPPORTED", "NO_LIABILITY_ACCOUNTS", "NO_ACCOUNTS", "NO_INVESTMENT_ACCOUNTS",
})
```

Add the method after `get_recurring`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_plaid_provider.py -v`
Expected: PASS (all provider tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers/plaid.py backend/tests/test_plaid_provider.py
git commit -m "feat(finance): PlaidProvider.get_liabilities + liabilities consent on bank links

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: `PlaidProvider.get_investment_transactions` (paged)

**Files:**
- Modify: `backend/app/providers/plaid.py` (constant + method reusing `get_holdings` account/security parsers)
- Test: `backend/tests/test_plaid_provider.py` (append)

**Interfaces:**
- Consumes: `NormalizedInvestmentTransaction`, `NormalizedAccount`, `NormalizedSecurity`.
- Produces: `PlaidProvider.get_investment_transactions(access_token, start, end) -> tuple[list[NormalizedAccount], list[NormalizedSecurity], list[NormalizedInvestmentTransaction]]`.

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_plaid_provider.py`:

```python
def test_get_investment_transactions_pages_and_parses():
    from datetime import date
    page1 = {"accounts": [{"account_id": "brk", "name": "Coinbase", "type": "investment",
                           "subtype": "crypto", "balances": {"current": 3000.0, "iso_currency_code": "USD"}}],
             "securities": [{"security_id": "s1", "name": "Bitcoin", "ticker_symbol": "BTC",
                             "type": "cryptocurrency", "iso_currency_code": "USD"}],
             "investment_transactions": [{"investment_transaction_id": "it1", "account_id": "brk",
                                          "security_id": "s1", "date": "2026-06-10", "name": "BUY BTC",
                                          "quantity": 0.01, "amount": 600.0, "price": 60000.0,
                                          "fees": 1.5, "type": "buy", "subtype": "buy",
                                          "iso_currency_code": "USD"}],
             "total_investment_transactions": 2}
    page2 = {"accounts": [], "securities": [],
             "investment_transactions": [{"investment_transaction_id": "it2", "account_id": "brk",
                                          "security_id": "s1", "date": "2026-06-11", "name": "SELL BTC",
                                          "quantity": -0.005, "amount": -300.0, "price": 60000.0,
                                          "type": "sell", "subtype": "sell", "iso_currency_code": "USD"}],
             "total_investment_transactions": 2}
    http = FakePlaidHTTP(responses={"/investments/transactions/get": seq(page1, page2)})
    p = _provider(http)
    accts, secs, txns = p.get_investment_transactions("tok", date(2026, 6, 1), date(2026, 6, 30))
    ids = {t.source_id for t in txns}
    assert ids == {"it1", "it2"}
    it1 = next(t for t in txns if t.source_id == "it1")
    assert it1.type == "buy" and it1.quantity == Decimal("0.01") and it1.amount == Decimal("600")
    assert secs[0].ticker_symbol == "BTC" and accts[0].source_id == "brk"
    _, body = http.posts[0]
    assert body["start_date"] == "2026-06-01" and body["end_date"] == "2026-06-30"
    assert body["options"]["offset"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_plaid_provider.py::test_get_investment_transactions_pages_and_parses -v`
Expected: FAIL with `AttributeError: … 'get_investment_transactions'`.

- [ ] **Step 3: Implement** — in `backend/app/providers/plaid.py`:

Extend the import with `NormalizedInvestmentTransaction,`. Add the constant:

```python
INVESTMENTS_TRANSACTIONS_GET = "/investments/transactions/get"
```

Refactor the account/security parsing out of `get_holdings` into helpers `_account(a, item_id)` and `_security(sec)` (extract the existing loops verbatim so `get_holdings` and this method share them — DRY), then add:

```python
    def get_investment_transactions(self, access_token: str, start: date, end: date) -> tuple[
        list[NormalizedAccount], list[NormalizedSecurity], list[NormalizedInvestmentTransaction]]:
        accounts: dict[str, NormalizedAccount] = {}
        securities: dict[str, NormalizedSecurity] = {}
        txns: list[NormalizedInvestmentTransaction] = []
        offset = 0
        while True:
            data = self._call(INVESTMENTS_TRANSACTIONS_GET, {
                "access_token": access_token,
                "start_date": start.isoformat(), "end_date": end.isoformat(),
                "options": {"count": 500, "offset": offset},
            })
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_plaid_provider.py -v`
Expected: PASS (paging + existing `get_holdings` still green after the helper extraction).

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers/plaid.py backend/tests/test_plaid_provider.py
git commit -m "feat(finance): PlaidProvider.get_investment_transactions (paged) + share account/security parsers

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Update-mode `create_link_token(access_token=…)`

**Files:**
- Modify: `backend/app/providers/plaid.py` (`create_link_token`)
- Test: `backend/tests/test_plaid_provider.py` (append)

**Interfaces:**
- Produces: `create_link_token(kind, access_token=None)` — when `access_token` is passed, mints an update-mode token (includes `access_token`, omits `products`/`additional_consented_products`).

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_plaid_provider.py`:

```python
def test_create_link_token_update_mode_omits_products():
    http = FakePlaidHTTP(responses={"/link/token/create": {"link_token": "l", "hosted_link_url": "u"}})
    p = _provider(http)
    p.create_link_token("bank", access_token="acc-tok")
    _, body = http.posts[0]
    assert body["access_token"] == "acc-tok"
    assert "products" not in body
    assert "additional_consented_products" not in body
    assert "hosted_link" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_plaid_provider.py::test_create_link_token_update_mode_omits_products -v`
Expected: FAIL (`create_link_token() got an unexpected keyword argument 'access_token'`).

- [ ] **Step 3: Implement** — replace `create_link_token` in `backend/app/providers/plaid.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_plaid_provider.py -v`
Expected: PASS (update-mode + both original bank/investments link tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers/plaid.py backend/tests/test_plaid_provider.py
git commit -m "feat(finance): update-mode create_link_token(access_token=...)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Store upserts for the three tables + disconnect cascade

**Files:**
- Modify: `backend/app/store.py` (import models; add upserts near the finance section ~line 2178; extend `delete_finance_item` model loop ~line 2027)
- Test: `backend/tests/test_finance_store.py` (append)

**Interfaces:**
- Consumes: models + normalized dataclasses from Tasks 1–2.
- Produces: `store.upsert_finance_recurring(r)`, `store.upsert_finance_liability(l)`, `store.upsert_finance_investment_transaction(it)`; `delete_finance_item` now also deletes rows in the three new tables for the item.

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_finance_store.py`:

```python
def test_upsert_and_cascade_slice2_tables():
    from datetime import date
    from app.providers.base import (
        NormalizedItem, NormalizedRecurringStream, NormalizedLiability,
        NormalizedInvestmentTransaction,
    )
    store.upsert_finance_item(NormalizedItem(item_id="itm1", institution_id="ins_1",
                                             institution_name="Chase", products=["transactions"]),
                              access_token="tok")
    store.upsert_finance_recurring(NormalizedRecurringStream(
        source="plaid", source_id="str1", item_id="itm1", account_id="a1",
        stream_type="outflow", description="Netflix", merchant_name="Netflix",
        category_primary="ENTERTAINMENT", average_amount=Decimal("15.49"),
        frequency="MONTHLY", predicted_next_date=date(2026, 7, 12)))
    store.upsert_finance_liability(NormalizedLiability(
        source="plaid", source_id="cc1", item_id="itm1", account_id="cc1",
        liability_type="credit", minimum_payment=Decimal("35"),
        next_payment_due_date=date(2026, 7, 15)))
    store.upsert_finance_investment_transaction(NormalizedInvestmentTransaction(
        source="plaid", source_id="it1", item_id="itm1", account_id="brk", security_id="s1",
        type="buy", quantity=Decimal("0.01"), amount=Decimal("600"), date=date(2026, 6, 10)))
    # idempotent re-upsert keeps one row
    store.upsert_finance_recurring(NormalizedRecurringStream(
        source="plaid", source_id="str1", item_id="itm1", account_id="a1",
        stream_type="outflow", description="Netflix", merchant_name="Netflix",
        average_amount=Decimal("16.49"), frequency="MONTHLY"))
    from sqlalchemy import select as _select
    from app.models import FinanceRecurring, FinanceLiability, FinanceInvestmentTransaction
    with store._session() as s:
        assert len(s.scalars(_select(FinanceRecurring)).all()) == 1        # re-upsert didn't duplicate
        assert len(s.scalars(_select(FinanceInvestmentTransaction)).all()) == 1
    # disconnect cascades all three new tables
    assert store.delete_finance_item("itm1") is True
    with store._session() as s:
        assert s.scalars(_select(FinanceRecurring)).all() == []
        assert s.scalars(_select(FinanceLiability)).all() == []
        assert s.scalars(_select(FinanceInvestmentTransaction)).all() == []
```

This test is self-contained (direct ORM queries, no dependency on later read methods).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_finance_store.py::test_upsert_and_cascade_slice2_tables -v`
Expected: FAIL (`store has no attribute 'upsert_finance_recurring'`).

- [ ] **Step 3: Implement the upserts** — in `backend/app/store.py`, add to the model import block `FinanceRecurring, FinanceLiability, FinanceInvestmentTransaction`, and add methods in the finance section (after `upsert_finance_holding`):

```python
    @_retry_integrity
    def upsert_finance_recurring(self, r) -> None:
        from .config import settings
        with self._session() as s, s.begin():
            row = s.scalars(
                select(FinanceRecurring)
                .where(FinanceRecurring.owner == settings.owner)
                .where(FinanceRecurring.source == "plaid")
                .where(FinanceRecurring.source_id == r.source_id)
            ).first()
            if row is None:
                row = FinanceRecurring(owner=settings.owner, source="plaid", source_id=r.source_id)
                s.add(row)
            row.item_id = r.item_id
            row.account_id = r.account_id
            row.stream_type = r.stream_type
            row.description = r.description
            row.merchant_name = r.merchant_name
            row.category_primary = r.category_primary
            row.category_detailed = r.category_detailed
            row.average_amount = r.average_amount
            row.last_amount = r.last_amount
            row.frequency = r.frequency
            row.first_date = r.first_date
            row.last_date = r.last_date
            row.predicted_next_date = r.predicted_next_date
            row.is_active = r.is_active
            row.status = r.status
            row.iso_currency = r.iso_currency

    @_retry_integrity
    def upsert_finance_liability(self, l) -> None:
        from .config import settings
        with self._session() as s, s.begin():
            row = s.scalars(
                select(FinanceLiability)
                .where(FinanceLiability.owner == settings.owner)
                .where(FinanceLiability.source == "plaid")
                .where(FinanceLiability.source_id == l.source_id)
            ).first()
            if row is None:
                row = FinanceLiability(owner=settings.owner, source="plaid", source_id=l.source_id)
                s.add(row)
            row.item_id = l.item_id
            row.account_id = l.account_id
            row.liability_type = l.liability_type
            row.last_statement_balance = l.last_statement_balance
            row.minimum_payment = l.minimum_payment
            row.next_payment_due_date = l.next_payment_due_date
            row.last_payment_amount = l.last_payment_amount
            row.last_payment_date = l.last_payment_date
            row.apr_percentage = l.apr_percentage
            row.iso_currency = l.iso_currency

    @_retry_integrity
    def upsert_finance_investment_transaction(self, it) -> None:
        from .config import settings
        with self._session() as s, s.begin():
            row = s.scalars(
                select(FinanceInvestmentTransaction)
                .where(FinanceInvestmentTransaction.owner == settings.owner)
                .where(FinanceInvestmentTransaction.source == "plaid")
                .where(FinanceInvestmentTransaction.source_id == it.source_id)
            ).first()
            if row is None:
                row = FinanceInvestmentTransaction(owner=settings.owner, source="plaid",
                                                   source_id=it.source_id)
                s.add(row)
            row.item_id = it.item_id
            row.account_id = it.account_id
            row.security_id = it.security_id
            row.type = it.type
            row.subtype = it.subtype
            row.name = it.name
            row.quantity = it.quantity
            row.amount = it.amount
            row.price = it.price
            row.fees = it.fees
            row.date = it.date
            row.iso_currency = it.iso_currency
```

- [ ] **Step 4: Extend the disconnect cascade** — in `delete_finance_item`, add the three models to the delete loop:

```python
            for model in (FinanceAccount, FinanceTransaction, FinanceHolding,
                          FinanceRecurring, FinanceLiability, FinanceInvestmentTransaction):
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_finance_store.py::test_upsert_and_cascade_slice2_tables -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/store.py backend/tests/test_finance_store.py
git commit -m "feat(finance): store upserts for recurring/liabilities/investment-txns + disconnect cascade

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: `recurring_kind` classifier + `finance_subscriptions` + `finance_bills`

**Files:**
- Modify: `backend/app/store.py` (module-level `recurring_kind` near `budget_bucket` ~line 92; read methods in the finance section)
- Test: `backend/tests/test_finance_store.py` (append)

**Interfaces:**
- Consumes: `FinanceRecurring`, `FinanceLiability`, `_dec_to_float`.
- Produces: module-level `recurring_kind(primary, detailed="") -> str` (`'subscription'|'bill'|'other'`); `store.finance_subscriptions() -> list[dict]` (`{name, merchant_name, amount, frequency, next_date, category}`); `store.finance_bills() -> list[dict]` (`{name, sub, amount, due_date, kind, auto}`).

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_finance_store.py`:

```python
def test_subscriptions_and_bills_split_and_merge():
    from datetime import date
    from app.providers.base import NormalizedRecurringStream, NormalizedLiability
    store.upsert_finance_recurring(NormalizedRecurringStream(
        source="plaid", source_id="sub1", item_id="itm1", account_id="a1", stream_type="outflow",
        description="Netflix", merchant_name="Netflix", category_primary="ENTERTAINMENT",
        average_amount=Decimal("15.49"), frequency="MONTHLY", predicted_next_date=date(2026, 7, 12),
        is_active=True))
    store.upsert_finance_recurring(NormalizedRecurringStream(
        source="plaid", source_id="bill1", item_id="itm1", account_id="a1", stream_type="outflow",
        description="Verizon", merchant_name="Verizon", category_primary="RENT_AND_UTILITIES",
        average_amount=Decimal("70"), frequency="MONTHLY", predicted_next_date=date(2026, 7, 16),
        is_active=True))
    store.upsert_finance_recurring(NormalizedRecurringStream(
        source="plaid", source_id="pay1", item_id="itm1", account_id="a1", stream_type="inflow",
        description="Payroll", merchant_name="Acme", category_primary="INCOME",
        average_amount=Decimal("2500"), frequency="BIWEEKLY", is_active=True))
    store.upsert_finance_liability(NormalizedLiability(
        source="plaid", source_id="cc1", item_id="itm1", account_id="cc1", liability_type="credit",
        minimum_payment=Decimal("35"), next_payment_due_date=date(2026, 7, 15)))
    subs = store.finance_subscriptions()
    assert [s["name"] for s in subs] == ["Netflix"]           # inflow + bill excluded
    assert subs[0]["amount"] == 15.49
    bills = store.finance_bills()
    names = {b["name"] for b in bills}
    assert "Verizon" in names                                 # utility recurring stream = bill
    assert "Netflix" not in names                             # entertainment stream = subscription, not bill
    # recurring bill + liability both present, sorted by due date
    assert any(b["kind"] == "recurring" for b in bills)
    assert any(b["kind"] == "liability" and b["amount"] == 35.0 for b in bills)
    assert [b["due_date"] for b in bills] == sorted(b["due_date"] for b in bills)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_finance_store.py::test_subscriptions_and_bills_split_and_merge -v`
Expected: FAIL (`store has no attribute 'finance_subscriptions'`).

- [ ] **Step 3: Add the classifier** — in `backend/app/store.py` after `budget_bucket`:

```python
def recurring_kind(primary: str, detailed: str = "") -> str:
    """Split a recurring OUTFLOW stream into 'subscription' vs 'bill' by Plaid PFC.
    [confirm-against-live] — real PFC values verified at the live gate."""
    primary = (primary or "").upper()
    if primary in ("RENT_AND_UTILITIES", "LOAN_PAYMENTS", "INSURANCE"):
        return "bill"
    if primary in ("ENTERTAINMENT", "GENERAL_SERVICES"):
        return "subscription"
    return "other"
```

- [ ] **Step 4: Add the read methods** — in the finance section of `store.py`:

```python
    def finance_subscriptions(self) -> list[dict]:
        """Active recurring OUTFLOW streams classified 'subscription', by next date."""
        from .config import settings
        with self._session() as s:
            rows = s.scalars(
                select(FinanceRecurring)
                .where(FinanceRecurring.owner == settings.owner)
                .where(FinanceRecurring.stream_type == "outflow")
                .where(FinanceRecurring.is_active.is_(True))
            ).all()
        out = []
        for r in rows:
            if recurring_kind(r.category_primary, r.category_detailed) != "subscription":
                continue
            out.append({
                "name": r.merchant_name or r.description,
                "merchant_name": r.merchant_name,
                "amount": _dec_to_float(r.average_amount),
                "frequency": r.frequency,
                "next_date": r.predicted_next_date.isoformat() if r.predicted_next_date else None,
                "category": r.category_primary,
            })
        out.sort(key=lambda x: (x["next_date"] or "9999-12-31"))
        return out

    def finance_bills(self) -> list[dict]:
        """Recurring 'bill' streams merged with liabilities (statement/due), by due date."""
        from .config import settings
        with self._session() as s:
            streams = s.scalars(
                select(FinanceRecurring)
                .where(FinanceRecurring.owner == settings.owner)
                .where(FinanceRecurring.stream_type == "outflow")
                .where(FinanceRecurring.is_active.is_(True))
            ).all()
            liabs = s.scalars(
                select(FinanceLiability).where(FinanceLiability.owner == settings.owner)
            ).all()
        out = []
        for r in streams:
            if recurring_kind(r.category_primary, r.category_detailed) != "bill":
                continue
            out.append({
                "name": r.merchant_name or r.description,
                "sub": r.description,
                "amount": _dec_to_float(r.average_amount),
                "due_date": r.predicted_next_date.isoformat() if r.predicted_next_date else None,
                "kind": "recurring",
                "auto": True,
            })
        for l in liabs:
            out.append({
                "name": l.account_id,
                "sub": l.liability_type,
                "amount": _dec_to_float(l.minimum_payment),
                "due_date": l.next_payment_due_date.isoformat() if l.next_payment_due_date else None,
                "kind": "liability",
                "auto": False,
            })
        out.sort(key=lambda x: (x["due_date"] or "9999-12-31"))
        return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_finance_store.py::test_subscriptions_and_bills_split_and_merge -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/store.py backend/tests/test_finance_store.py
git commit -m "feat(finance): recurring_kind classifier + finance_subscriptions/finance_bills reads

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9: `finance_investment_transactions` read

**Files:**
- Modify: `backend/app/store.py` (finance section)
- Test: covered by Task 7's `test_upsert_and_cascade_slice2_tables` + a shaping test appended to `backend/tests/test_finance_store.py`

**Interfaces:**
- Produces: `store.finance_investment_transactions(days=None) -> list[dict]` (`{date, type, name, ticker, quantity, amount, price, currency}`), joined to `finance_securities`, newest first.

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_finance_store.py`:

```python
def test_investment_transactions_join_securities_newest_first():
    from datetime import date
    from app.providers.base import NormalizedSecurity, NormalizedInvestmentTransaction
    store.upsert_finance_security(NormalizedSecurity(
        source="plaid", source_id="s1", name="Bitcoin", ticker_symbol="BTC",
        type="cryptocurrency", iso_currency="USD"))
    store.upsert_finance_investment_transaction(NormalizedInvestmentTransaction(
        source="plaid", source_id="it1", item_id="itm1", account_id="brk", security_id="s1",
        type="buy", name="BUY BTC", quantity=Decimal("0.01"), amount=Decimal("600"),
        price=Decimal("60000"), date=date(2026, 6, 10)))
    store.upsert_finance_investment_transaction(NormalizedInvestmentTransaction(
        source="plaid", source_id="it2", item_id="itm1", account_id="brk", security_id="s1",
        type="sell", name="SELL BTC", quantity=Decimal("-0.005"), amount=Decimal("-300"),
        date=date(2026, 6, 11)))
    ledger = store.finance_investment_transactions()
    assert ledger[0]["type"] == "sell"          # newest first (2026-06-11 before 2026-06-10)
    assert ledger[0]["ticker"] == "BTC"
    assert ledger[1]["type"] == "buy" and ledger[1]["amount"] == 600.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_finance_store.py::test_investment_transactions_join_securities_newest_first -v`
Expected: FAIL (`store has no attribute 'finance_investment_transactions'`).

- [ ] **Step 3: Implement** — in `store.py` finance section:

```python
    def finance_investment_transactions(self, days: int | None = None) -> list[dict]:
        """Investment buys/sells/dividends joined to securities, newest first."""
        from .config import settings
        with self._session() as s:
            secs = {
                x.source_id: x for x in s.scalars(
                    select(FinanceSecurity).where(FinanceSecurity.owner == settings.owner)
                ).all()
            }
            q = (
                select(FinanceInvestmentTransaction)
                .where(FinanceInvestmentTransaction.owner == settings.owner)
                .order_by(FinanceInvestmentTransaction.date.desc(),
                          FinanceInvestmentTransaction.id.desc())
            )
            if days is not None:
                cutoff = (utcnow() - timedelta(days=days)).date()
                q = q.where(FinanceInvestmentTransaction.date >= cutoff)
            rows = s.scalars(q).all()
        out = []
        for t in rows:
            sec = secs.get(t.security_id)
            out.append({
                "type": t.type,
                "name": t.name or (sec.name if sec else t.security_id),
                "ticker": (sec.ticker_symbol if sec else None),
                "quantity": _dec_to_float(t.quantity),
                "amount": _dec_to_float(t.amount),
                "price": _dec_to_float(t.price),
                "date": t.date.isoformat() if t.date else None,
                "currency": t.iso_currency,
            })
        return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_finance_store.py -k "slice2 or investment_transactions" -v`
Expected: PASS (this test + Task 7's cascade test).

- [ ] **Step 5: Commit**

```bash
git add backend/app/store.py backend/tests/test_finance_store.py
git commit -m "feat(finance): finance_investment_transactions read (joined to securities)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 10: `finance_calendar_events` + `events_between` read-merge

**Files:**
- Modify: `backend/app/store.py` (new `finance_calendar_events`; append to `events_between` ~line 1040)
- Test: `backend/tests/test_finance_store.py` (append) + `backend/tests/test_calendar.py` (append — confirm read-only on the HTTP surface)

**Interfaces:**
- Consumes: `finance_bills()`, `finance_subscriptions()`.
- Produces: `store.finance_calendar_events(window_start, window_end) -> list[dict]` (occurrence dicts with `source="finance"`, `editable=False`, `id="finance:<source_id>"`, `tint="honey"`), merged into `events_between`.

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_finance_store.py`:

```python
def test_bills_appear_in_events_between_read_only():
    from datetime import datetime, timezone
    from app.providers.base import NormalizedLiability
    store.upsert_finance_liability(NormalizedLiability(
        source="plaid", source_id="cc1", item_id="itm1", account_id="cc1", liability_type="credit",
        minimum_payment=Decimal("35"), next_payment_due_date=__import__("datetime").date(2026, 7, 15)))
    occ = store.events_between(datetime(2026, 7, 1, tzinfo=timezone.utc),
                              datetime(2026, 7, 31, tzinfo=timezone.utc))
    fin = [o for o in occ if str(o["id"]).startswith("finance:")]
    assert fin and fin[0]["editable"] is False and fin[0]["source"] == "finance"
    # out-of-window excluded
    occ2 = store.events_between(datetime(2026, 8, 1, tzinfo=timezone.utc),
                               datetime(2026, 8, 31, tzinfo=timezone.utc))
    assert [o for o in occ2 if str(o["id"]).startswith("finance:")] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_finance_store.py::test_bills_appear_in_events_between_read_only -v`
Expected: FAIL (no `finance:` occurrences).

- [ ] **Step 3: Implement** — add `finance_calendar_events` in the finance section of `store.py`:

```python
    def finance_calendar_events(self, window_start, window_end) -> list[dict]:
        """Read-time projection (mirrors moodle_calendar_events): bill due dates +
        subscription renewals in the window as read-only 'finance:<id>' occurrences.
        NOT rows in the events table — events_between appends these at read time."""
        out: list[dict] = []

        def _push(source_id: str, title: str, iso_date: str | None):
            if not iso_date:
                return
            d = date.fromisoformat(iso_date)
            start = datetime(d.year, d.month, d.day, 9, 0, tzinfo=timezone.utc)
            if not (window_start <= start < window_end):
                return
            out.append({
                "id": f"finance:{source_id}",
                "title": title,
                "start": start,
                "end": start + timedelta(hours=1),
                "tint": "honey",
                "location": "",
                "description": "",
                "recurring": False,
                "recurrence_label": None,
                "at": clock(start),
                "source": "finance",
                "editable": False,
            })

        for b in self.finance_bills():
            amt = f" · ${b['amount']:,.0f}" if b.get("amount") is not None else ""
            _push(f"bill:{b['name']}", f"{b['name']}{amt} due", b.get("due_date"))
        for sub in self.finance_subscriptions():
            amt = f" · ${sub['amount']:,.2f}" if sub.get("amount") is not None else ""
            _push(f"sub:{sub['name']}", f"{sub['name']}{amt} renews", sub.get("next_date"))
        return out
```

Then append to `events_between` (right after the Moodle append):

```python
        out.extend(self.moodle_calendar_events(window_start, window_end))
        out.extend(self.finance_calendar_events(window_start, window_end))
        out.sort(key=lambda o: o["start"])
        return out
```

- [ ] **Step 4: Write the HTTP read-only guard test** — append to `backend/tests/test_calendar.py` (create if absent, mirroring existing calendar test imports):

```python
def test_finance_calendar_occurrence_not_mutable_via_http(client):
    # A 'finance:<id>' occurrence id is not an int, so the int-typed events routes reject it.
    res = client.patch("/api/calendar/events/finance:bill:cc1", json={"title": "x"})
    assert res.status_code in (404, 422)
    res2 = client.delete("/api/calendar/events/finance:bill:cc1")
    assert res2.status_code in (404, 422)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_finance_store.py::test_bills_appear_in_events_between_read_only tests/test_calendar.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/store.py backend/tests/test_finance_store.py backend/tests/test_calendar.py
git commit -m "feat(finance): bills/renewals read-merge into calendar events_between (read-only)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 11: Expanded budget categories + reallocate clamp

**Files:**
- Modify: `backend/app/store.py` (`BUDGET_CATEGORIES`, `_BUDGET_COLORS`, `budget_bucket`, `reallocate_budget`)
- Modify: `backend/app/tools.py` (category list in `set_budget` description ~line 877)
- Modify: `backend/tests/test_finance_api.py:111` (six → ten) + append store tests to `backend/tests/test_finance_store.py`

**Interfaces:**
- Produces: 10-category fixed set; `budget_bucket` maps four new buckets; `reallocate_budget` floors limits at `Decimal("0")`.

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_finance_store.py`:

```python
def test_expanded_budget_categories_and_bucket_mapping():
    from app.store import BUDGET_CATEGORIES, budget_bucket
    assert BUDGET_CATEGORIES == ["Groceries", "Dining out", "Rent & bills", "Transport",
                                 "Shopping", "Entertainment", "Health", "Travel",
                                 "Savings", "Other"]
    assert budget_bucket("GENERAL_MERCHANDISE") == "Shopping"
    assert budget_bucket("ENTERTAINMENT") == "Entertainment"
    assert budget_bucket("MEDICAL") == "Health"
    assert budget_bucket("TRAVEL") == "Travel"
    got = {b["category"] for b in store.finance_budgets("2026-06")}
    assert len(got) == 10


def test_reallocate_clamps_at_zero():
    store.upsert_budgets("2026-06", [{"category": "Dining out", "limit_amount": 50}])
    store.reallocate_budget("2026-06", "Dining out", "Savings", 200)  # more than source has
    budgets = {b["category"]: b for b in store.finance_budgets("2026-06")}
    assert budgets["Dining out"]["limit_amount"] == 0.0                # clamped, not negative
    assert budgets["Savings"]["limit_amount"] == 200.0
```

Also change `backend/tests/test_finance_api.py:111` from `assert len(got) == 6` to `assert len(got) == 10`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_finance_store.py::test_expanded_budget_categories_and_bucket_mapping tests/test_finance_store.py::test_reallocate_clamps_at_zero -v`
Expected: FAIL.

- [ ] **Step 3: Update the constants + mapping** — in `backend/app/store.py` replace the budget block (lines ~85-107):

```python
# ---- finance budget categories (expanded fixed set, slice 2) ----
BUDGET_CATEGORIES = ["Groceries", "Dining out", "Rent & bills", "Transport",
                     "Shopping", "Entertainment", "Health", "Travel", "Savings", "Other"]
# kit.css defines only clay/honey/plum/sky/green (-600) + slate; colors repeat by design.
_BUDGET_COLORS = {
    "Groceries": "clay", "Dining out": "plum", "Rent & bills": "honey",
    "Transport": "sky", "Shopping": "plum", "Entertainment": "sky",
    "Health": "green", "Travel": "honey", "Savings": "green", "Other": "slate",
}


def budget_bucket(primary: str, detailed: str = "") -> str:
    """Map a Plaid personal_finance_category to one of the ten budget buckets.
    [confirm-against-live] — real PFC values verified at the live gate."""
    primary = (primary or "").upper()
    detailed = (detailed or "").upper()
    if "GROCERIES" in detailed:
        return "Groceries"
    if primary == "FOOD_AND_DRINK":
        return "Dining out"
    if primary in ("RENT_AND_UTILITIES", "LOAN_PAYMENTS", "HOME_IMPROVEMENT"):
        return "Rent & bills"
    if primary in ("TRANSPORTATION",):
        return "Transport"
    if primary == "TRAVEL":
        return "Travel"
    if primary in ("GENERAL_MERCHANDISE",):
        return "Shopping"
    if primary in ("ENTERTAINMENT",):
        return "Entertainment"
    if primary in ("MEDICAL", "PERSONAL_CARE"):
        return "Health"
    if primary == "TRANSFER_OUT" and ("SAVINGS" in detailed or "INVESTMENT" in detailed):
        return "Savings"
    return "Other"
```

- [ ] **Step 4: Clamp reallocate** — in `reallocate_budget`:

```python
        new_from = max(Decimal("0"), Decimal(str(current.get(from_category, 0))) - amt)
        new_to = max(Decimal("0"), Decimal(str(current.get(to_category, 0))) + amt)
        self._upsert_one_budget(month, from_category, new_from)
        self._upsert_one_budget(month, to_category, new_to)
        return self.finance_budgets(month)
```

- [ ] **Step 5: Update the assistant `set_budget` description** — in `backend/app/tools.py`, replace the category list in the `set_budget` description string with: `"Categories: Groceries, Dining out, Rent & bills, Transport, Shopping, Entertainment, Health, Travel, Savings, Other."`

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_finance_store.py tests/test_finance_api.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/store.py backend/app/tools.py backend/tests/test_finance_store.py backend/tests/test_finance_api.py
git commit -m "feat(finance): expand budget categories to 10 + clamp reallocate at zero

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 12: Sync — recurring/liabilities/investment branches + fake extension

**Files:**
- Modify: `backend/tests/fakes.py` (extend `FakePlaidProvider`)
- Modify: `backend/app/finance_sync.py` (`_sync_item`)
- Test: `backend/tests/test_finance_sync.py` (append)

**Interfaces:**
- Consumes: provider methods (Tasks 3–5), store upserts (Task 7).
- Produces: `_sync_item` now upserts recurring + liabilities on `transactions` items and investment transactions on `investments` items. `FakePlaidProvider` gains `get_recurring`/`get_liabilities`/`get_investment_transactions` (default empty) + `create_link_token(kind, access_token=None)`.

- [ ] **Step 1: Extend `FakePlaidProvider`** — in `backend/tests/fakes.py`, add to `__init__` params `recurring=None, liabilities=None, investment_txns=None,` and store `self.recurring = recurring or []`, `self.liabilities = liabilities or []`, `self.investment_txns = investment_txns or ([], [], [])`. Update `create_link_token` and add three methods:

```python
    def create_link_token(self, kind: str, access_token=None) -> dict:
        self.link_kinds.append(kind)
        return {"link_token": "link-1", "hosted_link_url": "https://plaid/hl"}

    def get_recurring(self, access_token: str):
        return list(self.recurring)

    def get_liabilities(self, access_token: str):
        return list(self.liabilities)

    def get_investment_transactions(self, access_token: str, start=None, end=None):
        return self.investment_txns
```

- [ ] **Step 2: Write the failing test** — append to `backend/tests/test_finance_sync.py`:

```python
def test_tick_syncs_recurring_and_liabilities_on_transactions_item():
    from datetime import date
    from tests.fakes import FakePlaidProvider
    from app.providers.base import NormalizedRecurringStream, NormalizedLiability
    _seed_item(products=("transactions",))
    rec = NormalizedRecurringStream(source="plaid", source_id="sub1", item_id="", account_id="a1",
                                    stream_type="outflow", description="Netflix", merchant_name="Netflix",
                                    category_primary="ENTERTAINMENT", average_amount=Decimal("15.49"),
                                    frequency="MONTHLY", predicted_next_date=date(2026, 7, 12))
    liab = NormalizedLiability(source="plaid", source_id="cc1", item_id="", account_id="cc1",
                               liability_type="credit", minimum_payment=Decimal("35"),
                               next_payment_due_date=date(2026, 7, 15))
    providers.configure([FakePlaidProvider(accounts=[_acct()], recurring=[rec], liabilities=[liab])])
    finance_sync.tick()
    assert len(store.finance_subscriptions()) == 1
    assert any(b["kind"] == "liability" for b in store.finance_bills())


def test_tick_syncs_investment_transactions_on_investments_item():
    from datetime import date
    from tests.fakes import FakePlaidProvider
    from app.providers.base import (
        NormalizedAccount, NormalizedSecurity, NormalizedInvestmentTransaction,
    )
    _seed_item(products=("investments",))
    sec = NormalizedSecurity(source="plaid", source_id="s1", name="BTC", ticker_symbol="BTC",
                             type="cryptocurrency", iso_currency="USD")
    it = NormalizedInvestmentTransaction(source="plaid", source_id="it1", item_id="itm1",
                                         account_id="brk", security_id="s1", type="buy",
                                         quantity=Decimal("0.01"), amount=Decimal("600"),
                                         date=date(2026, 6, 10))
    prov = FakePlaidProvider(holdings=([_acct("brk")], [sec], []),
                             investment_txns=([_acct("brk")], [sec], [it]))
    providers.configure([prov])
    finance_sync.tick()
    assert len(store.finance_investment_transactions()) == 1


def test_tick_survives_liabilities_absent():
    # Provider returns [] for liabilities (feature absent) — no crash, no rows.
    from tests.fakes import FakePlaidProvider
    _seed_item(products=("transactions",))
    providers.configure([FakePlaidProvider(accounts=[_acct()])])  # recurring/liabilities default []
    assert finance_sync.tick() >= 1
    assert store.finance_bills() == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_finance_sync.py -k "recurring or investment or absent" -v`
Expected: FAIL (sync doesn't fetch the new data yet).

- [ ] **Step 4: Implement** — in `backend/app/finance_sync.py`, add `timedelta` to the datetime import, `from .config import settings` is already imported. Extend `_sync_item`:

Inside the `if "transactions" in products:` block, after the cursor `while` loop:

```python
        for rec in provider.get_recurring(access_token):
            rec.item_id = item_id
            store.upsert_finance_recurring(rec)
            count += 1
        for liab in provider.get_liabilities(access_token):
            liab.item_id = item_id
            store.upsert_finance_liability(liab)
            count += 1
```

Inside the `if "investments" in products:` block, after the holdings loops:

```python
        end = now.date()
        start = end - timedelta(days=settings.plaid_backfill_days)
        itx_accts, itx_secs, itxns = provider.get_investment_transactions(access_token, start, end)
        for a in itx_accts:
            store.upsert_finance_account(a)
            count += 1
        for sec in itx_secs:
            store.upsert_finance_security(sec)
            count += 1
        for it in itxns:
            it.item_id = item_id
            store.upsert_finance_investment_transaction(it)
            count += 1
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_finance_sync.py -v`
Expected: PASS (new + all slice-1 sync tests — the fake now satisfies the extended `_sync_item`).

- [ ] **Step 6: Commit**

```bash
git add backend/tests/fakes.py backend/app/finance_sync.py backend/tests/test_finance_sync.py
git commit -m "feat(finance): sync recurring/liabilities + investment transactions per item

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 13: API — subscriptions/bills/investment-transactions endpoints + schemas

**Files:**
- Modify: `backend/app/schemas.py` (append after `BudgetReallocate`)
- Modify: `backend/app/routers/finance.py` (new GET routes + imports)
- Test: `backend/tests/test_finance_api.py` (append)

**Interfaces:**
- Consumes: store reads (Tasks 8–9).
- Produces: `GET /api/finance/subscriptions|/bills|/investment-transactions`; schemas `SubscriptionOut`, `BillOut`, `InvestmentTxnOut`.

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_finance_api.py`:

```python
def test_subscriptions_bills_investment_endpoints(client):
    from datetime import date
    from app.providers.base import (
        NormalizedRecurringStream, NormalizedLiability, NormalizedSecurity,
        NormalizedInvestmentTransaction,
    )
    store.upsert_finance_recurring(NormalizedRecurringStream(
        source="plaid", source_id="sub1", item_id="itm1", account_id="a1", stream_type="outflow",
        description="Netflix", merchant_name="Netflix", category_primary="ENTERTAINMENT",
        average_amount=Decimal("15.49"), frequency="MONTHLY", predicted_next_date=date(2026, 7, 12)))
    store.upsert_finance_liability(NormalizedLiability(
        source="plaid", source_id="cc1", item_id="itm1", account_id="cc1", liability_type="credit",
        minimum_payment=Decimal("35"), next_payment_due_date=date(2026, 7, 15)))
    store.upsert_finance_security(NormalizedSecurity(
        source="plaid", source_id="s1", name="Bitcoin", ticker_symbol="BTC", type="cryptocurrency"))
    store.upsert_finance_investment_transaction(NormalizedInvestmentTransaction(
        source="plaid", source_id="it1", item_id="itm1", account_id="brk", security_id="s1",
        type="buy", name="BUY BTC", quantity=Decimal("0.01"), amount=Decimal("600"),
        date=date(2026, 6, 10)))
    assert client.get("/api/finance/subscriptions").json()[0]["name"] == "Netflix"
    assert any(b["kind"] == "liability" for b in client.get("/api/finance/bills").json())
    itx = client.get("/api/finance/investment-transactions").json()
    assert itx[0]["ticker"] == "BTC" and itx[0]["type"] == "buy"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_finance_api.py::test_subscriptions_bills_investment_endpoints -v`
Expected: FAIL (404 on the new routes).

- [ ] **Step 3: Add schemas** — append to `backend/app/schemas.py`:

```python
class SubscriptionOut(BaseModel):
    name: str
    merchant_name: str | None
    amount: float | None
    frequency: str
    next_date: str | None
    category: str


class BillOut(BaseModel):
    name: str
    sub: str
    amount: float | None
    due_date: str | None
    kind: str
    auto: bool


class InvestmentTxnOut(BaseModel):
    type: str
    name: str
    ticker: str | None
    quantity: float
    amount: float
    price: float | None
    date: str | None
    currency: str


class ReauthStartOut(BaseModel):
    hosted_link_url: str
    link_token: str
```

- [ ] **Step 4: Add the endpoints** — in `backend/app/routers/finance.py`, extend the schema import and add routes after `holdings`:

```python
@router.get("/subscriptions", response_model=list[SubscriptionOut])
def subscriptions() -> list[dict]:
    return store.finance_subscriptions()


@router.get("/bills", response_model=list[BillOut])
def bills() -> list[dict]:
    return store.finance_bills()


@router.get("/investment-transactions", response_model=list[InvestmentTxnOut])
def investment_transactions(days: int | None = Query(default=None)) -> list[dict]:
    return store.finance_investment_transactions(days)
```

(Add `SubscriptionOut, BillOut, InvestmentTxnOut, ReauthStartOut` to the `from ..schemas import (...)` block.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_finance_api.py::test_subscriptions_bills_investment_endpoints -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas.py backend/app/routers/finance.py backend/tests/test_finance_api.py
git commit -m "feat(finance): GET subscriptions/bills/investment-transactions endpoints

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 14: API — update-mode reauth endpoints

**Files:**
- Modify: `backend/app/routers/finance.py` (two routes)
- Test: `backend/tests/test_finance_api.py` (append)

**Interfaces:**
- Consumes: `create_link_token(kind, access_token=…)` (Task 6), `store.set_finance_item_status`, `finance_sync.tick`.
- Produces: `POST /api/finance/items/{item_id}/reauth/start` → `ReauthStartOut`; `POST /api/finance/items/{item_id}/reauth/complete` → `FinanceStatus`.

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_finance_api.py`:

```python
def test_reauth_start_and_complete(client):
    from tests.fakes import FakePlaidProvider
    p = FakePlaidProvider(item=NormalizedItem(item_id="itm1", institution_id="ins_1",
                                              institution_name="Chase", products=["transactions"]))
    providers.configure([p])
    client.post("/api/finance/link/complete", json={"link_token": "l"})
    store.set_finance_item_status("itm1", "needs_reauth")
    start = client.post("/api/finance/items/itm1/reauth/start")
    assert start.status_code == 200 and start.json()["hosted_link_url"] == "https://plaid/hl"
    done = client.post("/api/finance/items/itm1/reauth/complete")
    assert done.status_code == 200
    assert store.get_finance_item("itm1")["status"] == "active"     # flipped back
    assert client.post("/api/finance/items/nope/reauth/start").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_finance_api.py::test_reauth_start_and_complete -v`
Expected: FAIL (404 on reauth routes).

- [ ] **Step 3: Implement** — in `backend/app/routers/finance.py`, add after `disconnect`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_finance_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/finance.py backend/tests/test_finance_api.py
git commit -m "feat(finance): update-mode reauth start/complete endpoints

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 15: Assistant read tools

**Files:**
- Modify: `backend/app/tools.py` (run-fns after `_get_holdings`; register in `DEFINITIONS`)
- Test: `backend/tests/test_finance_tools.py` (append)

**Interfaces:**
- Produces: tools `get_subscriptions`, `get_bills`, `get_investment_transactions` (read-only, `{"screen":"finance"}` action).

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_finance_tools.py`:

```python
def test_finance_slice2_read_tools_registered_and_run():
    names = {d["name"] for d in tools.DEFINITIONS}
    assert {"get_subscriptions", "get_bills", "get_investment_transactions"} <= names
    result, action = tools.execute("get_subscriptions", {})
    assert action["screen"] == "finance"
    assert isinstance(json.loads(result), list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_finance_tools.py::test_finance_slice2_read_tools_registered_and_run -v`
Expected: FAIL (tools not registered).

- [ ] **Step 3: Implement** — in `backend/app/tools.py`, add run-fns after `_get_holdings`:

```python
def _get_subscriptions(args: dict):
    return store.finance_subscriptions(), _finance_action("Subscriptions", "Recurring subscriptions")


def _get_bills(args: dict):
    return store.finance_bills(), _finance_action("Bills", "Upcoming bills")


def _get_investment_transactions(args: dict):
    return store.finance_investment_transactions(args.get("days")), _finance_action(
        "Investment activity", "Buys, sells and dividends")
```

Register in `DEFINITIONS` (after `get_holdings`):

```python
    {"name": "get_subscriptions",
     "description": "The user's recurring subscriptions (name, amount, cadence, next renewal).",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
     "run": _get_subscriptions},
    {"name": "get_bills",
     "description": "Upcoming bills and loan/credit-card payments with due dates.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
     "run": _get_bills},
    {"name": "get_investment_transactions",
     "description": "Investment buys, sells and dividends, optionally limited to the last N days.",
     "input_schema": {"type": "object", "properties": {
         "days": {"type": "integer"}}, "additionalProperties": False},
     "run": _get_investment_transactions},
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_finance_tools.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools.py backend/tests/test_finance_tools.py
git commit -m "feat(finance): assistant read tools for subscriptions/bills/investment activity

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 16: Frontend — API client + live panels + investment ledger + reauth rewire

**Files:**
- Modify: `frontend/src/lib/api.js` (finance block ~lines 231-236)
- Modify: `frontend/src/screens/FinanceScreen.jsx`
- Verify: `cd frontend && npm run build`

**Interfaces:**
- Consumes: the new endpoints (Tasks 13–14).
- Produces: `api.financeSubscriptions()`, `api.financeBills()`, `api.financeInvestmentTransactions(days)`, `api.financeReauthStart(itemId)`, `api.financeReauthComplete(itemId)`; live Subscriptions/Bills/Investment panels; reauth via update mode.

- [ ] **Step 1: Add API methods** — in `frontend/src/lib/api.js`, in the finance block:

```javascript
  financeSubscriptions: () => request('/api/finance/subscriptions'),
  financeBills: () => request('/api/finance/bills'),
  financeInvestmentTransactions: (days) => request(`/api/finance/investment-transactions${days ? `?days=${days}` : ''}`),
  financeReauthStart: (itemId) => request(`/api/finance/items/${itemId}/reauth/start`, { method: 'POST' }),
  financeReauthComplete: (itemId) => request(`/api/finance/items/${itemId}/reauth/complete`, { method: 'POST' }),
```

- [ ] **Step 2: Wire state + reads** — in `FinanceScreen.jsx`: delete `SAMPLE_SUBS`/`SAMPLE_BILLS` (lines 16-25); add state `const [subs, setSubs] = React.useState(null)`, `const [bills, setBills] = React.useState(null)`, `const [invTxns, setInvTxns] = React.useState(null)`; add to `refresh()`:

```javascript
    api.financeSubscriptions().then((s) => { if (s) setSubs(s) }).catch(() => {})
    api.financeBills().then((b) => { if (b) setBills(b) }).catch(() => {})
    api.financeInvestmentTransactions().then((t) => { if (t) setInvTxns(t) }).catch(() => {})
```

- [ ] **Step 3: Render live Subscriptions + Bills** — replace the sample-panels block (lines 216-236) with live data (drop the "Sample · slice 2" badges):

```jsx
      <div className="kit-grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
        <Card title="Subscriptions">
          {(subs || []).length === 0 && <p className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>No subscriptions detected yet — they appear after a few weeks of transactions.</p>}
          {(subs || []).map((s, i) => (
            <div className="kit-sub" key={i}>
              <span className="kit-sub__logo" style={{ background: 'var(--plum-600)' }}>{(s.name || '?').slice(0, 1)}</span>
              <div className="kit-sub__main"><p className="kit-row__title">{s.name}</p><p className="kit-row__sub">{money(s.amount)} · {(s.frequency || '').toLowerCase()}</p></div>
              <span className="kit-row__sub" style={{ fontFamily: 'var(--font-mono)' }}>{s.next_date ? `Renews ${s.next_date}` : ''}</span>
            </div>
          ))}
        </Card>
        <Card title="Bills & recurring">
          {(bills || []).length === 0 && <p className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>No bills detected yet — connect a bank with recurring payments.</p>}
          {(bills || []).map((b, i) => (
            <div className="kit-sub" key={i}>
              <span className="kit-workout__ico" style={{ width: 38, height: 38, background: 'var(--honey-100)', color: 'var(--honey-600)' }}><Icon name={b.kind === 'liability' ? 'building-2' : 'wifi'} /></span>
              <div className="kit-sub__main"><p className="kit-row__title">{b.name}</p><p className="kit-row__sub">{b.sub}{b.due_date ? ` · Due ${b.due_date}` : ''}</p></div>
              <span className="kit-row__amt">{money(b.amount)}</span>
            </div>
          ))}
        </Card>
      </div>
```

- [ ] **Step 4: Add the Investment activity ledger** — after the net-worth/holdings grid (after line 181), add a card:

```jsx
      <Card title="Investment activity">
        {(invTxns || []).length === 0 && <p className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>No investment activity — connect Coinbase or a brokerage.</p>}
        {(invTxns || []).slice(0, 12).map((t, i) => (
          <div className="kit-row" key={i}>
            <span className="kit-cat" style={{ background: 'var(--paper-300)' }} />
            <div className="kit-row__main">
              <p className="kit-row__title">{t.name}</p>
              <p className="kit-row__sub">{t.type} · {t.ticker || ''} · {t.date}</p>
            </div>
            <span className={`kit-row__amt ${t.amount < 0 ? 'kit-amt--pos' : 'kit-amt--neg'}`}>
              {t.amount < 0 ? '+' : '−'}{money(Math.abs(t.amount))}
            </span>
          </div>
        ))}
      </Card>
```

- [ ] **Step 5: Rewire reauth** — add handler and repoint the two "Reconnect" buttons (lines 119-136) away from `startLink`:

```javascript
  const reauth = (itemId) => {
    api.financeReauthStart(itemId).then((r) => {
      if (r?.hosted_link_url) {
        window.open(r.hosted_link_url, '_blank', 'noopener')
        setPendingLink({ reauthItemId: itemId })
        setLinkMsg('Finish reconnecting in the Plaid tab, then click "Finish linking".')
      }
    }).catch(() => setLinkMsg('Could not start reconnect. Try again.'))
  }
```

Update `finishLink` to handle the reauth case:

```javascript
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
```

Change the per-item "Reconnect" `Badge` region and the needs-reauth banner button `onClick` from `() => startLink('bank')` to `() => reauth(it.item_id)` / `() => reauth(needsReauth[0].item_id)` respectively.

- [ ] **Step 6: Verify the build**

Run: `cd frontend && npm run build`
Expected: build succeeds with no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/api.js frontend/src/screens/FinanceScreen.jsx
git commit -m "feat(finance): live subscriptions/bills panels, investment ledger, update-mode reauth UI

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 17: Docs — finance.md + README status

**Files:**
- Modify: `docs/finance.md` (flip slice-2 checkboxes; remove "sample data" notes at lines ~14, ~21, ~71, ~75)
- Modify: `docs/README.md` (finance status row)

**Interfaces:** none (docs only).

- [ ] **Step 1: Update `docs/finance.md`** — change "Subscriptions and bills remain a future slice." and "Subscriptions and Bills panels still render sample data (slice 2)." to reflect that they are now **live** (recurring streams + liabilities); check the `- [ ] **Subscriptions + Bills** live sync (slice 2).` box to `- [x]`; note investment transaction history + expanded categories + update-mode reauth shipped in slice 2; mention bills/renewals now appear on the Calendar.

- [ ] **Step 2: Update `docs/README.md`** — bump the finance row to reflect slice-2 delivered (recurring/bills/liabilities/investment-ledger/calendar-merge/reauth), migration `0009`.

- [ ] **Step 3: Commit**

```bash
git add docs/finance.md docs/README.md
git commit -m "docs(finance): mark slice-2 (recurring, bills, investment ledger) shipped

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 18: Privacy Wave 5 draft (liabilities) — publish is a user gate

**Files:**
- Modify: `docs/privacy-policy.md` (Plaid block: §1 connected-service data, §3 provider row, §4 per-integration block, §6 retention; effective-date bump)
- Modify (if present locally): `scuffed-corporation/privacy/index.html`
- **Do NOT publish the gist** — that is a user-approval action (flag it, don't do it).

**Interfaces:** none (docs only).

- [ ] **Step 1: Amend `docs/privacy-policy.md`** — extend the Plaid disclosure: now also **stored** are recurring subscription/bill streams and **liabilities** (loan & credit-card statement balances, minimum payments, next-payment due dates, APRs) and investment transaction history; still read-only; still never sent to Anthropic except on an explicit finance question; disconnect deletes it within 30 days. Bump the effective date.

- [ ] **Step 2: Mirror into the corp HTML** if `scuffed-corporation/privacy/index.html` exists in the working tree; otherwise note it in the commit body as pending.

- [ ] **Step 3: Commit (canonical + corp only)**

```bash
git add docs/privacy-policy.md
git commit -m "docs(privacy): Wave 5 — disclose liabilities + recurring + investment activity (Plaid slice 2)

Gist publish pending user approval.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 4: Surface the gate to the user** — report that the privacy gist needs the user to publish it (same approval flow as prior waves); do not attempt to publish it autonomously.

---

### Task 19: Full-suite green + report

**Files:** none (verification).

- [ ] **Step 1: Run the whole backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all pass (slice-1 baseline 49 finance tests + the ~18 new tests; no regressions elsewhere). Investigate any failure before proceeding — do not proceed on red.

- [ ] **Step 2: Verify the frontend build**

Run: `cd frontend && npm run build`
Expected: success.

- [ ] **Step 3: Report the pass count** (user rule) — state "X passed / Y skipped" from the pytest summary.

- [ ] **Step 4: (Optional) live smoke extension** — extend `backend/app/smoke_plaid.py` to print recurring/liabilities/investment-transaction counts after a live link (not in CI); defer running it to the live gate (spec §14).

---

## Self-Review

**1. Spec coverage:**
- Subscriptions live (§1.1) → Tasks 3, 8, 13, 16. Bills live incl. liabilities (§1.1) → Tasks 4, 8, 13, 16. ✓
- Bills/renewals → Calendar read-merge (§2) → Task 10. ✓
- Expanded budget categories + reallocate clamp (§3, §6.6) → Task 11. ✓
- Investment transaction history, separate ledger (§4) → Tasks 5, 9, 13, 16. ✓
- Update-mode reauth incl. duplicate-item fix (§5, §8) → Tasks 6, 14, 16. ✓
- Liabilities consent change (§12) → Task 4. ✓
- Migration 0009 + models + ALL_TABLES (§5) → Task 1. ✓
- Provider methods + dataclasses + protocol (§4) → Tasks 2–6. ✓
- Sync branches + feature-absent (§5) → Task 12. ✓
- Assistant read tools (§10) → Task 15. ✓
- Privacy Wave 5, gist as user gate (§11) → Task 18. ✓
- Docs (§11) → Task 17. Tests across layers (§13) → every task + Task 19. ✓
- Notifications deferred to slice 3 (§2) → correctly absent. ✓

**2. Placeholder scan:** No "TBD/TODO/handle edge cases"; every code step carries real code and exact commands. Task 7's note about a read-dependent assertion is explicit about which task (9) makes it green.

**3. Type consistency:** `NormalizedRecurringStream`/`NormalizedLiability`/`NormalizedInvestmentTransaction` field names are identical across base.py (Task 2), provider parsers (Tasks 3–5), store upserts (Task 7), and sync (Task 12). Store read dict keys (`name/amount/next_date` for subs; `name/sub/amount/due_date/kind/auto` for bills; `type/name/ticker/quantity/amount/price/date/currency` for investment txns) match the schemas (Task 13) and the frontend (Task 16). `create_link_token(kind, access_token=None)` signature is consistent across base.py, plaid.py, and FakePlaidProvider. `finance_investment_transactions`, `finance_subscriptions`, `finance_bills`, `finance_calendar_events`, `recurring_kind` names are used identically wherever referenced.
