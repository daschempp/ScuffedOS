# M7 Finance/Plaid Slice-1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Graduate the Finance screen from in-component sample data to live, read-only data from the user's real accounts via Plaid — accounts/balances, transactions, and investment holdings (incl. Coinbase crypto) — plus editable local budgets.

**Architecture:** Clones the M6 Moodle groove — a hand-rolled `httpx` provider (`providers/plaid.py`, no vendor SDK) → registry → `finance_sync.py` background tick → `store.py` `# ---- finance ----` section → `routers/finance.py` (reads from Postgres only) → live `FinanceScreen.jsx`. Diverges on one axis: Plaid is **multi-Item**, so per-institution credentials live in a new `finance_items` table (not the single-row `provider_accounts`), and the sync loops over items, injecting each Item's `access_token`. Connect is Plaid **Hosted Link** (open Plaid's page → poll `/link/token/get` → exchange), so — like Moodle's paste flow — it lives on the finance router, not the shared `/api/oauth/*` router. All reads come from the DB; the synced tables *are* the cache.

**Tech Stack:** Python 3.14 · FastAPI · SQLAlchemy 2.0 (`Mapped`/`mapped_column`) · Alembic · Pydantic v2 · `httpx` · pytest over `TestClient` · Vite + React (JSX).

## Global Constraints

Every task's requirements implicitly include these (copied verbatim from the spec `docs/superpowers/specs/2026-07-05-finance-plaid-slice1-design.md`):

- **No vendor SDK** — the Plaid client is hand-rolled `httpx` (repo rule). Do **not** add `plaid-python` (or any new backend dependency).
- **No new frontend dependencies** and **no CDN scripts** — Hosted Link is why (`react-plaid-link` / `cdn.plaid.com` are forbidden). Reuse `ui.jsx` primitives + `kit-*`/`sa-*` classes + design tokens; no hardcoded colors.
- **Money is `Decimal`/`Numeric`, never float** — storage `Numeric` columns; arithmetic (summary, budget spend, reallocation) in `Decimal`; convert to `float` only at the JSON boundary. `iso_currency` stored alongside every amount.
- **Migration** `0008_finance`, `down_revision = "0007"` (current head is `0007_email_actions`). Six new tables. Register all six in `tests/test_migrations.py` `ALL_TABLES`.
- **Suite stays green** — baseline **526 passed / 1 skipped** (SQLite, verified 2026-07-05). Every task ends green; report the pass count. Both the SQLite and (CI) Postgres legs must pass.
- **`source = "plaid"`** on every synced row; unique key `(owner, source, source_id)` (except `finance_budgets` → `(owner, category, month)` and `finance_holdings` → `(owner, account_id, security_id)`).
- **Fixed budget categories** this slice: `["Groceries", "Rent & bills", "Dining out", "Transport", "Savings", "Other"]`. Custom categories are slice 2.
- **`PLAID_ENV`** is a setting defaulting to `"production"`; the host derives from it (`https://{sandbox|production}.plaid.com`). Tests never hit real Plaid — fakes only, wired through `conftest.no_external_services`.
- **Read-only against Plaid** — the app **never** initiates a transfer or any bank write. "Move to savings" = local budget-limit reallocation only. Real transfers are a permanent non-goal.
- **Access tokens are server-side only** — never serialized to any client response; only derived fields (institution name, status, products) surface.
- **TDD** — write the failing test first, watch it fail, implement minimally, watch it pass, commit. Run backend tests with `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest -q`.

---

## File Structure

**New backend files:**
- `backend/app/providers/plaid.py` — hand-rolled Plaid REST client (all Plaid field/endpoint names confined here).
- `backend/app/finance_sync.py` — background tick + on-demand trigger; loops over `finance_items`.
- `backend/app/routers/finance.py` — `/api/finance/*` (Hosted-Link connect + DB-only reads + local budget writes).
- `backend/alembic/versions/0008_finance.py` — the six-table migration.
- `backend/app/smoke_plaid.py` — live end-to-end smoke (Reporter, exit 0/1/2, not in CI).
- `backend/tests/test_finance_config.py`, `test_finance_models.py`, `test_finance_store.py`, `test_plaid_provider.py`, `test_finance_sync.py`, `test_finance_api.py`, `test_finance_tools.py`.

**Modified backend files:**
- `backend/app/providers/base.py` — `Normalized{Item,Account,Transaction,Security,Holding}` + `TransactionsDelta` dataclasses; `PlaidProvider` Protocol.
- `backend/app/providers/__init__.py` — register `PlaidProvider()` in `_build_real`.
- `backend/app/models.py` — six ORM models.
- `backend/app/store.py` — `# ---- finance ----` section + module-level `_finance_*_dict` serializers + category map.
- `backend/app/schemas.py` — Finance request/response models.
- `backend/app/routers/__init__`? (no — routers are imported in `main.py`).
- `backend/app/main.py` — import + `include_router(finance.router)` + lifespan `finance_sync.run_loop()`.
- `backend/app/config.py` + `backend/.env.example` — `PLAID_*` / `FINANCE_SYNC_*` settings.
- `backend/app/tools.py` — finance read tools + local budget write tools + `_finance_action` card.
- `backend/tests/conftest.py` — add `finance_sync.configure(None)`/`("unset")` to `no_external_services`.
- `backend/tests/fakes.py` — `FakePlaidHTTP` (transport) + `FakePlaidProvider` (protocol) + payload builders.
- `backend/tests/test_migrations.py` — six table names into `ALL_TABLES`.

**Modified frontend files:**
- `frontend/src/lib/api.js` — `finance*` method block.
- `frontend/src/screens/FinanceScreen.jsx` — replace sample-only component with the live screen.
- (`App.jsx` `finance` branch + `Sidebar.jsx` `Finance` nav item already exist — **no edit needed**.)

**Docs:**
- `docs/finance.md` (rewrite status), `docs/README.md` (row), `docs/privacy-policy.md` (Wave 4) + corp site + gist.

---

### Task 1: Config settings + `.env.example`

**Files:**
- Modify: `backend/app/config.py` (append to `Settings`, after the Moodle block)
- Modify: `backend/.env.example`
- Test: `backend/tests/test_finance_config.py`

**Interfaces:**
- Produces: `settings.plaid_client_id`, `settings.plaid_secret`, `settings.plaid_env`, `settings.plaid_country_codes` (`list[str]`), `settings.finance_sync_enabled` (`bool`), `settings.finance_sync_seconds` (`int`), `settings.plaid_backfill_days` (`int`). All read elsewhere as `settings.*`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_finance_config.py
"""M7 Finance (Plaid) settings — defaults + env override (contract §8)."""
from app.config import Settings


def test_finance_settings_defaults():
    s = Settings(_env_file=None)
    assert s.plaid_env == "production"
    assert s.plaid_client_id == ""
    assert s.plaid_secret == ""
    assert s.plaid_country_codes == ["US"]
    assert s.finance_sync_enabled is True
    assert s.finance_sync_seconds == 1800
    assert s.plaid_backfill_days == 90


def test_finance_settings_env_override(monkeypatch):
    monkeypatch.setenv("PLAID_ENV", "sandbox")
    monkeypatch.setenv("PLAID_CLIENT_ID", "cid")
    monkeypatch.setenv("PLAID_SECRET", "sek")
    s = Settings(_env_file=None)
    assert s.plaid_env == "sandbox"
    assert s.plaid_client_id == "cid"
    assert s.plaid_secret == "sek"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_config.py -q`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'plaid_env'`.

- [ ] **Step 3: Add the settings block**

In `backend/app/config.py`, immediately after the `# ---- M6 School (Moodle) ----` block (right before `settings = Settings()`):

```python
    # ---- M7 Finance (Plaid) ----
    # Plaid REST lives at {sandbox|production}.plaid.com. Credentials come from
    # the Plaid dashboard (Production keys once the use-case is approved); the
    # per-Item access_tokens live in the finance_items table, never here. The
    # connect flow is Hosted Link (a Plaid-hosted page), so no redirect URI is
    # registered and no public callback is needed. Read-only — we never move money.
    plaid_client_id: str = ""
    plaid_secret: str = ""
    plaid_env: str = "production"                 # "sandbox" | "production"
    plaid_country_codes: list[str] = ["US"]

    # Background finance-sync (mirrors moodle_sync_enabled / moodle_sync_seconds).
    finance_sync_enabled: bool = True
    finance_sync_seconds: int = 1800              # 30 min
    plaid_backfill_days: int = 90                 # first-sync transaction history window
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_config.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Update `.env.example`**

Append to `backend/.env.example`:

```
# ---- M7 Finance (Plaid) ----
PLAID_CLIENT_ID=""            # from the Plaid dashboard (Production keys)
PLAID_SECRET=""              # Production secret
PLAID_ENV="production"       # sandbox | production  (host: {env}.plaid.com)
PLAID_COUNTRY_CODES="US"
FINANCE_SYNC_ENABLED=True
FINANCE_SYNC_SECONDS=1800    # 30 min
PLAID_BACKFILL_DAYS=90       # first-sync transaction history window
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py backend/.env.example backend/tests/test_finance_config.py
git commit -m "feat(finance): M7 Plaid settings + .env.example"
```

---

### Task 2: Normalized dataclasses + `PlaidProvider` Protocol

**Files:**
- Modify: `backend/app/providers/base.py` (append after `MoodleProvider` Protocol)
- Test: `backend/tests/test_finance_models.py` (create; a dataclass smoke test — model tests join it in Task 3)

**Interfaces:**
- Produces (importable from `app.providers.base`):
  - `NormalizedItem(item_id: str, institution_id: str, institution_name: str, products: list[str])`
  - `NormalizedAccount(source, source_id, item_id, name, official_name, mask, type, subtype, current_balance: Decimal | None, available_balance: Decimal | None, iso_currency)`
  - `NormalizedTransaction(source, source_id, account_id, item_id, name, merchant_name, amount: Decimal, iso_currency, date: date, authorized_date: date | None, pending: bool, category_primary, category_detailed, payment_channel)`
  - `NormalizedSecurity(source, source_id, name, ticker_symbol, type, close_price: Decimal | None, iso_currency, is_cash_equivalent: bool)`
  - `NormalizedHolding(source, item_id, account_id, security_id, quantity: Decimal, cost_basis: Decimal | None, institution_value: Decimal, institution_price: Decimal | None, iso_currency)`
  - `TransactionsDelta(added: list[NormalizedTransaction], modified: list[NormalizedTransaction], removed: list[str], next_cursor: str, has_more: bool)`
  - `PlaidProvider` Protocol (runtime-checkable), distinguishing method `get_accounts`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_finance_models.py
"""M7 Finance — normalized dataclasses + ORM models (contract §2/§4)."""
from datetime import date
from decimal import Decimal

from app.providers.base import (
    NormalizedAccount,
    NormalizedHolding,
    NormalizedItem,
    NormalizedSecurity,
    NormalizedTransaction,
    PlaidProvider,
    TransactionsDelta,
)


def test_normalized_dataclasses_construct():
    item = NormalizedItem(item_id="itm1", institution_id="ins_1",
                          institution_name="Chase", products=["transactions"])
    assert item.products == ["transactions"]

    acct = NormalizedAccount(
        source="plaid", source_id="acc1", item_id="itm1", name="Checking",
        official_name=None, mask="1234", type="depository", subtype="checking",
        current_balance=Decimal("100.50"), available_balance=Decimal("90.00"),
        iso_currency="USD",
    )
    assert acct.current_balance == Decimal("100.50")

    txn = NormalizedTransaction(
        source="plaid", source_id="t1", account_id="acc1", item_id="itm1",
        name="Whole Foods", merchant_name="Whole Foods", amount=Decimal("64.20"),
        iso_currency="USD", date=date(2026, 6, 8), authorized_date=None,
        pending=False, category_primary="FOOD_AND_DRINK",
        category_detailed="FOOD_AND_DRINK_GROCERIES", payment_channel="in store",
    )
    assert txn.amount == Decimal("64.20")

    sec = NormalizedSecurity(source="plaid", source_id="s1", name="Bitcoin",
                             ticker_symbol="BTC", type="cryptocurrency",
                             close_price=Decimal("60000"), iso_currency="USD",
                             is_cash_equivalent=False)
    assert sec.type == "cryptocurrency"

    hold = NormalizedHolding(source="plaid", item_id="itm1", account_id="acc9",
                             security_id="s1", quantity=Decimal("0.05"),
                             cost_basis=Decimal("2000"), institution_value=Decimal("3000"),
                             institution_price=Decimal("60000"), iso_currency="USD")
    assert hold.institution_value == Decimal("3000")

    delta = TransactionsDelta(added=[txn], modified=[], removed=["t9"],
                              next_cursor="CUR2", has_more=False)
    assert delta.removed == ["t9"]


def test_plaid_provider_is_runtime_checkable():
    class Stub:
        name = "plaid"
        def get_accounts(self, access_token): return []
    assert isinstance(Stub(), PlaidProvider)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_models.py::test_normalized_dataclasses_construct -q`
Expected: FAIL — `ImportError: cannot import name 'NormalizedItem'`.

- [ ] **Step 3: Add dataclasses + Protocol to `base.py`**

At the top of `backend/app/providers/base.py`, extend the imports:

```python
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol, runtime_checkable
```

Append after the `MoodleProvider` Protocol (end of file):

```python
# ---- Finance / Plaid (M7) ------------------------------------------------
@dataclass
class NormalizedItem:
    item_id: str                          # Plaid item_id
    institution_id: str
    institution_name: str
    products: list[str] = field(default_factory=list)   # ['transactions'] / ['investments']


@dataclass
class NormalizedAccount:
    source: str                           # 'plaid'
    source_id: str                        # Plaid account_id
    item_id: str
    name: str
    official_name: str | None
    mask: str | None
    type: str                             # depository | investment | credit | loan
    subtype: str | None                   # checking | savings | ira | 401k | brokerage | ...
    current_balance: Decimal | None = None
    available_balance: Decimal | None = None
    iso_currency: str = "USD"


@dataclass
class NormalizedTransaction:
    source: str                           # 'plaid'
    source_id: str                        # Plaid transaction_id
    account_id: str
    item_id: str
    name: str
    merchant_name: str | None
    amount: Decimal                       # Plaid sign: + = outflow (money leaving)
    iso_currency: str
    date: date                            # posted date
    authorized_date: date | None = None
    pending: bool = False
    category_primary: str = ""            # personal_finance_category.primary
    category_detailed: str = ""
    payment_channel: str = ""


@dataclass
class NormalizedSecurity:
    source: str                           # 'plaid'
    source_id: str                        # Plaid security_id
    name: str
    ticker_symbol: str | None
    type: str                             # equity | etf | mutual fund | cryptocurrency | ...
    close_price: Decimal | None = None
    iso_currency: str = "USD"
    is_cash_equivalent: bool = False


@dataclass
class NormalizedHolding:
    source: str                           # 'plaid'
    item_id: str
    account_id: str
    security_id: str
    quantity: Decimal
    cost_basis: Decimal | None = None
    institution_value: Decimal = Decimal("0")
    institution_price: Decimal | None = None
    iso_currency: str = "USD"


@dataclass
class TransactionsDelta:                   # one /transactions/sync page
    added: list[NormalizedTransaction] = field(default_factory=list)
    modified: list[NormalizedTransaction] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)   # transaction_ids
    next_cursor: str = ""
    has_more: bool = False


@runtime_checkable
class PlaidProvider(Protocol):
    """Read-only Plaid REST adapter. NOT an OAuthProvider (Hosted Link is a
    token exchange, not a redirect code flow). Distinguishing method
    get_accounts. Multi-Item: every data method takes an item's access_token."""
    name: str                             # 'plaid'

    def create_link_token(self, kind: str) -> dict: ...          # {'link_token','hosted_link_url',...}
    def get_link_public_token(self, link_token: str) -> str | None: ...
    def exchange_public_token(self, public_token: str) -> tuple[str, str]: ...  # (access_token, item_id)
    def get_item(self, access_token: str) -> NormalizedItem: ...
    def get_accounts(self, access_token: str) -> list[NormalizedAccount]: ...
    def sync_transactions(self, access_token: str, cursor: str | None) -> TransactionsDelta: ...
    def get_holdings(self, access_token: str) -> tuple[list[NormalizedAccount],
                                                       list[NormalizedSecurity],
                                                       list[NormalizedHolding]]: ...
    def remove_item(self, access_token: str) -> None: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_models.py -q`
Expected: PASS (2 passed) — `test_plaid_provider_is_runtime_checkable` passes because the Protocol is `@runtime_checkable` and `get_accounts` is the checked member.

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers/base.py backend/tests/test_finance_models.py
git commit -m "feat(finance): normalized Plaid dataclasses + PlaidProvider protocol"
```

---

### Task 3: ORM models (six finance tables)

**Files:**
- Modify: `backend/app/models.py` (append after the `MoodleNotification` model)
- Test: `backend/tests/test_finance_models.py` (extend)

**Interfaces:**
- Produces (importable from `app.models`): `FinanceItem`, `FinanceAccount`, `FinanceTransaction`, `FinanceSecurity`, `FinanceHolding`, `FinanceBudget`.
- Column conventions: `Numeric(16, 2)` for balances/amounts/values/limits; `Numeric(24, 8)` for `quantity`; `Numeric(20, 8)` for prices/cost_basis; `DateTime(timezone=True)` for timestamps; `JSONField` for `meta`; `Date` for transaction dates.

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_finance_models.py`:

```python
from datetime import datetime, timezone

from app.db import Base, make_engine, make_session_factory
from app.models import (
    FinanceAccount, FinanceBudget, FinanceHolding, FinanceItem,
    FinanceSecurity, FinanceTransaction,
)


def test_finance_models_persist_and_roundtrip():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s, s.begin():
        s.add(FinanceItem(owner="me", source="plaid", source_id="itm1",
                          access_token="tok", institution_id="ins_1",
                          institution_name="Chase", products=["transactions"],
                          status="active"))
        s.add(FinanceAccount(owner="me", source="plaid", source_id="acc1",
                             item_id="itm1", name="Checking", type="depository",
                             subtype="checking", current_balance=Decimal("100.50"),
                             iso_currency="USD"))
        s.add(FinanceTransaction(owner="me", source="plaid", source_id="t1",
                                 account_id="acc1", item_id="itm1", name="WF",
                                 amount=Decimal("64.20"), iso_currency="USD",
                                 date=date(2026, 6, 8), category_primary="FOOD_AND_DRINK"))
        s.add(FinanceSecurity(owner="me", source="plaid", source_id="s1",
                              name="Bitcoin", ticker_symbol="BTC", type="cryptocurrency",
                              iso_currency="USD"))
        s.add(FinanceHolding(owner="me", account_id="acc9", item_id="itm1",
                             security_id="s1", quantity=Decimal("0.05"),
                             institution_value=Decimal("3000"), iso_currency="USD"))
        s.add(FinanceBudget(owner="me", category="Groceries", month="2026-06",
                            limit_amount=Decimal("400")))
    with Session() as s:
        acc = s.query(FinanceAccount).one()
        assert acc.current_balance == Decimal("100.50")
        assert s.query(FinanceHolding).one().quantity == Decimal("0.05")
    engine.dispose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_models.py::test_finance_models_persist_and_roundtrip -q`
Expected: FAIL — `ImportError: cannot import name 'FinanceItem'`.

- [ ] **Step 3: Add the six models**

At the top of `backend/app/models.py`, add `Numeric` to the `sqlalchemy` import and `Decimal` to the datetime line:

```python
from decimal import Decimal
from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Index, JSON, Numeric, String, Text,
    UniqueConstraint, text,
)
```

Append after the `MoodleNotification` class:

```python
# ---- Finance / Plaid (M7) -------------------------------------------------
class FinanceItem(Base):
    """One linked Plaid Item (a bank/Coinbase connection). access_token is
    server-side only, never serialized. cursor is the /transactions/sync
    cursor; products drives the per-Item sync branch (transactions/investments)."""

    __tablename__ = "finance_items"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id",
                         name="uq_finance_items_owner_source_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)        # 'plaid'
    source_id: Mapped[str] = mapped_column(String(128), index=True)    # Plaid item_id
    access_token: Mapped[str | None] = mapped_column(Text)             # server-side only
    institution_id: Mapped[str] = mapped_column(String(64), default="")
    institution_name: Mapped[str] = mapped_column(String(255), default="")
    products: Mapped[list] = mapped_column(JSONField, default=list)    # ['transactions']/['investments']
    status: Mapped[str] = mapped_column(String(16), default="active")  # 'active' | 'needs_reauth'
    cursor: Mapped[str | None] = mapped_column(Text)                   # /transactions/sync cursor
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FinanceAccount(Base):
    """A Plaid account within an Item. type/subtype drive net-worth bucketing."""

    __tablename__ = "finance_accounts"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id",
                         name="uq_finance_accounts_owner_source_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)        # 'plaid'
    source_id: Mapped[str] = mapped_column(String(128), index=True)    # Plaid account_id
    item_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    official_name: Mapped[str | None] = mapped_column(String(255))
    mask: Mapped[str | None] = mapped_column(String(16))
    type: Mapped[str] = mapped_column(String(32), default="")          # depository|investment|credit|loan
    subtype: Mapped[str | None] = mapped_column(String(48))
    current_balance: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    available_balance: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    iso_currency: Mapped[str] = mapped_column(String(8), default="USD")
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FinanceTransaction(Base):
    """A Plaid transaction. amount sign is Plaid's: + = outflow / money leaving."""

    __tablename__ = "finance_transactions"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id",
                         name="uq_finance_transactions_owner_source_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)        # 'plaid'
    source_id: Mapped[str] = mapped_column(String(128), index=True)    # Plaid transaction_id
    account_id: Mapped[str] = mapped_column(String(128), index=True)
    item_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(Text, default="")
    merchant_name: Mapped[str | None] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=0)
    iso_currency: Mapped[str] = mapped_column(String(8), default="USD")
    date: Mapped[date] = mapped_column(Date, index=True)
    authorized_date: Mapped[date | None] = mapped_column(Date)
    pending: Mapped[bool] = mapped_column(Boolean, default=False)
    category_primary: Mapped[str] = mapped_column(String(64), default="")
    category_detailed: Mapped[str] = mapped_column(String(128), default="")
    payment_channel: Mapped[str] = mapped_column(String(32), default="")
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FinanceSecurity(Base):
    """A security referenced by holdings. type='cryptocurrency' for Coinbase coins."""

    __tablename__ = "finance_securities"
    __table_args__ = (
        UniqueConstraint("owner", "source", "source_id",
                         name="uq_finance_securities_owner_source_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)        # 'plaid'
    source_id: Mapped[str] = mapped_column(String(128), index=True)    # Plaid security_id
    name: Mapped[str] = mapped_column(String(255), default="")
    ticker_symbol: Mapped[str | None] = mapped_column(String(32))
    type: Mapped[str] = mapped_column(String(48), default="")          # equity|etf|cryptocurrency|...
    close_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    iso_currency: Mapped[str] = mapped_column(String(8), default="USD")
    is_cash_equivalent: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FinanceHolding(Base):
    """An investment position (account x security). Keyed (owner, account_id,
    security_id) — Plaid gives holdings no id of their own."""

    __tablename__ = "finance_holdings"
    __table_args__ = (
        UniqueConstraint("owner", "account_id", "security_id",
                         name="uq_finance_holdings_owner_account_security"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    source: Mapped[str] = mapped_column(String(16), default="plaid", index=True)
    item_id: Mapped[str] = mapped_column(String(128), index=True)
    account_id: Mapped[str] = mapped_column(String(128), index=True)
    security_id: Mapped[str] = mapped_column(String(128), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=0)
    cost_basis: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    institution_value: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=0)
    institution_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    iso_currency: Mapped[str] = mapped_column(String(8), default="USD")
    meta: Mapped[dict] = mapped_column(JSONField, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FinanceBudget(Base):
    """A local, user-editable monthly budget limit per category. NOT from Plaid
    — spend is derived from finance_transactions at read time."""

    __tablename__ = "finance_budgets"
    __table_args__ = (
        UniqueConstraint("owner", "category", "month",
                         name="uq_finance_budgets_owner_category_month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="me", index=True)
    category: Mapped[str] = mapped_column(String(48), index=True)      # a fixed bucket name
    month: Mapped[str] = mapped_column(String(7), index=True)          # 'YYYY-MM'
    limit_amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_models.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/tests/test_finance_models.py
git commit -m "feat(finance): six SQLAlchemy models (items/accounts/transactions/securities/holdings/budgets)"
```

---

### Task 4: Migration `0008_finance` + `test_migrations` registration

**Files:**
- Create: `backend/alembic/versions/0008_finance.py`
- Modify: `backend/tests/test_migrations.py` (`ALL_TABLES`)
- Test: existing `backend/tests/test_migrations.py` (upgrade/downgrade + Postgres drift guard)

**Interfaces:**
- Consumes: the six models from Task 3.
- Produces: `revision = "0008"`, `down_revision = "0007"`; the six tables in the DB matching `Base.metadata` exactly (the `compare_metadata` drift guard must return `[]`).

- [ ] **Step 1: Add the six table names to `ALL_TABLES`**

In `backend/tests/test_migrations.py`, extend the `ALL_TABLES` set:

```python
    "moodle_courses", "moodle_deadlines", "moodle_assignments",
    "moodle_grades", "moodle_announcements", "moodle_notifications",
    "finance_items", "finance_accounts", "finance_transactions",
    "finance_securities", "finance_holdings", "finance_budgets",
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_migrations.py::test_upgrade_head_builds_full_schema -q`
Expected: FAIL — `assert ALL_TABLES <= tables` fails; the six `finance_*` tables are missing (no migration yet).

- [ ] **Step 3: Write the migration**

Create `backend/alembic/versions/0008_finance.py`:

```python
"""Finance domain (M7): Plaid items / accounts / transactions / securities /
holdings + local budgets.

Six tables. The five synced tables are keyed (owner, source, source_id) =
('plaid', <id>) for idempotent upsert; finance_holdings is keyed
(owner, account_id, security_id) and finance_budgets (owner, category, month).
Read-only against Plaid — access_tokens live in finance_items server-side.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

JSONField = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "finance_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("institution_id", sa.String(length=64), nullable=False),
        sa.Column("institution_name", sa.String(length=255), nullable=False),
        sa.Column("products", JSONField, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("owner", "source", "source_id",
                            name="uq_finance_items_owner_source_source_id"),
    )
    op.create_index(op.f("ix_finance_items_owner"), "finance_items", ["owner"])
    op.create_index(op.f("ix_finance_items_source"), "finance_items", ["source"])
    op.create_index(op.f("ix_finance_items_source_id"), "finance_items", ["source_id"])

    op.create_table(
        "finance_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("item_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("official_name", sa.String(length=255), nullable=True),
        sa.Column("mask", sa.String(length=16), nullable=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("subtype", sa.String(length=48), nullable=True),
        sa.Column("current_balance", sa.Numeric(16, 2), nullable=True),
        sa.Column("available_balance", sa.Numeric(16, 2), nullable=True),
        sa.Column("iso_currency", sa.String(length=8), nullable=False),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "source", "source_id",
                            name="uq_finance_accounts_owner_source_source_id"),
    )
    op.create_index(op.f("ix_finance_accounts_owner"), "finance_accounts", ["owner"])
    op.create_index(op.f("ix_finance_accounts_source"), "finance_accounts", ["source"])
    op.create_index(op.f("ix_finance_accounts_source_id"), "finance_accounts", ["source_id"])
    op.create_index(op.f("ix_finance_accounts_item_id"), "finance_accounts", ["item_id"])

    op.create_table(
        "finance_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("account_id", sa.String(length=128), nullable=False),
        sa.Column("item_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("merchant_name", sa.String(length=255), nullable=True),
        sa.Column("amount", sa.Numeric(16, 2), nullable=False),
        sa.Column("iso_currency", sa.String(length=8), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("authorized_date", sa.Date(), nullable=True),
        sa.Column("pending", sa.Boolean(), nullable=False),
        sa.Column("category_primary", sa.String(length=64), nullable=False),
        sa.Column("category_detailed", sa.String(length=128), nullable=False),
        sa.Column("payment_channel", sa.String(length=32), nullable=False),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "source", "source_id",
                            name="uq_finance_transactions_owner_source_source_id"),
    )
    op.create_index(op.f("ix_finance_transactions_owner"), "finance_transactions", ["owner"])
    op.create_index(op.f("ix_finance_transactions_source"), "finance_transactions", ["source"])
    op.create_index(op.f("ix_finance_transactions_source_id"), "finance_transactions", ["source_id"])
    op.create_index(op.f("ix_finance_transactions_account_id"), "finance_transactions", ["account_id"])
    op.create_index(op.f("ix_finance_transactions_item_id"), "finance_transactions", ["item_id"])
    op.create_index(op.f("ix_finance_transactions_date"), "finance_transactions", ["date"])

    op.create_table(
        "finance_securities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("ticker_symbol", sa.String(length=32), nullable=True),
        sa.Column("type", sa.String(length=48), nullable=False),
        sa.Column("close_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("iso_currency", sa.String(length=8), nullable=False),
        sa.Column("is_cash_equivalent", sa.Boolean(), nullable=False),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "source", "source_id",
                            name="uq_finance_securities_owner_source_source_id"),
    )
    op.create_index(op.f("ix_finance_securities_owner"), "finance_securities", ["owner"])
    op.create_index(op.f("ix_finance_securities_source"), "finance_securities", ["source"])
    op.create_index(op.f("ix_finance_securities_source_id"), "finance_securities", ["source_id"])

    op.create_table(
        "finance_holdings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("item_id", sa.String(length=128), nullable=False),
        sa.Column("account_id", sa.String(length=128), nullable=False),
        sa.Column("security_id", sa.String(length=128), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("cost_basis", sa.Numeric(20, 8), nullable=True),
        sa.Column("institution_value", sa.Numeric(16, 2), nullable=False),
        sa.Column("institution_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("iso_currency", sa.String(length=8), nullable=False),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "account_id", "security_id",
                            name="uq_finance_holdings_owner_account_security"),
    )
    op.create_index(op.f("ix_finance_holdings_owner"), "finance_holdings", ["owner"])
    op.create_index(op.f("ix_finance_holdings_source"), "finance_holdings", ["source"])
    op.create_index(op.f("ix_finance_holdings_item_id"), "finance_holdings", ["item_id"])
    op.create_index(op.f("ix_finance_holdings_account_id"), "finance_holdings", ["account_id"])
    op.create_index(op.f("ix_finance_holdings_security_id"), "finance_holdings", ["security_id"])

    op.create_table(
        "finance_budgets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=48), nullable=False),
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("limit_amount", sa.Numeric(16, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "category", "month",
                            name="uq_finance_budgets_owner_category_month"),
    )
    op.create_index(op.f("ix_finance_budgets_owner"), "finance_budgets", ["owner"])
    op.create_index(op.f("ix_finance_budgets_category"), "finance_budgets", ["category"])
    op.create_index(op.f("ix_finance_budgets_month"), "finance_budgets", ["month"])


def downgrade() -> None:
    op.drop_table("finance_budgets")
    op.drop_table("finance_holdings")
    op.drop_table("finance_securities")
    op.drop_table("finance_transactions")
    op.drop_table("finance_accounts")
    op.drop_table("finance_items")
```

- [ ] **Step 4: Run migration tests to verify they pass**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_migrations.py -q`
Expected: PASS — `test_upgrade_head_builds_full_schema` and `test_downgrade_base_removes_everything` pass. (The Postgres-only `compare_metadata` drift test is `skipped` on SQLite; it runs in CI. If a local Postgres is handy, run with `TEST_DATABASE_URL=postgresql://…` and confirm the drift diff is `[]` — a `Numeric` scale mismatch is the usual culprit.)

- [ ] **Step 5: Run the whole suite (baseline hold)**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest -q`
Expected: **532 passed, 1 skipped** (526 baseline + 6 new finance tests so far).

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/0008_finance.py backend/tests/test_migrations.py
git commit -m "feat(finance): migration 0008_finance (six tables) + ALL_TABLES"
```

---

### Task 5: Store — finance items CRUD + status + module-level serializers

**Files:**
- Modify: `backend/app/store.py` (imports; a module-level `_finance_item_dict`; a `# ---- finance ----` section between `# ---- moodle ----` and the next section)
- Test: `backend/tests/test_finance_store.py` (create)

**Interfaces:**
- Consumes: `FinanceItem` (Task 3), `NormalizedItem` (Task 2).
- Produces: `store.upsert_finance_item(item: NormalizedItem, access_token: str) -> dict`, `store.list_finance_items() -> list[dict]`, `store.get_finance_item(item_id) -> dict | None`, `store.get_finance_item_token(item_id) -> str | None`, `store.set_finance_item_status(item_id, status)`, `store.set_finance_item_cursor(item_id, cursor)`, `store.set_finance_item_synced(item_id, when=None)`, `store.delete_finance_item(item_id) -> bool`, `store.finance_status() -> dict`. The client-safe `_finance_item_dict` **omits `access_token`**.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_finance_store.py
"""M7 Finance store — items CRUD/status, accounts, transactions delta,
holdings, budgets, summary, net worth. No network; SQLite via conftest."""
from datetime import date
from decimal import Decimal

from app.providers.base import (
    NormalizedAccount, NormalizedHolding, NormalizedItem,
    NormalizedSecurity, NormalizedTransaction, TransactionsDelta,
)
from app.store import store


def _item(item_id="itm1", products=("transactions",), name="Chase"):
    return NormalizedItem(item_id=item_id, institution_id="ins_1",
                          institution_name=name, products=list(products))


def test_upsert_finance_item_is_idempotent_and_hides_token():
    first = store.upsert_finance_item(_item(), access_token="tok-A")
    second = store.upsert_finance_item(_item(name="Chase Bank"), access_token="tok-B")
    assert first["item_id"] == second["item_id"]
    assert second["institution_name"] == "Chase Bank"
    assert "access_token" not in second           # never serialized to clients
    assert len(store.list_finance_items()) == 1
    # Token retrievable only via the server-side accessor.
    assert store.get_finance_item_token("itm1") == "tok-B"


def test_finance_item_status_cursor_synced_and_delete():
    store.upsert_finance_item(_item(), access_token="tok")
    store.set_finance_item_cursor("itm1", "CURSOR-9")
    store.set_finance_item_status("itm1", "needs_reauth")
    row = store.get_finance_item("itm1")
    assert row["status"] == "needs_reauth"
    status = store.finance_status()
    assert status["connected"] is True and len(status["items"]) == 1
    assert store.delete_finance_item("itm1") is True
    assert store.list_finance_items() == []
    assert store.delete_finance_item("itm1") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_store.py::test_upsert_finance_item_is_idempotent_and_hides_token -q`
Expected: FAIL — `AttributeError: 'Store' object has no attribute 'upsert_finance_item'`.

- [ ] **Step 3: Extend store imports**

In `backend/app/store.py`, add `Decimal` and the finance models/dataclasses. In the `from .models import (...)` block add:

```python
    FinanceAccount,
    FinanceBudget,
    FinanceHolding,
    FinanceItem,
    FinanceSecurity,
    FinanceTransaction,
```

In the `from .providers.base import (...)` block add:

```python
    NormalizedAccount,
    NormalizedHolding,
    NormalizedItem,
    NormalizedSecurity,
    NormalizedTransaction,
    TransactionsDelta,
```

And near the top imports add `from decimal import Decimal` (join the existing `from datetime import ...` line region).

- [ ] **Step 4: Add the module-level serializer**

Near the other `_*_dict` builders (module level, e.g. by `_moodle_deadline_dict`), add:

```python
def _finance_item_dict(row: FinanceItem) -> dict:
    """Client-safe Item view — NO access_token, NO cursor."""
    return {
        "item_id": row.source_id,
        "institution_name": row.institution_name,
        "status": row.status,
        "products": list(row.products or []),
        "connected_at": aware_utc(row.connected_at),
        "last_sync_at": aware_utc(row.last_sync_at),
    }
```

- [ ] **Step 5: Add the `# ---- finance ----` items section to the `Store` class**

After the Moodle section (`delete_moodle_data`), add:

```python
    # ---- finance ----
    def _finance_item_row(self, s: Session, item_id: str) -> FinanceItem | None:
        from .config import settings
        return s.scalars(
            select(FinanceItem)
            .where(FinanceItem.owner == settings.owner)
            .where(FinanceItem.source == "plaid")
            .where(FinanceItem.source_id == item_id)
        ).first()

    @_retry_integrity
    def upsert_finance_item(self, item: NormalizedItem, access_token: str) -> dict:
        from .config import settings
        with self._session() as s, s.begin():
            row = self._finance_item_row(s, item.item_id)
            if row is None:
                row = FinanceItem(owner=settings.owner, source="plaid",
                                  source_id=item.item_id)
                s.add(row)
            row.access_token = access_token
            row.institution_id = item.institution_id
            row.institution_name = item.institution_name
            row.products = list(item.products or [])
            row.status = "active"
            s.flush()
            return _finance_item_dict(row)

    def list_finance_items(self) -> list[dict]:
        from .config import settings
        with self._session() as s:
            rows = s.scalars(
                select(FinanceItem)
                .where(FinanceItem.owner == settings.owner)
                .order_by(FinanceItem.id)
            ).all()
            return [_finance_item_dict(r) for r in rows]

    def get_finance_item(self, item_id: str) -> dict | None:
        with self._session() as s:
            row = self._finance_item_row(s, item_id)
            return _finance_item_dict(row) if row else None

    def get_finance_item_token(self, item_id: str) -> str | None:
        """Server-side only — the access_token for one Item (used by the sync)."""
        with self._session() as s:
            row = self._finance_item_row(s, item_id)
            return row.access_token if row else None

    def set_finance_item_status(self, item_id: str, status: str) -> None:
        with self._session() as s, s.begin():
            row = self._finance_item_row(s, item_id)
            if row is not None:
                row.status = status

    def set_finance_item_cursor(self, item_id: str, cursor: str | None) -> None:
        with self._session() as s, s.begin():
            row = self._finance_item_row(s, item_id)
            if row is not None:
                row.cursor = cursor

    def set_finance_item_synced(self, item_id: str, when: datetime | None = None) -> None:
        with self._session() as s, s.begin():
            row = self._finance_item_row(s, item_id)
            if row is not None:
                row.last_sync_at = _to_utc(when) if when else utcnow()

    def get_finance_item_cursor(self, item_id: str) -> str | None:
        """Server-side only — the /transactions/sync cursor for one Item."""
        with self._session() as s:
            row = self._finance_item_row(s, item_id)
            return row.cursor if row else None

    def delete_finance_item(self, item_id: str) -> bool:
        """Disconnect one Item: delete it + its accounts/transactions/holdings,
        then prune securities no surviving holding references. Returns True iff
        the Item existed."""
        from .config import settings
        with self._session() as s, s.begin():
            row = self._finance_item_row(s, item_id)
            if row is None:
                return False
            s.delete(row)
            for model in (FinanceAccount, FinanceTransaction, FinanceHolding):
                for r in s.scalars(
                    select(model)
                    .where(model.owner == settings.owner)
                    .where(model.item_id == item_id)
                ):
                    s.delete(r)
            # Prune orphan securities (no holding references them any more).
            live_sec_ids = set(s.scalars(
                select(FinanceHolding.security_id)
                .where(FinanceHolding.owner == settings.owner)
            ).all())
            for sec in s.scalars(
                select(FinanceSecurity).where(FinanceSecurity.owner == settings.owner)
            ):
                if sec.source_id not in live_sec_ids:
                    s.delete(sec)
            return True

    def finance_status(self) -> dict:
        items = self.list_finance_items()
        return {"connected": len(items) > 0, "items": items}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_store.py -q`
Expected: PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add backend/app/store.py backend/tests/test_finance_store.py
git commit -m "feat(finance): store — finance_items CRUD, status, token accessor"
```

---

### Task 6: Store — accounts, transactions, and `/transactions/sync` delta

**Files:**
- Modify: `backend/app/store.py` (finance section + serializers)
- Test: `backend/tests/test_finance_store.py` (extend)

**Interfaces:**
- Produces: `store.upsert_finance_account(a: NormalizedAccount) -> dict`, `store.list_finance_accounts() -> list[dict]`, `store.apply_transaction_delta(delta: TransactionsDelta) -> int`, `store.finance_transactions(days: int | None = None, account_id: str | None = None, category: str | None = None) -> list[dict]`. Transaction dicts carry `positive` (bool; `amount < 0`) and a display `amount` as `float`.

- [ ] **Step 1: Write the failing test** — append to `test_finance_store.py`:

```python
def _acct(source_id="acc1", item_id="itm1", type="depository", subtype="checking",
          current="100.00", available="90.00"):
    return NormalizedAccount(source="plaid", source_id=source_id, item_id=item_id,
                             name="Checking", official_name=None, mask="1234",
                             type=type, subtype=subtype,
                             current_balance=Decimal(current),
                             available_balance=Decimal(available), iso_currency="USD")


def _txn(source_id="t1", amount="64.20", d=date(2026, 6, 8), primary="FOOD_AND_DRINK",
         detailed="FOOD_AND_DRINK_GROCERIES", account_id="acc1"):
    return NormalizedTransaction(source="plaid", source_id=source_id, account_id=account_id,
                                 item_id="itm1", name="Whole Foods", merchant_name="Whole Foods",
                                 amount=Decimal(amount), iso_currency="USD", date=d,
                                 authorized_date=None, pending=False,
                                 category_primary=primary, category_detailed=detailed,
                                 payment_channel="in store")


def test_account_upsert_idempotent_and_serialized():
    store.upsert_finance_account(_acct())
    store.upsert_finance_account(_acct(current="150.00"))
    accs = store.list_finance_accounts()
    assert len(accs) == 1
    assert accs[0]["current_balance"] == 150.0
    assert accs[0]["type"] == "depository"


def test_apply_transaction_delta_upserts_and_removes():
    n = store.apply_transaction_delta(TransactionsDelta(
        added=[_txn("t1"), _txn("t2", amount="-3200.00", primary="INCOME")],
        modified=[], removed=[], next_cursor="C1", has_more=False))
    assert n == 2
    txns = store.finance_transactions()
    assert {t["source_id"] for t in txns} == {"t1", "t2"}
    income = next(t for t in txns if t["source_id"] == "t2")
    assert income["positive"] is True                 # amount < 0 → inflow
    # A second page modifies t1 and removes t2.
    store.apply_transaction_delta(TransactionsDelta(
        added=[], modified=[_txn("t1", amount="70.00")], removed=["t2"],
        next_cursor="C2", has_more=False))
    txns = store.finance_transactions()
    assert len(txns) == 1
    assert txns[0]["source_id"] == "t1" and txns[0]["amount"] == 70.0


def test_finance_transactions_filters():
    store.apply_transaction_delta(TransactionsDelta(
        added=[_txn("t1", account_id="acc1", primary="FOOD_AND_DRINK"),
               _txn("t2", account_id="acc2", primary="TRANSPORTATION")],
        modified=[], removed=[], next_cursor="C1", has_more=False))
    assert len(store.finance_transactions(account_id="acc1")) == 1
    assert len(store.finance_transactions(category="TRANSPORTATION")) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_store.py::test_apply_transaction_delta_upserts_and_removes -q`
Expected: FAIL — `AttributeError: 'Store' object has no attribute 'apply_transaction_delta'`.

- [ ] **Step 3: Add serializers**

At module level (with the other `_*_dict` builders):

```python
def _dec_to_float(x) -> float | None:
    return float(x) if x is not None else None


def _finance_account_dict(a: FinanceAccount) -> dict:
    return {
        "id": a.id,
        "source_id": a.source_id,
        "item_id": a.item_id,
        "name": a.name,
        "official_name": a.official_name,
        "mask": a.mask,
        "type": a.type,
        "subtype": a.subtype,
        "current_balance": _dec_to_float(a.current_balance),
        "available_balance": _dec_to_float(a.available_balance),
        "iso_currency": a.iso_currency,
    }


def _finance_transaction_dict(t: FinanceTransaction) -> dict:
    return {
        "id": t.id,
        "source_id": t.source_id,
        "account_id": t.account_id,
        "name": t.name,
        "merchant_name": t.merchant_name,
        "amount": _dec_to_float(t.amount),
        "positive": (t.amount is not None and t.amount < 0),   # inflow
        "iso_currency": t.iso_currency,
        "date": t.date.isoformat() if t.date else None,
        "pending": t.pending,
        "category": t.category_primary,
        "when": relative_when(_to_utc(datetime(t.date.year, t.date.month, t.date.day)))
                if t.date else "",
    }
```

- [ ] **Step 4: Add the account + transaction store methods** to the `# ---- finance ----` section:

```python
    def _finance_account_row(self, s: Session, source_id: str) -> FinanceAccount | None:
        from .config import settings
        return s.scalars(
            select(FinanceAccount)
            .where(FinanceAccount.owner == settings.owner)
            .where(FinanceAccount.source == "plaid")
            .where(FinanceAccount.source_id == source_id)
        ).first()

    @_retry_integrity
    def upsert_finance_account(self, a: NormalizedAccount) -> dict:
        from .config import settings
        with self._session() as s, s.begin():
            row = self._finance_account_row(s, a.source_id)
            if row is None:
                row = FinanceAccount(owner=settings.owner, source="plaid",
                                     source_id=a.source_id)
                s.add(row)
            row.item_id = a.item_id
            row.name = a.name
            row.official_name = a.official_name
            row.mask = a.mask
            row.type = a.type
            row.subtype = a.subtype
            row.current_balance = a.current_balance
            row.available_balance = a.available_balance
            row.iso_currency = a.iso_currency
            s.flush()
            return _finance_account_dict(row)

    def list_finance_accounts(self) -> list[dict]:
        from .config import settings
        with self._session() as s:
            rows = s.scalars(
                select(FinanceAccount)
                .where(FinanceAccount.owner == settings.owner)
                .order_by(FinanceAccount.id)
            ).all()
            return [_finance_account_dict(a) for a in rows]

    @_retry_integrity
    def upsert_finance_transaction(self, t: NormalizedTransaction) -> None:
        from .config import settings
        with self._session() as s, s.begin():
            row = s.scalars(
                select(FinanceTransaction)
                .where(FinanceTransaction.owner == settings.owner)
                .where(FinanceTransaction.source == "plaid")
                .where(FinanceTransaction.source_id == t.source_id)
            ).first()
            if row is None:
                row = FinanceTransaction(owner=settings.owner, source="plaid",
                                         source_id=t.source_id)
                s.add(row)
            row.account_id = t.account_id
            row.item_id = t.item_id
            row.name = t.name
            row.merchant_name = t.merchant_name
            row.amount = t.amount
            row.iso_currency = t.iso_currency
            row.date = t.date
            row.authorized_date = t.authorized_date
            row.pending = t.pending
            row.category_primary = t.category_primary
            row.category_detailed = t.category_detailed
            row.payment_channel = t.payment_channel

    def apply_transaction_delta(self, delta: TransactionsDelta) -> int:
        """Apply one /transactions/sync page: upsert added+modified by
        transaction_id, delete removed. Returns rows added+modified."""
        from .config import settings
        for t in delta.added:
            self.upsert_finance_transaction(t)
        for t in delta.modified:
            self.upsert_finance_transaction(t)
        if delta.removed:
            with self._session() as s, s.begin():
                for tid in delta.removed:
                    row = s.scalars(
                        select(FinanceTransaction)
                        .where(FinanceTransaction.owner == settings.owner)
                        .where(FinanceTransaction.source == "plaid")
                        .where(FinanceTransaction.source_id == tid)
                    ).first()
                    if row is not None:
                        s.delete(row)
        return len(delta.added) + len(delta.modified)

    def finance_transactions(self, days: int | None = None, account_id: str | None = None,
                             category: str | None = None) -> list[dict]:
        from .config import settings
        with self._session() as s:
            q = (
                select(FinanceTransaction)
                .where(FinanceTransaction.owner == settings.owner)
                .order_by(FinanceTransaction.date.desc(), FinanceTransaction.id.desc())
            )
            if days is not None:
                cutoff = (utcnow() - timedelta(days=days)).date()
                q = q.where(FinanceTransaction.date >= cutoff)
            if account_id is not None:
                q = q.where(FinanceTransaction.account_id == account_id)
            if category is not None:
                q = q.where(FinanceTransaction.category_primary == category)
            return [_finance_transaction_dict(t) for t in s.scalars(q).all()]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_store.py -q`
Expected: PASS (5 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/store.py backend/tests/test_finance_store.py
git commit -m "feat(finance): store — accounts + transactions sync-delta + filtered reads"
```

---

### Task 7: Store — securities + holdings

**Files:**
- Modify: `backend/app/store.py`
- Test: `backend/tests/test_finance_store.py` (extend)

**Interfaces:**
- Produces: `store.upsert_finance_security(sec: NormalizedSecurity) -> None`, `store.upsert_finance_holding(h: NormalizedHolding) -> None`, `store.finance_holdings() -> list[dict]` (each holding joined to its security: `{id, name, ticker, type, quantity, value, price, currency, is_crypto}`).

- [ ] **Step 1: Write the failing test** — append:

```python
def _sec(source_id="s1", name="Bitcoin", ticker="BTC", type="cryptocurrency"):
    return NormalizedSecurity(source="plaid", source_id=source_id, name=name,
                              ticker_symbol=ticker, type=type,
                              close_price=Decimal("60000"), iso_currency="USD")


def _hold(security_id="s1", account_id="acc9", qty="0.05", value="3000"):
    return NormalizedHolding(source="plaid", item_id="itm1", account_id=account_id,
                             security_id=security_id, quantity=Decimal(qty),
                             cost_basis=Decimal("2000"), institution_value=Decimal(value),
                             institution_price=Decimal("60000"), iso_currency="USD")


def test_holdings_join_security_and_flag_crypto():
    store.upsert_finance_security(_sec())
    store.upsert_finance_security(_sec("s2", "Apple", "AAPL", "equity"))
    store.upsert_finance_holding(_hold("s1", value="3000"))
    store.upsert_finance_holding(_hold("s2", account_id="acc9", value="22640"))
    holdings = store.finance_holdings()
    assert len(holdings) == 2
    btc = next(h for h in holdings if h["ticker"] == "BTC")
    assert btc["is_crypto"] is True
    assert btc["value"] == 3000.0
    assert btc["name"] == "Bitcoin"
    aapl = next(h for h in holdings if h["ticker"] == "AAPL")
    assert aapl["is_crypto"] is False


def test_holding_upsert_idempotent_by_account_and_security():
    store.upsert_finance_security(_sec())
    store.upsert_finance_holding(_hold(value="3000"))
    store.upsert_finance_holding(_hold(value="3200"))     # same account+security
    holdings = store.finance_holdings()
    assert len(holdings) == 1 and holdings[0]["value"] == 3200.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_store.py::test_holdings_join_security_and_flag_crypto -q`
Expected: FAIL — `AttributeError: 'Store' object has no attribute 'upsert_finance_security'`.

- [ ] **Step 3: Add the methods** to the `# ---- finance ----` section:

```python
    @_retry_integrity
    def upsert_finance_security(self, sec: NormalizedSecurity) -> None:
        from .config import settings
        with self._session() as s, s.begin():
            row = s.scalars(
                select(FinanceSecurity)
                .where(FinanceSecurity.owner == settings.owner)
                .where(FinanceSecurity.source == "plaid")
                .where(FinanceSecurity.source_id == sec.source_id)
            ).first()
            if row is None:
                row = FinanceSecurity(owner=settings.owner, source="plaid",
                                      source_id=sec.source_id)
                s.add(row)
            row.name = sec.name
            row.ticker_symbol = sec.ticker_symbol
            row.type = sec.type
            row.close_price = sec.close_price
            row.iso_currency = sec.iso_currency
            row.is_cash_equivalent = sec.is_cash_equivalent

    @_retry_integrity
    def upsert_finance_holding(self, h: NormalizedHolding) -> None:
        from .config import settings
        with self._session() as s, s.begin():
            row = s.scalars(
                select(FinanceHolding)
                .where(FinanceHolding.owner == settings.owner)
                .where(FinanceHolding.account_id == h.account_id)
                .where(FinanceHolding.security_id == h.security_id)
            ).first()
            if row is None:
                row = FinanceHolding(owner=settings.owner, account_id=h.account_id,
                                     security_id=h.security_id)
                s.add(row)
            row.item_id = h.item_id
            row.quantity = h.quantity
            row.cost_basis = h.cost_basis
            row.institution_value = h.institution_value
            row.institution_price = h.institution_price
            row.iso_currency = h.iso_currency

    def finance_holdings(self) -> list[dict]:
        """Holdings joined to their securities, ordered by value desc."""
        from .config import settings
        with self._session() as s:
            secs = {
                x.source_id: x for x in s.scalars(
                    select(FinanceSecurity).where(FinanceSecurity.owner == settings.owner)
                ).all()
            }
            rows = s.scalars(
                select(FinanceHolding)
                .where(FinanceHolding.owner == settings.owner)
                .order_by(FinanceHolding.institution_value.desc())
            ).all()
            out = []
            for h in rows:
                sec = secs.get(h.security_id)
                out.append({
                    "id": h.id,
                    "account_id": h.account_id,
                    "security_id": h.security_id,
                    "name": sec.name if sec else h.security_id,
                    "ticker": (sec.ticker_symbol if sec else None),
                    "type": (sec.type if sec else ""),
                    "is_crypto": bool(sec and sec.type == "cryptocurrency"),
                    "quantity": _dec_to_float(h.quantity),
                    "value": _dec_to_float(h.institution_value),
                    "price": _dec_to_float(h.institution_price),
                    "currency": h.iso_currency,
                })
            return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_store.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/store.py backend/tests/test_finance_store.py
git commit -m "feat(finance): store — securities + holdings (crypto-flagged, join)"
```

---

### Task 8: Store — budgets, category mapping, reallocation

**Files:**
- Modify: `backend/app/store.py` (module-level constants + finance section)
- Test: `backend/tests/test_finance_store.py` (extend)

**Interfaces:**
- Produces module constants: `BUDGET_CATEGORIES: list[str]`, `budget_bucket(primary: str, detailed: str) -> str`.
- Produces: `store.finance_budgets(month: str) -> list[dict]` (each `{category, limit_amount, spent, color}`, all six categories always present), `store.upsert_budgets(month: str, budgets: list[dict]) -> list[dict]`, `store.reallocate_budget(month: str, from_category: str, to_category: str, amount: float) -> list[dict]`.

- [ ] **Step 1: Write the failing test** — append:

```python
def test_budget_bucket_mapping():
    from app.store import budget_bucket
    assert budget_bucket("FOOD_AND_DRINK", "FOOD_AND_DRINK_GROCERIES") == "Groceries"
    assert budget_bucket("FOOD_AND_DRINK", "FOOD_AND_DRINK_RESTAURANT") == "Dining out"
    assert budget_bucket("RENT_AND_UTILITIES", "") == "Rent & bills"
    assert budget_bucket("TRANSPORTATION", "") == "Transport"
    assert budget_bucket("TRANSFER_OUT", "TRANSFER_OUT_SAVINGS") == "Savings"
    assert budget_bucket("ENTERTAINMENT", "") == "Other"


def test_budgets_have_all_categories_with_derived_spend():
    store.upsert_budgets("2026-06", [{"category": "Groceries", "limit_amount": 400}])
    # A June grocery outflow (+ amount) and an inflow (should not count as spend).
    store.apply_transaction_delta(TransactionsDelta(
        added=[_txn("t1", amount="64.20", d=date(2026, 6, 8),
                    primary="FOOD_AND_DRINK", detailed="FOOD_AND_DRINK_GROCERIES"),
               _txn("t2", amount="-500.00", d=date(2026, 6, 5), primary="INCOME")],
        modified=[], removed=[], next_cursor="C1", has_more=False))
    budgets = store.finance_budgets("2026-06")
    assert len(budgets) == len(store.BUDGET_CATEGORIES) if hasattr(store, "BUDGET_CATEGORIES") else True
    groceries = next(b for b in budgets if b["category"] == "Groceries")
    assert groceries["limit_amount"] == 400.0
    assert groceries["spent"] == 64.20
    assert groceries["color"]  # non-empty tint


def test_reallocate_budget_moves_limit():
    store.upsert_budgets("2026-06", [
        {"category": "Dining out", "limit_amount": 250},
        {"category": "Savings", "limit_amount": 600}])
    store.reallocate_budget("2026-06", "Dining out", "Savings", 120)
    budgets = {b["category"]: b for b in store.finance_budgets("2026-06")}
    assert budgets["Dining out"]["limit_amount"] == 130.0
    assert budgets["Savings"]["limit_amount"] == 720.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_store.py::test_budget_bucket_mapping -q`
Expected: FAIL — `ImportError: cannot import name 'budget_bucket' from 'app.store'`.

- [ ] **Step 3: Add module-level constants + mapping** (near the top of `store.py`, after the imports):

```python
# ---- finance budget categories (fixed set, slice 1) ----
BUDGET_CATEGORIES = ["Groceries", "Rent & bills", "Dining out", "Transport", "Savings", "Other"]
_BUDGET_COLORS = {
    "Groceries": "clay", "Rent & bills": "honey", "Dining out": "plum",
    "Transport": "sky", "Savings": "green", "Other": "slate",
}


def budget_bucket(primary: str, detailed: str = "") -> str:
    """Map a Plaid personal_finance_category to one of the six budget buckets.
    [confirm-against-live] — real PFC values verified at the live gate."""
    primary = (primary or "").upper()
    detailed = (detailed or "").upper()
    if "GROCERIES" in detailed:
        return "Groceries"
    if primary == "FOOD_AND_DRINK":
        return "Dining out"
    if primary in ("RENT_AND_UTILITIES", "LOAN_PAYMENTS", "HOME_IMPROVEMENT"):
        return "Rent & bills"
    if primary in ("TRANSPORTATION", "TRAVEL"):
        return "Transport"
    if primary == "TRANSFER_OUT" and ("SAVINGS" in detailed or "INVESTMENT" in detailed):
        return "Savings"
    return "Other"
```

- [ ] **Step 4: Add the budget store methods** to the `# ---- finance ----` section:

```python
    def finance_budgets(self, month: str) -> list[dict]:
        """All six budget categories for `month` (YYYY-MM), each with its local
        limit and derived spend (Σ outflow amounts mapped to that bucket)."""
        from .config import settings
        with self._session() as s:
            limits = {
                b.category: b.limit_amount for b in s.scalars(
                    select(FinanceBudget)
                    .where(FinanceBudget.owner == settings.owner)
                    .where(FinanceBudget.month == month)
                ).all()
            }
            txns = s.scalars(
                select(FinanceTransaction)
                .where(FinanceTransaction.owner == settings.owner)
            ).all()
        spent = {c: Decimal("0") for c in BUDGET_CATEGORIES}
        for t in txns:
            if t.date is None or t.date.strftime("%Y-%m") != month:
                continue
            if t.amount is None or t.amount <= 0:        # only outflows are "spend"
                continue
            spent[budget_bucket(t.category_primary, t.category_detailed)] += t.amount
        return [
            {
                "category": c,
                "limit_amount": _dec_to_float(limits.get(c, Decimal("0"))),
                "spent": float(spent[c]),
                "color": _BUDGET_COLORS[c],
            }
            for c in BUDGET_CATEGORIES
        ]

    @_retry_integrity
    def _upsert_one_budget(self, month: str, category: str, limit_amount) -> None:
        from .config import settings
        with self._session() as s, s.begin():
            row = s.scalars(
                select(FinanceBudget)
                .where(FinanceBudget.owner == settings.owner)
                .where(FinanceBudget.category == category)
                .where(FinanceBudget.month == month)
            ).first()
            if row is None:
                row = FinanceBudget(owner=settings.owner, category=category, month=month)
                s.add(row)
            row.limit_amount = Decimal(str(limit_amount))

    def upsert_budgets(self, month: str, budgets: list[dict]) -> list[dict]:
        for b in budgets:
            category = b["category"]
            if category not in BUDGET_CATEGORIES:        # ignore unknown buckets
                continue
            self._upsert_one_budget(month, category, b["limit_amount"])
        return self.finance_budgets(month)

    def reallocate_budget(self, month: str, from_category: str, to_category: str,
                          amount: float) -> list[dict]:
        """Logical move: subtract `amount` from from_category's limit, add it to
        to_category's. Local only — never touches a bank."""
        current = {b["category"]: b["limit_amount"] for b in self.finance_budgets(month)}
        amt = Decimal(str(amount))
        self._upsert_one_budget(month, from_category,
                                Decimal(str(current.get(from_category, 0))) - amt)
        self._upsert_one_budget(month, to_category,
                                Decimal(str(current.get(to_category, 0))) + amt)
        return self.finance_budgets(month)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_store.py -q`
Expected: PASS (10 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/store.py backend/tests/test_finance_store.py
git commit -m "feat(finance): store — budgets, PFC->bucket mapping, reallocation"
```

---

### Task 9: Store — summary + net-worth derivations

**Files:**
- Modify: `backend/app/store.py`
- Test: `backend/tests/test_finance_store.py` (extend)

**Interfaces:**
- Produces: `store.finance_summary(month: str | None = None) -> dict` (`{month, balance, income_month, spent_month, income_delta, spent_delta}`) and `store.finance_networth() -> dict` (`{buckets: [{name, value, color}], total}`). Net-worth buckets: **Cash** (depository balances), **Crypto** (Σ crypto holding value), **Investments** (non-crypto investment holdings/accounts, non-retirement), **Retirement** (investment `ira`/`401k`/`403b`/`roth` subtypes), **Credit/Loans** (credit + loan balances, **negative**).

- [ ] **Step 1: Write the failing test** — append:

```python
def test_finance_summary_income_spent_and_deltas():
    store.upsert_finance_account(_acct("acc1", current="4820.50", available="4820.50"))
    store.apply_transaction_delta(TransactionsDelta(added=[
        _txn("i1", amount="-3200.00", d=date(2026, 6, 1), primary="INCOME"),
        _txn("s1", amount="1450.00", d=date(2026, 6, 3), primary="RENT_AND_UTILITIES"),
        _txn("s2", amount="64.20", d=date(2026, 6, 8), primary="FOOD_AND_DRINK"),
        _txn("x1", amount="500.00", d=date(2026, 5, 5), primary="FOOD_AND_DRINK"),  # May
    ], modified=[], removed=[], next_cursor="C", has_more=False))
    summ = store.finance_summary("2026-06")
    assert summ["balance"] == 4820.50
    assert summ["income_month"] == 3200.0
    assert round(summ["spent_month"], 2) == 1514.20
    # spent delta vs May (500.00 spent in May): 1514.20 - 500 = +1014.20
    assert round(summ["spent_delta"], 2) == 1014.20


def test_finance_networth_buckets():
    store.upsert_finance_account(_acct("cash", type="depository", subtype="checking",
                                       current="18050.00", available="18050.00"))
    store.upsert_finance_account(_acct("ira", type="investment", subtype="ira",
                                       current="21400.00", available="0"))
    store.upsert_finance_account(_acct("cc", type="credit", subtype="credit card",
                                       current="1200.00", available="0"))
    store.upsert_finance_security(_sec("s1", "Bitcoin", "BTC", "cryptocurrency"))
    store.upsert_finance_security(_sec("s2", "VTI", "VTI", "etf"))
    store.upsert_finance_holding(_hold("s1", account_id="brk", value="3400"))    # crypto
    store.upsert_finance_holding(_hold("s2", account_id="brk", value="48200"))   # investments
    nw = store.finance_networth()
    buckets = {b["name"]: b["value"] for b in nw["buckets"]}
    assert buckets["Cash"] == 18050.0
    assert buckets["Crypto"] == 3400.0
    assert buckets["Investments"] == 48200.0
    assert buckets["Retirement"] == 21400.0
    assert buckets["Credit/Loans"] == -1200.0
    assert round(nw["total"], 2) == round(18050 + 3400 + 48200 + 21400 - 1200, 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_store.py::test_finance_networth_buckets -q`
Expected: FAIL — `AttributeError: 'Store' object has no attribute 'finance_networth'`.

- [ ] **Step 3: Add the derivations** to the `# ---- finance ----` section:

```python
    _RETIREMENT_SUBTYPES = frozenset({
        "ira", "roth", "roth 401k", "401k", "401a", "403b", "457b", "pension",
        "retirement", "sep ira", "simple ira", "sarsep", "tsp",
    })

    def _month_sums(self, s: Session, month: str) -> tuple[Decimal, Decimal]:
        """(income, spent) for `month` (YYYY-MM), excluding internal transfers."""
        from .config import settings
        income = Decimal("0")
        spent = Decimal("0")
        for t in s.scalars(
            select(FinanceTransaction).where(FinanceTransaction.owner == settings.owner)
        ):
            if t.date is None or t.date.strftime("%Y-%m") != month or t.amount is None:
                continue
            primary = (t.category_primary or "").upper()
            if t.amount < 0:
                if primary != "TRANSFER_IN":
                    income += -t.amount
            elif t.amount > 0:
                if primary != "TRANSFER_OUT":
                    spent += t.amount
        return income, spent

    def finance_summary(self, month: str | None = None) -> dict:
        from .config import settings
        month = month or utcnow().strftime("%Y-%m")
        y, m = int(month[:4]), int(month[5:7])
        prev = f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"
        with self._session() as s:
            balance = Decimal("0")
            for a in s.scalars(
                select(FinanceAccount)
                .where(FinanceAccount.owner == settings.owner)
                .where(FinanceAccount.type == "depository")
            ):
                bal = a.available_balance if a.available_balance is not None else a.current_balance
                if bal is not None:
                    balance += bal
            income, spent = self._month_sums(s, month)
            prev_income, prev_spent = self._month_sums(s, prev)
        return {
            "month": month,
            "balance": float(balance),
            "income_month": float(income),
            "spent_month": float(spent),
            "income_delta": float(income - prev_income),
            "spent_delta": float(spent - prev_spent),
        }

    def finance_networth(self) -> dict:
        from .config import settings
        with self._session() as s:
            accounts = s.scalars(
                select(FinanceAccount).where(FinanceAccount.owner == settings.owner)
            ).all()
            crypto_ids = {
                x.source_id for x in s.scalars(
                    select(FinanceSecurity)
                    .where(FinanceSecurity.owner == settings.owner)
                    .where(FinanceSecurity.type == "cryptocurrency")
                ).all()
            }
            holdings = s.scalars(
                select(FinanceHolding).where(FinanceHolding.owner == settings.owner)
            ).all()
        cash = Decimal("0")
        credit_loans = Decimal("0")
        for a in accounts:
            bal = a.current_balance if a.current_balance is not None else Decimal("0")
            if a.type == "depository":
                cash += (a.available_balance if a.available_balance is not None else bal)
            elif a.type in ("credit", "loan"):
                credit_loans += bal
        crypto = Decimal("0")
        investments = Decimal("0")
        retirement = Decimal("0")
        acct_subtype = {a.source_id: (a.subtype or "").lower() for a in accounts}
        for h in holdings:
            value = h.institution_value or Decimal("0")
            if h.security_id in crypto_ids:
                crypto += value
            elif acct_subtype.get(h.account_id, "") in self._RETIREMENT_SUBTYPES:
                retirement += value
            else:
                investments += value
        # Un-itemized investment accounts (no holdings — e.g. some IRAs Plaid
        # can't itemize) contribute their account balance, classified by subtype.
        # Accounts WITH holdings are already counted via the loop above, so this
        # never double-counts.
        accounts_with_holdings = {h.account_id for h in holdings}
        for a in accounts:
            if a.type == "investment" and a.source_id not in accounts_with_holdings:
                value = a.current_balance or Decimal("0")
                if (a.subtype or "").lower() in self._RETIREMENT_SUBTYPES:
                    retirement += value
                else:
                    investments += value
        buckets = [
            {"name": "Cash", "value": float(cash), "color": "honey"},
            {"name": "Investments", "value": float(investments), "color": "green"},
            {"name": "Retirement", "value": float(retirement), "color": "sky"},
            {"name": "Crypto", "value": float(crypto), "color": "plum"},
            {"name": "Credit/Loans", "value": float(-credit_loans), "color": "clay"},
        ]
        total = cash + investments + retirement + crypto - credit_loans
        return {"buckets": buckets, "total": float(total)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_store.py -q`
Expected: PASS (12 passed).

- [ ] **Step 5: Run full suite (baseline hold)**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest -q`
Expected: **~544 passed, 1 skipped** (all store + model + config tests green).

- [ ] **Step 6: Commit**

```bash
git add backend/app/store.py backend/tests/test_finance_store.py
git commit -m "feat(finance): store — summary + net-worth bucket derivations"
```

---

### Task 10: PlaidProvider — `_call`, link-token, exchange, item

**Files:**
- Create: `backend/app/providers/plaid.py`
- Modify: `backend/tests/fakes.py` (add `FakePlaidHTTP` transport stub)
- Test: `backend/tests/test_plaid_provider.py` (create)

**Interfaces:**
- Consumes: `NormalizedItem`, `AuthError` (from `providers.base`); `settings.plaid_*`.
- Produces: `PlaidProvider` class with `name="plaid"`, `configure(fake_http="unset")`, `create_link_token(kind) -> dict`, `exchange_public_token(public_token) -> tuple[str, str]`, `get_item(access_token) -> NormalizedItem`. Also `PlaidError(RuntimeError)`, `PlaidAuthError(AuthError)`, module helper `_dec(x) -> Decimal | None`.

- [ ] **Step 1: Add `FakePlaidHTTP` to `tests/fakes.py`** (reuses the existing `_FakeResponse` + `_Seq`/`seq`):

```python
# ---- plaid provider seam (M7) ---------------------------------------------
class FakePlaidHTTP:
    """Scriptable transport for PlaidProvider.configure(fake_http=...).

    Routes .post(url, json=...) by URL-path substring. `responses` maps a path
    fragment (e.g. '/accounts/get') to a JSON dict (or seq(...) for repeated
    calls, e.g. paginated /transactions/sync). `status` maps a fragment to an
    error status_code; when >=400 the matching `responses` body (a Plaid
    {error_code, error_message} dict) is returned so the provider maps it to
    PlaidAuthError/PlaidError. Records every post as (url, json-body)."""

    def __init__(self, responses: dict | None = None, status: dict | None = None):
        self.responses = dict(responses or {})
        self.status = dict(status or {})
        self.posts: list[tuple[str, dict]] = []

    def _match(self, url: str, table: dict):
        for frag, val in table.items():
            if frag in url:
                return val
        return None

    def post(self, url, json=None, headers=None):
        self.posts.append((url, dict(json or {})))
        code = self._match(url, self.status) or 200
        val = self._match(url, self.responses)
        if code >= 400:
            body = val if isinstance(val, dict) else {
                "error_code": "INVALID_ACCESS_TOKEN", "error_message": "bad token"}
            return _FakeResponse(body, code)
        if isinstance(val, _Seq):
            return _FakeResponse(val.next())
        return _FakeResponse(val if val is not None else {})

    def get(self, url, headers=None, params=None):   # unused by PlaidProvider
        return _FakeResponse({})
```

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_plaid_provider.py
"""M7 — the real PlaidProvider driven by FakePlaidHTTP (no network). Covers
link-token per kind, public-token exchange, item/institution resolution,
accounts, /transactions/sync paging, holdings, and error→PlaidAuthError."""
from decimal import Decimal

import pytest

from app.config import settings
from app.providers.base import NormalizedItem
from app.providers.plaid import PlaidAuthError, PlaidError, PlaidProvider
from tests.fakes import FakePlaidHTTP, seq


def _provider(http):
    p = PlaidProvider()
    p.configure(fake_http=http)
    return p


def test_create_link_token_bank_requests_transactions(monkeypatch):
    monkeypatch.setattr(settings, "plaid_client_id", "cid")
    monkeypatch.setattr(settings, "plaid_secret", "sek")
    http = FakePlaidHTTP(responses={"/link/token/create": {
        "link_token": "link-1", "hosted_link_url": "https://plaid/hl", "expiration": "2026-07-05"}})
    p = _provider(http)
    out = p.create_link_token("bank")
    assert out["link_token"] == "link-1"
    assert out["hosted_link_url"] == "https://plaid/hl"
    url, body = http.posts[0]
    assert url.endswith("/link/token/create")
    assert body["products"] == ["transactions"]
    assert body["additional_consented_products"] == ["investments"]
    assert "hosted_link" in body
    assert body["client_id"] == "cid" and body["secret"] == "sek"


def test_create_link_token_investments_requests_investments():
    http = FakePlaidHTTP(responses={"/link/token/create": {"link_token": "l", "hosted_link_url": "u"}})
    p = _provider(http)
    p.create_link_token("investments")
    _, body = http.posts[0]
    assert body["products"] == ["investments"]
    assert "additional_consented_products" not in body


def test_exchange_public_token():
    http = FakePlaidHTTP(responses={"/item/public_token/exchange": {
        "access_token": "acc-tok", "item_id": "itm1"}})
    p = _provider(http)
    assert p.exchange_public_token("pub-1") == ("acc-tok", "itm1")


def test_get_item_resolves_institution_name_and_products():
    http = FakePlaidHTTP(responses={
        "/item/get": {"item": {"item_id": "itm1", "institution_id": "ins_1",
                               "billed_products": ["transactions"],
                               "available_products": ["investments"]}},
        "/institutions/get_by_id": {"institution": {"name": "Chase"}},
    })
    p = _provider(http)
    item = p.get_item("acc-tok")
    assert isinstance(item, NormalizedItem)
    assert item.institution_name == "Chase"
    assert set(item.products) == {"transactions", "investments"}


def test_call_maps_auth_error_code():
    http = FakePlaidHTTP(
        responses={"/accounts/get": {"error_code": "ITEM_LOGIN_REQUIRED", "error_message": "reauth"}},
        status={"/accounts/get": 400})
    p = _provider(http)
    with pytest.raises(PlaidAuthError):
        p.get_accounts("acc-tok")


def test_call_maps_non_auth_error_to_plaiderror():
    http = FakePlaidHTTP(
        responses={"/accounts/get": {"error_code": "RATE_LIMIT_EXCEEDED", "error_message": "slow"}},
        status={"/accounts/get": 429})
    p = _provider(http)
    with pytest.raises(PlaidError):
        p.get_accounts("acc-tok")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_plaid_provider.py::test_exchange_public_token -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.providers.plaid'`.

- [ ] **Step 4: Write `providers/plaid.py` (this task's methods; the rest land in Tasks 11–12)**

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_plaid_provider.py -q`
Expected: the four `create/exchange/get_item` + both error tests that call `get_accounts` — **`get_accounts` doesn't exist yet**, so the two `test_call_maps_*` FAIL with `AttributeError`. That's expected; they pass in Task 11. Confirm `test_create_link_token_bank_requests_transactions`, `..._investments_...`, `test_exchange_public_token`, `test_get_item_resolves_institution_name_and_products` **PASS** (4 passed, 2 errors).

- [ ] **Step 6: Commit**

```bash
git add backend/app/providers/plaid.py backend/tests/fakes.py backend/tests/test_plaid_provider.py
git commit -m "feat(finance): PlaidProvider — _call, link-token, exchange, item"
```

---

### Task 11: PlaidProvider — accounts + `/transactions/sync`

**Files:**
- Modify: `backend/app/providers/plaid.py`
- Test: `backend/tests/test_plaid_provider.py` (extend)

**Interfaces:**
- Produces: `get_accounts(access_token) -> list[NormalizedAccount]`, `sync_transactions(access_token, cursor) -> TransactionsDelta` (one page; caller loops on `has_more`).

- [ ] **Step 1: Write the failing test** — append:

```python
def test_get_accounts_parses_balances():
    http = FakePlaidHTTP(responses={"/accounts/get": {
        "item": {"item_id": "itm1"},
        "accounts": [{"account_id": "a1", "name": "Checking", "official_name": "Plaid Checking",
                      "mask": "1234", "type": "depository", "subtype": "checking",
                      "balances": {"current": 100.5, "available": 90.0, "iso_currency_code": "USD"}}]}})
    p = _provider(http)
    accs = p.get_accounts("tok")
    assert len(accs) == 1
    assert accs[0].current_balance == Decimal("100.5")
    assert accs[0].type == "depository" and accs[0].item_id == "itm1"


def test_sync_transactions_one_page():
    http = FakePlaidHTTP(responses={"/transactions/sync": {
        "added": [{"transaction_id": "t1", "account_id": "a1", "name": "WF",
                   "merchant_name": "Whole Foods", "amount": 64.2, "iso_currency_code": "USD",
                   "date": "2026-06-08", "authorized_date": "2026-06-07", "pending": False,
                   "personal_finance_category": {"primary": "FOOD_AND_DRINK",
                                                 "detailed": "FOOD_AND_DRINK_GROCERIES"},
                   "payment_channel": "in store"}],
        "modified": [], "removed": [{"transaction_id": "t9"}],
        "next_cursor": "CUR2", "has_more": True}})
    p = _provider(http)
    delta = p.sync_transactions("tok", None)
    assert delta.added[0].amount == Decimal("64.2")
    assert delta.added[0].category_primary == "FOOD_AND_DRINK"
    assert delta.removed == ["t9"]
    assert delta.next_cursor == "CUR2" and delta.has_more is True
    # cursor omitted on the first call, present on a subsequent one.
    _, body = http.posts[0]
    assert "cursor" not in body
    p.sync_transactions("tok", "CUR2")
    _, body2 = http.posts[1]
    assert body2["cursor"] == "CUR2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_plaid_provider.py::test_sync_transactions_one_page -q`
Expected: FAIL — `AttributeError: 'PlaidProvider' object has no attribute 'sync_transactions'`.

- [ ] **Step 3: Add the methods** to `PlaidProvider`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_plaid_provider.py -q`
Expected: PASS (8 passed — the two error tests from Task 10 now pass too).

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers/plaid.py backend/tests/test_plaid_provider.py
git commit -m "feat(finance): PlaidProvider — accounts + /transactions/sync"
```

---

### Task 12: PlaidProvider — holdings, Hosted-Link poll, remove

**Files:**
- Modify: `backend/app/providers/plaid.py`
- Test: `backend/tests/test_plaid_provider.py` (extend)

**Interfaces:**
- Produces: `get_holdings(access_token) -> tuple[list[NormalizedAccount], list[NormalizedSecurity], list[NormalizedHolding]]`, `get_link_public_token(link_token) -> str | None`, `remove_item(access_token) -> None`.

- [ ] **Step 1: Write the failing test** — append:

```python
def test_get_holdings_parses_accounts_securities_holdings():
    http = FakePlaidHTTP(responses={"/investments/holdings/get": {
        "accounts": [{"account_id": "brk", "name": "Coinbase", "type": "investment",
                      "subtype": "crypto", "balances": {"current": 3400.0, "iso_currency_code": "USD"}}],
        "securities": [{"security_id": "s1", "name": "Bitcoin", "ticker_symbol": "BTC",
                        "type": "cryptocurrency", "close_price": 60000, "iso_currency_code": "USD",
                        "is_cash_equivalent": False}],
        "holdings": [{"account_id": "brk", "security_id": "s1", "quantity": 0.05,
                      "cost_basis": 2000, "institution_value": 3000, "institution_price": 60000,
                      "iso_currency_code": "USD"}]}})
    p = _provider(http)
    accts, secs, holds = p.get_holdings("tok")
    assert accts[0].source_id == "brk" and accts[0].type == "investment"
    assert secs[0].type == "cryptocurrency" and secs[0].ticker_symbol == "BTC"
    assert holds[0].quantity == Decimal("0.05")
    assert holds[0].institution_value == Decimal("3000") and holds[0].account_id == "brk"


def test_get_link_public_token_returns_none_until_finished():
    # First poll: no sessions yet. Second poll: a finished session with a public_token.
    http = FakePlaidHTTP(responses={"/link/token/get": seq(
        {"link_token": "l", "link_sessions": []},
        {"link_token": "l", "link_sessions": [
            {"results": {"item_add_results": [{"public_token": "pub-xyz"}]}}]})})
    p = _provider(http)
    assert p.get_link_public_token("l") is None
    assert p.get_link_public_token("l") == "pub-xyz"


def test_remove_item_posts_access_token():
    http = FakePlaidHTTP(responses={"/item/remove": {}})
    p = _provider(http)
    p.remove_item("tok")
    url, body = http.posts[0]
    assert url.endswith("/item/remove") and body["access_token"] == "tok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_plaid_provider.py::test_get_holdings_parses_accounts_securities_holdings -q`
Expected: FAIL — `AttributeError: 'PlaidProvider' object has no attribute 'get_holdings'`.

- [ ] **Step 3: Add the methods** to `PlaidProvider`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_plaid_provider.py -q`
Expected: PASS (11 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers/plaid.py backend/tests/test_plaid_provider.py
git commit -m "feat(finance): PlaidProvider — holdings, Hosted-Link poll, item/remove"
```

---

### Task 13: Register PlaidProvider + `FakePlaidProvider`

**Files:**
- Modify: `backend/app/providers/__init__.py` (`_build_real`)
- Modify: `backend/tests/fakes.py` (add `FakePlaidProvider`)
- Test: `backend/tests/test_plaid_provider.py` (extend — registry assertion)

**Interfaces:**
- Produces: `providers.get("plaid")` returns a `PlaidProvider` in the real registry. `FakePlaidProvider(name="plaid")` — a protocol-level fake with scriptable `items`/`accounts`/`transactions`/`holdings` and a `raise_auth` flag, plus a `remove_item` recorder.

- [ ] **Step 1: Write the failing test** — append to `test_plaid_provider.py`:

```python
def test_plaid_registered_in_real_registry():
    from app import providers
    providers.configure("unset")            # real registry
    try:
        p = providers.get("plaid")
        assert p is not None and p.name == "plaid"
    finally:
        providers.configure([])             # restore test isolation
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_plaid_provider.py::test_plaid_registered_in_real_registry -q`
Expected: FAIL — `assert p is not None` fails (Plaid not yet in `_build_real`).

- [ ] **Step 3: Register in `providers/__init__.py`** — add to `_build_real`, after the Moodle block:

```python
        try:
            from .plaid import PlaidProvider
            built.append(PlaidProvider())
        except ImportError:
            pass  # PlaidProvider not present yet (mid-plan) — skip it.
```

- [ ] **Step 4: Add `FakePlaidProvider` to `tests/fakes.py`**

```python
class FakePlaidProvider:
    """Scriptable protocol-level PlaidProvider stand-in (name='plaid') — no
    network. Installed via providers.configure([FakePlaidProvider(...)]). The
    finance router/sync call: create_link_token, get_link_public_token,
    exchange_public_token, get_item, get_accounts, sync_transactions,
    get_holdings, remove_item. raise_auth drives the needs_reauth path."""

    name = "plaid"

    def __init__(self, *, item=None, accounts=None, delta=None, holdings=None,
                 public_token="pub-1", access_token="acc-tok", item_id="itm1",
                 raise_auth=False):
        from app.providers.base import NormalizedItem, TransactionsDelta
        self.item = item or NormalizedItem(item_id=item_id, institution_id="ins_1",
                                           institution_name="Test Bank",
                                           products=["transactions"])
        self.accounts = accounts or []
        self.delta = delta or TransactionsDelta(next_cursor="C1", has_more=False)
        self.holdings = holdings or ([], [], [])
        self.public_token = public_token
        self.access_token = access_token
        self.item_id = item_id
        self.raise_auth = raise_auth
        self.link_kinds: list[str] = []
        self.removed: list[str] = []
        self.synced_cursors: list = []

    def create_link_token(self, kind: str) -> dict:
        self.link_kinds.append(kind)
        return {"link_token": "link-1", "hosted_link_url": "https://plaid/hl"}

    def get_link_public_token(self, link_token: str):
        return self.public_token

    def exchange_public_token(self, public_token: str):
        return self.access_token, self.item_id

    def get_item(self, access_token: str):
        return self.item

    def get_accounts(self, access_token: str):
        from app.providers.plaid import PlaidAuthError
        if self.raise_auth:
            raise PlaidAuthError("ITEM_LOGIN_REQUIRED")
        return list(self.accounts)

    def sync_transactions(self, access_token: str, cursor):
        self.synced_cursors.append(cursor)
        return self.delta

    def get_holdings(self, access_token: str):
        return self.holdings

    def remove_item(self, access_token: str) -> None:
        self.removed.append(access_token)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_plaid_provider.py -q`
Expected: PASS (12 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/providers/__init__.py backend/tests/fakes.py backend/tests/test_plaid_provider.py
git commit -m "feat(finance): register PlaidProvider + FakePlaidProvider"
```

---

### Task 14: `finance_sync` engine + conftest wiring

**Files:**
- Create: `backend/app/finance_sync.py`
- Modify: `backend/tests/conftest.py` (`no_external_services`)
- Test: `backend/tests/test_finance_sync.py` (create)

**Interfaces:**
- Consumes: `providers.get("plaid")`, `store.list_finance_items`, `store.get_finance_item_token`, `store.get_finance_item_cursor`, `store.upsert_finance_account/security/holding`, `store.apply_transaction_delta`, `store.set_finance_item_cursor/status/synced`, `AuthError`.
- Produces: `finance_sync.configure(override="unset")`, `finance_sync.tick(now=None) -> int`, `finance_sync.trigger()` (async), `finance_sync.run_loop()` (async).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_finance_sync.py
"""M7 finance_sync — per-Item pull; transactions branch, investments branch,
paging, and AuthError -> needs_reauth. No network (FakePlaidProvider)."""
from decimal import Decimal

from app import finance_sync, providers
from app.providers.base import (
    NormalizedAccount, NormalizedHolding, NormalizedItem,
    NormalizedSecurity, NormalizedTransaction, TransactionsDelta,
)
from app.store import store


def _seed_item(item_id="itm1", products=("transactions",)):
    store.upsert_finance_item(
        NormalizedItem(item_id=item_id, institution_id="ins_1",
                       institution_name="Chase", products=list(products)),
        access_token="tok")


def _acct(source_id="a1"):
    return NormalizedAccount(source="plaid", source_id=source_id, item_id="itm1",
                             name="Checking", official_name=None, mask="1", type="depository",
                             subtype="checking", current_balance=Decimal("100"),
                             available_balance=Decimal("100"), iso_currency="USD")


def _txn(source_id="t1"):
    from datetime import date
    return NormalizedTransaction(source="plaid", source_id=source_id, account_id="a1",
                                 item_id="itm1", name="WF", merchant_name="WF",
                                 amount=Decimal("10"), iso_currency="USD", date=date(2026, 6, 8),
                                 authorized_date=None, pending=False,
                                 category_primary="FOOD_AND_DRINK", category_detailed="",
                                 payment_channel="in store")


def test_tick_syncs_transactions_and_advances_cursor():
    from tests.fakes import FakePlaidProvider
    _seed_item(products=("transactions",))
    delta = TransactionsDelta(added=[_txn("t1")], next_cursor="C2", has_more=False)
    providers.configure([FakePlaidProvider(accounts=[_acct()], delta=delta)])
    n = finance_sync.tick()
    assert n >= 2                                   # 1 account + 1 transaction
    assert len(store.finance_transactions()) == 1
    assert store.get_finance_item_cursor("itm1") == "C2"
    assert store.get_finance_item("itm1")["last_sync_at"] is not None


def test_tick_syncs_investments_branch():
    from tests.fakes import FakePlaidProvider
    _seed_item(products=("investments",))
    sec = NormalizedSecurity(source="plaid", source_id="s1", name="BTC", ticker_symbol="BTC",
                             type="cryptocurrency", close_price=Decimal("60000"), iso_currency="USD")
    hold = NormalizedHolding(source="plaid", item_id="itm1", account_id="brk", security_id="s1",
                             quantity=Decimal("0.05"), institution_value=Decimal("3000"),
                             iso_currency="USD")
    prov = FakePlaidProvider(holdings=([_acct("brk")], [sec], [hold]))
    providers.configure([prov])
    finance_sync.tick()
    assert len(store.finance_holdings()) == 1


def test_tick_flips_needs_reauth_on_auth_error():
    from tests.fakes import FakePlaidProvider
    _seed_item()
    providers.configure([FakePlaidProvider(raise_auth=True)])
    finance_sync.tick()
    assert store.get_finance_item("itm1")["status"] == "needs_reauth"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_sync.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.finance_sync'`.

- [ ] **Step 3: Write `finance_sync.py`**

```python
"""Finance sync engine (M7) — a background tick + on-demand trigger.

Clone of moodle_sync.py, but multi-Item: instead of looping providers, it loops
store.list_finance_items() and, per Item, injects that Item's access_token and
branches on its `products`: 'transactions' -> paged /transactions/sync (advance
the cursor); 'investments' -> holdings; accounts refresh always. A PlaidAuthError
(subclass of AuthError) on one Item flips only that Item to needs_reauth. Reads
never depend on a live Plaid call; only connect and this sync reach Plaid. The
tick NEVER crashes. Test seam: configure(fake) installs an object with .tick().
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from . import providers
from .config import settings
from .providers.base import AuthError
from .store import store

logger = logging.getLogger("scuffed_os.finance_sync")

_override: object | None | str = "unset"


def configure(override: object | None | str = "unset") -> None:
    """Test seam for mocking tick(); install a fake with .tick(). None/"unset"
    run the real tick. run_loop is gated separately by settings.finance_sync_enabled."""
    global _override
    _override = override


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sync_item(provider, item: dict, now: datetime) -> int:
    """One Item's pass. Raises AuthError so the caller flips needs_reauth."""
    if item.get("status") != "active":
        return 0
    item_id = item["item_id"]
    access_token = store.get_finance_item_token(item_id)
    if not access_token:
        return 0
    products = item.get("products") or []
    count = 0
    for acc in provider.get_accounts(access_token):
        store.upsert_finance_account(acc)
        count += 1
    if "transactions" in products:
        cursor = store.get_finance_item_cursor(item_id)
        while True:
            delta = provider.sync_transactions(access_token, cursor)
            count += store.apply_transaction_delta(delta)
            cursor = delta.next_cursor
            store.set_finance_item_cursor(item_id, cursor)
            if not delta.has_more:
                break
    if "investments" in products:
        accts, secs, holds = provider.get_holdings(access_token)
        for a in accts:
            store.upsert_finance_account(a)
            count += 1
        for sec in secs:
            store.upsert_finance_security(sec)
            count += 1
        for h in holds:
            store.upsert_finance_holding(h)
            count += 1
    store.set_finance_item_synced(item_id, now)
    return count


def tick(now: datetime | None = None) -> int:
    """One sync pass over every linked Item. Never crashes; auth failures flip
    that Item to needs_reauth. Returns rows upserted. Test seam via configure()."""
    if _override not in ("unset", None) and hasattr(_override, "tick"):
        return _override.tick(now)  # type: ignore[union-attr]
    now = now or _utcnow()
    provider = providers.get("plaid")
    if provider is None:
        return 0
    try:
        items = store.list_finance_items()
    except RuntimeError:  # no DATABASE_URL — nothing to do
        return 0
    total = 0
    for item in items:
        try:
            total += _sync_item(provider, item, now)
        except AuthError:
            logger.warning("plaid item %s needs re-auth; flipping status", item["item_id"])
            try:
                store.set_finance_item_status(item["item_id"], "needs_reauth")
            except Exception:
                logger.exception("could not flip %s to needs_reauth", item["item_id"])
        except RuntimeError as exc:
            if "DATABASE_URL" in str(exc):
                return total
            logger.exception("finance sync failed for %s", item["item_id"])
        except Exception:
            logger.exception("finance sync failed for %s", item["item_id"])
    return total


async def trigger() -> int:
    """One sync pass off the event loop. Awaited by connect + POST /api/finance/sync."""
    return await asyncio.to_thread(tick)


async def run_loop() -> None:
    logger.info("finance sync loop started (every %ss)", settings.finance_sync_seconds)
    while True:
        try:
            synced = await asyncio.to_thread(tick)
            if synced:
                logger.info("synced %d finance record(s)", synced)
        except Exception:
            logger.exception("finance sync tick failed")
        await asyncio.sleep(settings.finance_sync_seconds)
```

- [ ] **Step 4: Wire `conftest.py`** — add finance_sync to the `no_external_services` fixture. In the import line add `finance_sync`, then in the setup block (after `moodle_sync.configure(None)`) add `finance_sync.configure(None)`, and in the teardown block (after `moodle_sync.configure("unset")`) add `finance_sync.configure("unset")`:

```python
from app import email_draft, email_sync, email_triage, finance_sync, fitness_sync, food_db, llm, memory_engine, moodle_sync, providers, reminders
```
```python
    moodle_sync.configure(None)
    finance_sync.configure(None)
    yield
```
```python
    moodle_sync.configure("unset")
    finance_sync.configure("unset")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_sync.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Run full suite (baseline hold)**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest -q`
Expected: **~560 passed, 1 skipped** (all provider + sync tests green; nothing else regressed).

- [ ] **Step 7: Commit**

```bash
git add backend/app/finance_sync.py backend/tests/conftest.py backend/tests/test_finance_sync.py
git commit -m "feat(finance): finance_sync engine (multi-item pull) + conftest wiring"
```

---

### Task 15: Schemas (Finance request/response models)

**Files:**
- Modify: `backend/app/schemas.py` (append after the Moodle schemas)
- Test: `backend/tests/test_finance_api.py` (create — a schema-shape import smoke test; endpoint tests follow in Tasks 16–18)

**Interfaces:**
- Produces (importable from `app.schemas`): `LinkStart`, `LinkStartOut`, `LinkComplete`, `FinanceItemOut`, `FinanceStatus`, `FinanceSummary`, `NetWorthBucket`, `NetWorth`, `AccountOut`, `AccountsOut`, `TransactionOut`, `HoldingOut`, `BudgetOut`, `BudgetItem`, `BudgetsUpdate`, `BudgetReallocate`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_finance_api.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_api.py::test_finance_schemas_import -q`
Expected: FAIL — `ImportError: cannot import name 'LinkStart'`.

- [ ] **Step 3: Add the schemas** — append to `backend/app/schemas.py`:

```python
# ---- Finance schemas (M7 Plaid) ---------------------------------------------
class LinkStart(BaseModel):
    kind: Literal["bank", "investments"]


class LinkStartOut(BaseModel):
    hosted_link_url: str
    link_token: str


class LinkComplete(BaseModel):
    link_token: str


class FinanceItemOut(BaseModel):
    item_id: str
    institution_name: str
    status: Literal["active", "needs_reauth"]
    products: List[str]
    connected_at: datetime
    last_sync_at: datetime | None


class FinanceStatus(BaseModel):
    connected: bool
    items: List[FinanceItemOut]


class FinanceSummary(BaseModel):
    month: str
    balance: float
    income_month: float
    spent_month: float
    income_delta: float
    spent_delta: float


class NetWorthBucket(BaseModel):
    name: str
    value: float
    color: str


class NetWorth(BaseModel):
    buckets: List[NetWorthBucket]
    total: float


class AccountOut(BaseModel):
    id: int
    source_id: str
    item_id: str
    name: str
    official_name: str | None
    mask: str | None
    type: str
    subtype: str | None
    current_balance: float | None
    available_balance: float | None
    iso_currency: str


class AccountsOut(BaseModel):
    accounts: List[AccountOut]
    networth: NetWorth


class TransactionOut(BaseModel):
    id: int
    source_id: str
    account_id: str
    name: str
    merchant_name: str | None
    amount: float
    positive: bool
    iso_currency: str
    date: str | None
    pending: bool
    category: str
    when: str


class HoldingOut(BaseModel):
    id: int
    account_id: str
    security_id: str
    name: str
    ticker: str | None
    type: str
    is_crypto: bool
    quantity: float
    value: float
    price: float | None
    currency: str


class BudgetOut(BaseModel):
    category: str
    limit_amount: float
    spent: float
    color: str


class BudgetItem(BaseModel):
    category: str
    limit_amount: float


class BudgetsUpdate(BaseModel):
    month: str
    budgets: List[BudgetItem]


class BudgetReallocate(BaseModel):
    month: str
    from_category: str
    to_category: str
    amount: float
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_api.py::test_finance_schemas_import -q`
Expected: PASS. (`Literal`, `List`, `datetime`, `BaseModel` are already imported at the top of `schemas.py` — the Moodle/fitness schemas use them.)

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas.py backend/tests/test_finance_api.py
git commit -m "feat(finance): schemas (link, status, summary, accounts, transactions, holdings, budgets)"
```

---

### Task 16: Router — Hosted-Link connect + status + main wiring

**Files:**
- Create: `backend/app/routers/finance.py`
- Modify: `backend/app/main.py` (import + `include_router` + lifespan loop)
- Test: `backend/tests/test_finance_api.py` (extend)

**Interfaces:**
- Consumes: `providers.get("plaid")`, `store.*`, `finance_sync.tick`, schemas from Task 15, `PlaidError`/`PlaidAuthError`.
- Produces endpoints: `POST /api/finance/link/start`, `POST /api/finance/link/complete`, `GET /api/finance/status`.

- [ ] **Step 1: Write the failing test** — append to `test_finance_api.py`:

```python
def test_link_start_returns_hosted_url(client):
    from tests.fakes import FakePlaidProvider
    providers.configure([FakePlaidProvider()])
    res = client.post("/api/finance/link/start", json={"kind": "bank"})
    assert res.status_code == 200
    assert res.json()["hosted_link_url"] == "https://plaid/hl"
    assert res.json()["link_token"] == "link-1"


def test_link_complete_stores_item_and_returns_status(client):
    from tests.fakes import FakePlaidProvider
    item = NormalizedItem(item_id="itm1", institution_id="ins_1",
                          institution_name="Chase", products=["transactions"])
    providers.configure([FakePlaidProvider(item=item, accounts=[], delta=TransactionsDelta())])
    res = client.post("/api/finance/link/complete", json={"link_token": "l"})
    assert res.status_code == 200
    body = res.json()
    assert body["connected"] is True
    assert body["items"][0]["institution_name"] == "Chase"
    assert "access_token" not in body["items"][0]           # never serialized


def test_link_complete_409_when_not_finished(client):
    from tests.fakes import FakePlaidProvider
    p = FakePlaidProvider()
    p.public_token = None                                   # user hasn't finished on Plaid's page
    providers.configure([p])
    res = client.post("/api/finance/link/complete", json={"link_token": "l"})
    assert res.status_code == 409


def test_status_reflects_linked_items(client):
    from tests.fakes import FakePlaidProvider
    providers.configure([FakePlaidProvider()])
    client.post("/api/finance/link/complete", json={"link_token": "l"})
    res = client.get("/api/finance/status")
    assert res.status_code == 200 and res.json()["connected"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_api.py::test_link_start_returns_hosted_url -q`
Expected: FAIL — `404` (no `/api/finance/link/start` route registered).

- [ ] **Step 3: Create `routers/finance.py`**

```python
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
```

- [ ] **Step 4: Wire `main.py`**

Add `finance_sync` to the sync import and `finance` to the routers import:

```python
from . import email_sync, finance_sync, fitness_sync, moodle_sync, reminders
```
```python
from .routers import (
    assistant, calendar, email, finance, fitness, habits, memory, moodle,
    nutrition, oauth, tasks,
)
```

Add the include after `moodle.router`:

```python
app.include_router(moodle.router)
app.include_router(finance.router)
```

In `lifespan`, add a finance task var + gate + cleanup (mirroring moodle):

```python
    moodle_task: asyncio.Task | None = None
    finance_task: asyncio.Task | None = None
```
```python
    if settings.moodle_sync_enabled:
        moodle_task = asyncio.create_task(moodle_sync.run_loop())
    if settings.finance_sync_enabled:
        finance_task = asyncio.create_task(finance_sync.run_loop())
    yield
    for task in (reminder_task, fitness_task, email_task, moodle_task, finance_task):
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_api.py -q`
Expected: PASS (5 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/finance.py backend/app/main.py backend/tests/test_finance_api.py
git commit -m "feat(finance): router — Hosted-Link connect + status; wire main + lifespan"
```

---

### Task 17: Router — reads (summary, accounts, transactions, holdings)

**Files:**
- Modify: `backend/app/routers/finance.py`
- Test: `backend/tests/test_finance_api.py` (extend)

**Interfaces:**
- Produces: `GET /api/finance/summary`, `GET /api/finance/accounts`, `GET /api/finance/transactions`, `GET /api/finance/holdings` — all served from the store.

- [ ] **Step 1: Write the failing test** — append:

```python
def _seed_synced(client):
    """Link one item + push accounts/txn/holdings through a sync via the fake."""
    from datetime import date
    from tests.fakes import FakePlaidProvider
    acc = NormalizedAccount(source="plaid", source_id="a1", item_id="itm1", name="Checking",
                            official_name=None, mask="1", type="depository", subtype="checking",
                            current_balance=Decimal("4820.50"), available_balance=Decimal("4820.50"),
                            iso_currency="USD")
    txn = NormalizedTransaction(source="plaid", source_id="t1", account_id="a1", item_id="itm1",
                                name="WF", merchant_name="WF", amount=Decimal("64.20"),
                                iso_currency="USD", date=date(2026, 6, 8), authorized_date=None,
                                pending=False, category_primary="FOOD_AND_DRINK",
                                category_detailed="FOOD_AND_DRINK_GROCERIES", payment_channel="in store")
    delta = TransactionsDelta(added=[txn], next_cursor="C1", has_more=False)
    providers.configure([FakePlaidProvider(item=NormalizedItem(
        item_id="itm1", institution_id="ins_1", institution_name="Chase",
        products=["transactions"]), accounts=[acc], delta=delta)])
    client.post("/api/finance/link/complete", json={"link_token": "l"})


def test_summary_accounts_transactions_reads(client):
    _seed_synced(client)
    summ = client.get("/api/finance/summary?month=2026-06").json()
    assert summ["balance"] == 4820.50
    accts = client.get("/api/finance/accounts").json()
    assert accts["accounts"][0]["name"] == "Checking"
    assert any(b["name"] == "Cash" for b in accts["networth"]["buckets"])
    txns = client.get("/api/finance/transactions").json()
    assert txns[0]["source_id"] == "t1" and txns[0]["category"] == "FOOD_AND_DRINK"


def test_holdings_read(client):
    from tests.fakes import FakePlaidProvider
    sec = NormalizedSecurity(source="plaid", source_id="s1", name="Bitcoin", ticker_symbol="BTC",
                             type="cryptocurrency", close_price=Decimal("60000"), iso_currency="USD")
    hold = NormalizedHolding(source="plaid", item_id="itm1", account_id="brk", security_id="s1",
                             quantity=Decimal("0.05"), institution_value=Decimal("3000"), iso_currency="USD")
    acc = NormalizedAccount(source="plaid", source_id="brk", item_id="itm1", name="Coinbase",
                            official_name=None, mask=None, type="investment", subtype="crypto",
                            current_balance=Decimal("3000"), available_balance=None, iso_currency="USD")
    providers.configure([FakePlaidProvider(item=NormalizedItem(
        item_id="itm1", institution_id="ins_1", institution_name="Coinbase", products=["investments"]),
        holdings=([acc], [sec], [hold]))])
    client.post("/api/finance/link/complete", json={"link_token": "l"})
    holds = client.get("/api/finance/holdings").json()
    assert holds[0]["ticker"] == "BTC" and holds[0]["is_crypto"] is True and holds[0]["value"] == 3000.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_api.py::test_summary_accounts_transactions_reads -q`
Expected: FAIL — `404` on `/api/finance/summary`.

- [ ] **Step 3: Add the read endpoints** to `routers/finance.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_api.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/finance.py backend/tests/test_finance_api.py
git commit -m "feat(finance): router — summary/accounts/transactions/holdings reads"
```

---

### Task 18: Router — budgets, reallocation, disconnect, sync

**Files:**
- Modify: `backend/app/routers/finance.py`
- Test: `backend/tests/test_finance_api.py` (extend)

**Interfaces:**
- Produces: `GET /api/finance/budgets`, `PUT /api/finance/budgets`, `POST /api/finance/budgets/reallocate`, `POST /api/finance/items/{item_id}/disconnect`, `POST /api/finance/sync`.

- [ ] **Step 1: Write the failing test** — append:

```python
def test_budgets_get_put_and_reallocate(client):
    got = client.get("/api/finance/budgets?month=2026-06").json()
    assert len(got) == 6                                    # all six categories present
    client.put("/api/finance/budgets", json={"month": "2026-06", "budgets": [
        {"category": "Dining out", "limit_amount": 250},
        {"category": "Savings", "limit_amount": 600}]})
    client.post("/api/finance/budgets/reallocate", json={
        "month": "2026-06", "from_category": "Dining out", "to_category": "Savings", "amount": 120})
    budgets = {b["category"]: b for b in client.get("/api/finance/budgets?month=2026-06").json()}
    assert budgets["Dining out"]["limit_amount"] == 130.0
    assert budgets["Savings"]["limit_amount"] == 720.0


def test_disconnect_removes_item_and_calls_remove(client):
    from tests.fakes import FakePlaidProvider
    p = FakePlaidProvider(item=NormalizedItem(item_id="itm1", institution_id="ins_1",
                                              institution_name="Chase", products=["transactions"]))
    providers.configure([p])
    client.post("/api/finance/link/complete", json={"link_token": "l"})
    res = client.post("/api/finance/items/itm1/disconnect")
    assert res.status_code == 200 and res.json()["connected"] is False
    assert p.removed == ["acc-tok"]                         # remote remove attempted
    # Second disconnect → 404 (already gone).
    assert client.post("/api/finance/items/itm1/disconnect").status_code == 404


def test_sync_endpoint(client):
    from tests.fakes import FakePlaidProvider
    providers.configure([FakePlaidProvider()])
    client.post("/api/finance/link/complete", json={"link_token": "l"})
    res = client.post("/api/finance/sync")
    assert res.status_code == 200 and "itm1" in res.json()["items"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_api.py::test_budgets_get_put_and_reallocate -q`
Expected: FAIL — `404` on `/api/finance/budgets`.

- [ ] **Step 3: Add the endpoints** to `routers/finance.py`:

```python
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


@router.post("/sync")
def sync_now() -> dict:
    """Run one finance sync pass now. Reads never depend on it."""
    count = finance_sync.tick()
    return {"synced": count, "items": [i["item_id"] for i in store.list_finance_items()]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_api.py -q`
Expected: PASS (10 passed).

- [ ] **Step 5: Run full suite (baseline hold)**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest -q`
Expected: **~573 passed, 1 skipped**. No regressions.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/finance.py backend/tests/test_finance_api.py
git commit -m "feat(finance): router — budgets, reallocation, disconnect, sync"
```

---

### Task 19: Assistant tools (finance reads + local budget writes)

**Files:**
- Modify: `backend/app/tools.py` (handlers + `_finance_action` + `TOOLS` entries)
- Test: `backend/tests/test_finance_tools.py` (create)

**Interfaces:**
- Produces tools: `get_finance_summary`, `get_transactions`, `get_networth`, `get_holdings`, `get_budgets` (reads); `set_budget`, `reallocate_budget` (local writes, confirm-first by convention). No Plaid write tools.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_finance_tools.py
"""M7 assistant tools — finance reads + local budget writes (no Plaid writes)."""
import json

from app import tools
from app.store import store


def test_get_finance_summary_tool_returns_finance_action():
    result, action = tools.execute("get_finance_summary", {"month": "2026-06"})
    assert action["screen"] == "finance"
    assert "balance" in json.loads(result)


def test_reallocate_budget_tool_moves_limit():
    store.upsert_budgets("2026-06", [
        {"category": "Dining out", "limit_amount": 250},
        {"category": "Savings", "limit_amount": 600}])
    result, action = tools.execute("reallocate_budget", {
        "month": "2026-06", "from_category": "Dining out",
        "to_category": "Savings", "amount": 120})
    assert action["screen"] == "finance"
    budgets = {b["category"]: b for b in json.loads(result)["budgets"]}
    assert budgets["Savings"]["limit_amount"] == 720.0


def test_finance_tools_registered_in_definitions():
    names = {d["name"] for d in tools.DEFINITIONS}
    assert {"get_finance_summary", "get_transactions", "get_networth",
            "get_holdings", "get_budgets", "set_budget", "reallocate_budget"} <= names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_tools.py::test_get_finance_summary_tool_returns_finance_action -q`
Expected: FAIL — `Unknown tool get_finance_summary` (the executor returns an error dict; `action` is `None` → `TypeError`/assertion fails).

- [ ] **Step 3: Add handlers** to `backend/app/tools.py` (near the Moodle handlers):

```python
def _finance_action(title: str, meta: str) -> dict:
    return {"icon": "wallet", "title": title, "meta": meta,
            "cta": "Open finance", "screen": "finance"}


def _this_month_str() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _get_finance_summary(args: dict):
    return store.finance_summary(args.get("month")), _finance_action(
        "Summary", "Your money this month")


def _get_transactions(args: dict):
    return store.finance_transactions(
        args.get("days"), args.get("account_id"), args.get("category")
    ), _finance_action("Transactions", "Recent transactions")


def _get_networth(args: dict):
    return store.finance_networth(), _finance_action("Net worth", "Your net worth")


def _get_holdings(args: dict):
    return store.finance_holdings(), _finance_action("Holdings", "Your investments")


def _get_budgets(args: dict):
    return store.finance_budgets(args.get("month") or _this_month_str()), _finance_action(
        "Budgets", "Your budgets")


def _set_budget(args: dict):
    month = args.get("month") or _this_month_str()
    budgets = store.upsert_budgets(month, [{"category": args["category"],
                                            "limit_amount": args["limit_amount"]}])
    return {"budgets": budgets}, _finance_action(
        "Budget updated", f"{args['category']} → ${args['limit_amount']}")


def _reallocate_budget(args: dict):
    month = args.get("month") or _this_month_str()
    budgets = store.reallocate_budget(month, args["from_category"],
                                      args["to_category"], args["amount"])
    return {"budgets": budgets}, _finance_action(
        "Budget moved", f"${args['amount']} {args['from_category']} → {args['to_category']}")
```

- [ ] **Step 4: Register the tools** — add these dicts to the `TOOLS` list (after the Moodle tools):

```python
    {"name": "get_finance_summary",
     "description": "The user's balance, income and spending for a month (default: current).",
     "input_schema": {"type": "object", "properties": {
         "month": {"type": "string", "description": "YYYY-MM"}},
         "additionalProperties": False},
     "run": _get_finance_summary},
    {"name": "get_transactions",
     "description": "Recent bank transactions, optionally filtered by days, account_id, or Plaid category.",
     "input_schema": {"type": "object", "properties": {
         "days": {"type": "integer"}, "account_id": {"type": "string"},
         "category": {"type": "string"}},
         "additionalProperties": False},
     "run": _get_transactions},
    {"name": "get_networth",
     "description": "Net worth broken down by cash, investments, retirement, crypto and credit/loans.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
     "run": _get_networth},
    {"name": "get_holdings",
     "description": "Investment holdings (stocks, ETFs, crypto) with current values.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
     "run": _get_holdings},
    {"name": "get_budgets",
     "description": "Budget limits and derived spending per category for a month.",
     "input_schema": {"type": "object", "properties": {
         "month": {"type": "string"}}, "additionalProperties": False},
     "run": _get_budgets},
    {"name": "set_budget",
     "description": "Set a monthly budget LIMIT for a category (local only; never moves real money). "
                    "Categories: Groceries, Rent & bills, Dining out, Transport, Savings, Other.",
     "input_schema": {"type": "object", "properties": {
         "category": {"type": "string"}, "limit_amount": {"type": "number"},
         "month": {"type": "string"}},
         "required": ["category", "limit_amount"], "additionalProperties": False},
     "run": _set_budget},
    {"name": "reallocate_budget",
     "description": "Move budget LIMIT from one category to another (e.g. roll $120 from Dining out into "
                    "Savings). LOCAL ONLY — never moves real money in a bank. Confirm with the user first.",
     "input_schema": {"type": "object", "properties": {
         "from_category": {"type": "string"}, "to_category": {"type": "string"},
         "amount": {"type": "number"}, "month": {"type": "string"}},
         "required": ["from_category", "to_category", "amount"], "additionalProperties": False},
     "run": _reallocate_budget},
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest tests/test_finance_tools.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Run full suite (baseline hold)**

Run: `cd backend && source ../.venv/bin/activate && TEST_DATABASE_URL= python -m pytest -q`
Expected: **~576 passed, 1 skipped**. (If a test counts the total number of assistant tools, update its expected count.)

- [ ] **Step 7: Commit**

```bash
git add backend/app/tools.py backend/tests/test_finance_tools.py
git commit -m "feat(finance): assistant tools — finance reads + local budget writes"
```

---

### Task 20: Frontend — `api.js` finance method block

**Files:**
- Modify: `frontend/src/lib/api.js` (add a `finance*` block to the exported `api` object)

**Interfaces:**
- Produces: `api.financeStatus`, `api.financeLinkStart(kind)`, `api.financeLinkComplete(linkToken)`, `api.financeSummary(month)`, `api.financeAccounts()`, `api.financeTransactions(opts)`, `api.financeHoldings()`, `api.financeBudgets(month)`, `api.financeSaveBudgets(month, budgets)`, `api.financeReallocate(payload)`, `api.financeDisconnect(itemId)`, `api.financeSync()`.

- [ ] **Step 1: Add the block** — inside the exported `api` object (after the `moodle*` block):

```jsx
  // Finance / Plaid (M7) — every read comes straight from the finance_* tables
  // server-side (a read never triggers a live Plaid call), so the screen works
  // while a sync is mid-flight or Plaid is down. Only linkStart/linkComplete
  // (Hosted Link) and sync reach Plaid. Access tokens never cross this boundary.
  financeStatus: () => request('/api/finance/status'),
  financeLinkStart: (kind) => request('/api/finance/link/start', { method: 'POST', body: JSON.stringify({ kind }) }),
  financeLinkComplete: (linkToken) => request('/api/finance/link/complete', { method: 'POST', body: JSON.stringify({ link_token: linkToken }) }),
  financeSummary: (month) => request(`/api/finance/summary${month ? `?month=${month}` : ''}`),
  financeAccounts: () => request('/api/finance/accounts'),
  financeTransactions: ({ days, accountId, category } = {}) => {
    const q = new URLSearchParams()
    if (days != null) q.set('days', days)
    if (accountId) q.set('account_id', accountId)
    if (category) q.set('category', category)
    const qs = q.toString()
    return request(`/api/finance/transactions${qs ? `?${qs}` : ''}`)
  },
  financeHoldings: () => request('/api/finance/holdings'),
  financeBudgets: (month) => request(`/api/finance/budgets${month ? `?month=${month}` : ''}`),
  financeSaveBudgets: (month, budgets) => request('/api/finance/budgets', { method: 'PUT', body: JSON.stringify({ month, budgets }) }),
  financeReallocate: (payload) => request('/api/finance/budgets/reallocate', { method: 'POST', body: JSON.stringify(payload) }),
  financeDisconnect: (itemId) => request(`/api/finance/items/${itemId}/disconnect`, { method: 'POST' }),
  financeSync: () => request('/api/finance/sync', { method: 'POST' }),
```

- [ ] **Step 2: Verify the frontend still builds**

Run: `cd frontend && npm run build`
Expected: build succeeds (no syntax errors).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.js
git commit -m "feat(finance): api.js finance method block"
```

---

### Task 21: Frontend — live `FinanceScreen`

**Files:**
- Modify (replace): `frontend/src/screens/FinanceScreen.jsx`

**Interfaces:**
- Consumes: `api.finance*` (Task 20). Renders live Summary + Net worth + Budgets + Transactions + Holdings; Subscriptions + Bills stay sample with a "Sample · slice 2" badge. (`App.jsx` branch + `Sidebar.jsx` nav item already exist — no edit.)

- [ ] **Step 1: Replace the component** with the live version:

```jsx
/* Scuffed OS — Finance (live, synced with the user's real accounts via Plaid).
   Owns its own state (App.jsx renders <FinanceScreen /> with no props),
   mirroring School/Email. /api/finance/status drives the connection ladder; the
   reads (summary, accounts, transactions, holdings, budgets) come straight from
   the finance_* tables server-side (never a live Plaid call), so the screen
   works while a sync is mid-flight or Plaid is down. Connect is Hosted Link:
   a button opens Plaid's hosted page in a new tab; after the user finishes
   there, "Finish linking" completes the exchange. Access tokens never reach the
   client. Read-only against Plaid — budgets are the only edit, and they're
   local. Holdings/Subscriptions/Bills day-change is out of slice 1. */
import React from 'react'
import { Card, Stat, Badge, ProgressBar, Button, IconButton } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'
import { api } from '../lib/api.js'

// Slice-2 sample panels (kept visible, clearly labeled).
const SAMPLE_SUBS = [
  { name: 'Netflix', price: '$15.49', cycle: 'monthly', renews: 'Jun 12', color: 'var(--clay-600)', letter: 'N' },
  { name: 'Spotify', price: '$11.99', cycle: 'monthly', renews: 'Jun 18', color: 'var(--green-600)', letter: 'S' },
  { name: 'iCloud+', price: '$2.99', cycle: 'monthly', renews: 'Jun 24', color: 'var(--sky-600)', letter: 'i' },
]
const SAMPLE_BILLS = [
  { name: 'Rent', sub: 'Oak St. Realty', amt: '$1,450', due: 'Due Jul 1', auto: true, icon: 'house', tint: 'honey' },
  { name: 'Internet', sub: 'Verizon Fios', amt: '$70', due: 'Due Jun 16', auto: true, icon: 'wifi', tint: 'sky' },
]
const money = (n) => (n == null ? '—' : n.toLocaleString('en-US', { style: 'currency', currency: 'USD' }))

export function FinanceScreen() {
  const [status, setStatus] = React.useState(null)
  const [summary, setSummary] = React.useState(null)
  const [accounts, setAccounts] = React.useState(null)
  const [txns, setTxns] = React.useState(null)
  const [holdings, setHoldings] = React.useState(null)
  const [budgets, setBudgets] = React.useState(null)
  const [pendingLink, setPendingLink] = React.useState(null)   // {link_token} after a connect button
  const [linkMsg, setLinkMsg] = React.useState('')
  const [edits, setEdits] = React.useState({})                 // category -> edited limit string

  const refresh = React.useCallback(() => {
    api.financeStatus().then((s) => { if (s) setStatus(s) }).catch(() => {})
    api.financeSummary().then((s) => { if (s) setSummary(s) }).catch(() => {})
    api.financeAccounts().then((a) => { if (a) setAccounts(a) }).catch(() => {})
    api.financeTransactions().then((t) => { if (t) setTxns(t) }).catch(() => {})
    api.financeHoldings().then((h) => { if (h) setHoldings(h) }).catch(() => {})
    api.financeBudgets().then((b) => { if (b) setBudgets(b) }).catch(() => {})
  }, [])
  React.useEffect(() => { refresh() }, [refresh])

  const items = status?.items || []
  const connected = items.length > 0
  const needsReauth = items.filter((i) => i.status === 'needs_reauth')

  const startLink = (kind) => {
    setLinkMsg('')
    api.financeLinkStart(kind).then((r) => {
      if (r?.hosted_link_url) {
        window.open(r.hosted_link_url, '_blank', 'noopener')
        setPendingLink({ link_token: r.link_token })
        setLinkMsg('Finish linking in the Plaid tab, then click "Finish linking" below.')
      }
    }).catch(() => setLinkMsg('Could not start the link flow. Try again.'))
  }
  const finishLink = () => {
    if (!pendingLink) return
    api.financeLinkComplete(pendingLink.link_token)
      .then(() => { setPendingLink(null); setLinkMsg(''); refresh() })
      .catch((e) => setLinkMsg(e?.status === 409
        ? 'Still waiting — finish in the Plaid tab, then try again.'
        : 'Linking failed. Try connecting again.'))
  }
  const sync = () => { api.financeSync().then(() => refresh()).catch(() => {}) }
  const disconnect = (itemId) => { api.financeDisconnect(itemId).then(() => refresh()).catch(() => {}) }
  const saveBudgets = () => {
    const month = summary?.month
    const payload = (budgets || []).map((b) => ({
      category: b.category,
      limit_amount: edits[b.category] != null ? Number(edits[b.category]) : b.limit_amount,
    }))
    api.financeSaveBudgets(month, payload).then((b) => { if (b) { setBudgets(b); setEdits({}) } }).catch(() => {})
  }

  const ConnectButtons = (
    <div className="kit-inline" style={{ gap: 10, flexWrap: 'wrap', justifyContent: 'center' }}>
      <Button variant="primary" iconLeft={<Icon name="building-2" />} onClick={() => startLink('bank')}>Connect a bank</Button>
      <Button variant="secondary" iconLeft={<Icon name="bitcoin" />} onClick={() => startLink('investments')}>Connect Coinbase or brokerage</Button>
    </div>
  )
  const FinishLink = pendingLink && (
    <div className="kit-stack" style={{ gap: 8, marginTop: 14, alignItems: 'center' }}>
      <Button variant="primary" size="sm" iconLeft={<Icon name="check" />} onClick={finishLink}>Finish linking</Button>
      {linkMsg && <p className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>{linkMsg}</p>}
    </div>
  )

  // —— not connected: connect card ——
  if (status && !connected) {
    return (
      <Card variant="flat" style={{ maxWidth: 560, margin: '0 auto', padding: '40px 28px', textAlign: 'center' }}>
        <div style={{ display: 'inline-flex', width: 56, height: 56, borderRadius: 'var(--radius-lg)', background: 'var(--accent-soft)', color: 'var(--accent-text)', alignItems: 'center', justifyContent: 'center', marginBottom: 14 }}>
          <Icon name="wallet" />
        </div>
        <h3 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-xl)', color: 'var(--text-strong)', margin: '0 0 6px' }}>Connect your money</h3>
        <p className="kit-muted" style={{ maxWidth: 420, margin: '0 auto 18px' }}>Link a bank for balances, transactions and budgets, or Coinbase/a brokerage for holdings. Read-only — Plaid handles your login and we never move money.</p>
        {ConnectButtons}
        {FinishLink}
        {!pendingLink && linkMsg && <p className="kit-muted" style={{ color: 'var(--clay-600)', marginTop: 12 }}>{linkMsg}</p>}
      </Card>
    )
  }

  const nw = accounts?.networth
  return (
    <div className="kit-stack" style={{ gap: 'var(--gutter)' }}>
      {/* header: linked institutions + sync + add */}
      <div className="kit-inline" style={{ flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        {items.map((it) => (
          <span key={it.item_id} className="kit-inline" style={{ gap: 6, alignItems: 'center', padding: '4px 10px', borderRadius: 999, border: '1px solid var(--paper-300)' }}>
            <span className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>{it.institution_name}</span>
            {it.status === 'needs_reauth' && <Badge color="clay">Reconnect</Badge>}
            <IconButton label="Disconnect" size="sm" onClick={() => disconnect(it.item_id)}><Icon name="x" /></IconButton>
          </span>
        ))}
        <span className="kit-inline" style={{ marginLeft: 'auto', gap: 8 }}>
          <Button variant="soft" size="sm" iconLeft={<Icon name="plus" />} onClick={() => startLink('bank')}>Add</Button>
          <Button variant="soft" size="sm" iconLeft={<Icon name="refresh-cw" />} onClick={sync}>Sync</Button>
        </span>
      </div>
      {pendingLink && <Card variant="flat" style={{ textAlign: 'center', padding: '14px' }}>{FinishLink}</Card>}
      {needsReauth.length > 0 && (
        <Card variant="flat" style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <span className="kit-statline__ico" style={{ background: 'var(--clay-100)', color: 'var(--clay-600)' }}><Icon name="alert-triangle" /></span>
          <div style={{ flex: 1 }}>
            <p className="kit-row__title">Reconnect {needsReauth.map((i) => i.institution_name).join(', ')}</p>
            <p className="kit-muted">A bank login expired. Reconnect to resume syncing.</p>
          </div>
          <Button variant="primary" size="sm" onClick={() => startLink('bank')}>Reconnect</Button>
        </Card>
      )}

      {/* summary */}
      <div className="kit-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
        <Card><Stat label="Balance" value={money(summary?.balance)} icon={<Icon name="wallet" />} /></Card>
        <Card><Stat label={`Income · ${summary?.month || ''}`} value={money(summary?.income_month)} icon={<Icon name="arrow-down-left" />} /></Card>
        <Card><Stat label={`Spent · ${summary?.month || ''}`} value={money(summary?.spent_month)}
          delta={summary?.spent_delta != null ? `${summary.spent_delta >= 0 ? '+' : '−'}${money(Math.abs(summary.spent_delta))} vs last mo` : undefined}
          trend={summary?.spent_delta > 0 ? 'up' : 'down'} icon={<Icon name="arrow-up-right" />} /></Card>
      </div>

      {/* net worth + holdings */}
      <div className="kit-grid" style={{ gridTemplateColumns: '1.15fr 1fr' }}>
        <Card eyebrow="Net worth" title={money(nw?.total)}>
          <div className="kit-nwbar" style={{ marginTop: 4 }}>
            {(nw?.buckets || []).filter((b) => b.value > 0).map((b, i) => {
              const pos = (nw?.buckets || []).filter((x) => x.value > 0).reduce((s, x) => s + x.value, 0) || 1
              return <i key={i} style={{ width: (b.value / pos * 100) + '%', background: `var(--${b.color}-600)` }} />
            })}
          </div>
          <div className="kit-nwleg" style={{ marginTop: 14 }}>
            {(nw?.buckets || []).map((b, i) => (
              <div className="kit-nwleg__item" key={i}>
                <span className="kit-nwleg__dot" style={{ background: `var(--${b.color}-600)` }} />
                <span className="kit-muted" style={{ color: 'var(--text-body)' }}>{b.name}</span>
                <span className="kit-nwleg__val">{money(b.value)}</span>
              </div>
            ))}
          </div>
        </Card>
        <Card title="Holdings">
          {(holdings || []).length === 0 && <p className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>No holdings — connect Coinbase or a brokerage.</p>}
          {(holdings || []).map((h) => (
            <div className="kit-hold" key={h.id}>
              <span className="kit-hold__sym" style={{ background: h.is_crypto ? 'var(--plum-100)' : 'var(--green-100)', color: h.is_crypto ? 'var(--plum-600)' : 'var(--green-600)' }}>{(h.ticker || h.name || '?').slice(0, 3)}</span>
              <div className="kit-row__main">
                <p className="kit-row__title">{h.name}</p>
                <p className="kit-row__sub">{h.ticker || h.type}</p>
              </div>
              <div className="kit-row__amt">{money(h.value)}</div>
            </div>
          ))}
        </Card>
      </div>

      {/* budgets + transactions */}
      <div className="kit-grid" style={{ gridTemplateColumns: '1fr 1.2fr' }}>
        <Card title="Budgets" eyebrow={summary?.month}
          action={<Button variant="soft" size="sm" onClick={saveBudgets} disabled={Object.keys(edits).length === 0}>Save</Button>}>
          <div className="kit-stack" style={{ marginTop: 4, gap: 10 }}>
            {(budgets || []).map((c) => (
              <div key={c.category}>
                <ProgressBar label={c.category} value={c.spent} max={Math.max(c.limit_amount, 1)} color={c.color}
                  meta={`${money(c.spent)} / ${money(c.limit_amount)}`} />
                <input type="number" className="kit-input" defaultValue={c.limit_amount}
                  onChange={(e) => setEdits((prev) => ({ ...prev, [c.category]: e.target.value }))}
                  style={{ width: 90, marginTop: 4, padding: '4px 8px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--paper-300)', fontFamily: 'var(--font-mono, monospace)', fontSize: 12 }} />
              </div>
            ))}
          </div>
        </Card>
        <Card title="Recent transactions">
          {(txns || []).length === 0 && <p className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>No transactions yet — they land after the first sync.</p>}
          {(txns || []).slice(0, 12).map((t) => (
            <div className="kit-row" key={t.id}>
              <span className="kit-cat" style={{ background: 'var(--paper-300)' }} />
              <div className="kit-row__main">
                <p className="kit-row__title">{t.merchant_name || t.name}</p>
                <p className="kit-row__sub">{t.category} · {t.when}</p>
              </div>
              <span className={`kit-row__amt ${t.positive ? 'kit-amt--pos' : 'kit-amt--neg'}`}>
                {t.positive ? '+' : '−'}{money(Math.abs(t.amount))}
              </span>
            </div>
          ))}
        </Card>
      </div>

      {/* slice-2 sample panels (clearly labeled) */}
      <div className="kit-grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
        <Card title="Subscriptions" action={<Badge color="slate">Sample · slice 2</Badge>}>
          {SAMPLE_SUBS.map((s, i) => (
            <div className="kit-sub" key={i}>
              <span className="kit-sub__logo" style={{ background: s.color }}>{s.letter}</span>
              <div className="kit-sub__main"><p className="kit-row__title">{s.name}</p><p className="kit-row__sub">{s.price} · {s.cycle}</p></div>
              <span className="kit-row__sub" style={{ fontFamily: 'var(--font-mono)' }}>Renews {s.renews}</span>
            </div>
          ))}
        </Card>
        <Card title="Bills & recurring" action={<Badge color="slate">Sample · slice 2</Badge>}>
          {SAMPLE_BILLS.map((b, i) => (
            <div className="kit-sub" key={i}>
              <span className="kit-workout__ico" style={{ width: 38, height: 38, background: `var(--${b.tint}-100)`, color: `var(--${b.tint}-600)` }}><Icon name={b.icon} /></span>
              <div className="kit-sub__main"><p className="kit-row__title">{b.name}</p><p className="kit-row__sub">{b.sub} · {b.due}</p></div>
              <span className="kit-row__amt">{b.amt}</span>
            </div>
          ))}
        </Card>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify the build + a couple icons exist**

Run: `cd frontend && npm run build`
Expected: build succeeds. If `building-2`, `bitcoin`, `plus`, or `check` are missing from `frontend/src/lib/Icon.jsx`, add them (they're lucide names) or swap for an existing icon (e.g. `wallet`, `landmark`); rebuild.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/screens/FinanceScreen.jsx frontend/src/lib/Icon.jsx
git commit -m "feat(finance): live FinanceScreen (connect ladder, summary, net worth, budgets, transactions, holdings)"
```

---

### Task 22: Live smoke test `smoke_plaid.py`

**Files:**
- Create: `backend/app/smoke_plaid.py`

**Interfaces:**
- Read-only end-to-end against real Plaid; **not in CI**; exit `0` all-passed / `1` pipeline failure / `2` not-connected. Run: `python -m app.smoke_plaid`.

- [ ] **Step 1: Write the smoke script**

```python
"""End-to-end smoke test for the live Plaid read pipeline (M7). Drives the REAL
PlaidProvider against real Plaid using the access_tokens stored in finance_items,
then exercises accounts / transactions / holdings. Makes NO writes — Plaid slice-1
is read-only. Run by hand (NOT in CI): python -m app.smoke_plaid

Exit: 0 all legs passed · 1 pipeline failure · 2 no Item linked yet (link a bank
via the Finance screen's Hosted Link first)."""
from __future__ import annotations

import logging
import sys

from . import providers
from .config import settings
from .store import store


class Reporter:
    def __init__(self) -> None:
        self.failed = False

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""))
        self.failed = self.failed or not ok
        return ok


def _print_connect_help() -> None:
    print("\nNo Plaid Item linked yet. To connect end-to-end:")
    print("  1. Set PLAID_CLIENT_ID / PLAID_SECRET / PLAID_ENV in backend/.env.")
    print("  2. Start the backend + frontend, open the Finance screen.")
    print("  3. Click 'Connect a bank' (or Coinbase), finish in the Plaid tab, then 'Finish linking'.")
    print("  4. Re-run `python -m app.smoke_plaid`.")


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="    ! %(name)s: %(message)s")
    r = Reporter()
    print("Scuffed OS -- live Plaid read pipeline smoke test")
    print(f"  owner={settings.owner!r}  plaid_env={settings.plaid_env!r}")

    if not r.check(bool(settings.database_url), "DATABASE_URL configured"):
        return 1
    if not r.check(bool(settings.plaid_client_id and settings.plaid_secret),
                   "PLAID_CLIENT_ID / PLAID_SECRET configured"):
        return 1
    provider = providers.get("plaid")
    if not r.check(provider is not None, "Plaid provider registered"):
        return 1

    items = store.list_finance_items()
    if not items:
        r.check(False, "at least one Item linked", "not connected -- see below")
        _print_connect_help()
        return 2
    r.check(True, "Items linked", f"{len(items)}")

    for it in items:
        item_id = it["item_id"]
        print(f"\nItem {item_id} ({it['institution_name']}) products={it['products']}:")
        token = store.get_finance_item_token(item_id)
        if not r.check(bool(token), "access_token present server-side"):
            continue
        try:
            accounts = provider.get_accounts(token)
            r.check(True, "accounts fetched", f"{len(accounts)}")
            for a in accounts[:6]:
                print(f"        - {a.name!r} ({a.type}/{a.subtype}) bal={a.current_balance}")
            if "transactions" in (it["products"] or []):
                delta = provider.sync_transactions(token, store.get_finance_item_cursor(item_id))
                r.check(True, "transactions/sync page", f"+{len(delta.added)} ~{len(delta.modified)} -{len(delta.removed)}")
            if "investments" in (it["products"] or []):
                accts, secs, holds = provider.get_holdings(token)
                r.check(True, "holdings fetched", f"{len(holds)} across {len(secs)} securities")
                for h, s in [(h, next((x for x in secs if x.source_id == h.security_id), None)) for h in holds[:6]]:
                    print(f"        - {(s.ticker_symbol if s else h.security_id)!r} qty={h.quantity} value={h.institution_value}")
        except Exception as exc:  # a live call blew up -- report, don't traceback-dump
            r.check(False, f"pipeline raised {type(exc).__name__}", str(exc)[:140])

    print("\nRESULT:", "ALL PASSED" if not r.failed else "FAILURES -- see above")
    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify it imports + gates cleanly with no credentials**

Run: `cd backend && source ../.venv/bin/activate && python -m app.smoke_plaid; echo "exit=$?"`
Expected: prints the preconditions, fails the `DATABASE_URL`/credentials gate (or, if `.env` has them but no Item, prints the connect help), exits `1` or `2` — never a traceback.

- [ ] **Step 3: Commit**

```bash
git add backend/app/smoke_plaid.py
git commit -m "feat(finance): smoke_plaid.py live read pipeline (not in CI)"
```

---

### Task 23: Privacy Wave 4 + docs

**Files:**
- Modify: `docs/privacy-policy.md` (§3 provider table row, §4 new subsection, §6 retention, effective-date bump)
- Modify: `docs/finance.md` (status → live slice-1), `docs/README.md` (row)
- (Out-of-repo, user-approval action, do **not** auto-push): mirror the §4 block to the corp site `scuffed-corporation/privacy/index.html` and the gist.

**Interfaces:** documentation only — no code, no tests.

- [ ] **Step 1: Add the §4 subsection** to `docs/privacy-policy.md` (following the Moodle/Gmail template), verbatim:

```markdown
### If you choose to connect a bank or Coinbase (Plaid)

Scuffed OS can link your financial institutions through **Plaid** so the Finance
screen shows real balances, transactions, net worth, and investment holdings
(including Coinbase crypto). This is **read-only**: the app **never moves money,
initiates a transfer, or writes anything back to your bank or Coinbase.**

- **How it connects.** You link an institution through Plaid's own hosted flow.
  **Plaid handles your bank/Coinbase login — Scuffed OS never sees your
  credentials.** Plaid returns an access token that lets us read your data; that
  token is stored **server-side only** and never sent to the browser.
- **What is stored:** institution and account names/masks/types, balances,
  transaction metadata (date, amount, merchant, Plaid category), and investment
  holdings + securities (including crypto). Budgets you set are **local** and
  never leave the app; net worth is computed locally.
- **What is not stored:** your bank/Coinbase credentials (Plaid holds those),
  and full statements/documents.
- **Anthropic.** No financial data is sent to Anthropic **except** when you ask
  the assistant about your money — then the relevant figures transit to generate
  the reply and are not stored beyond it. The assistant can edit **local budget
  limits** on your instruction; it can **never** move money.
- **Disconnect.** Disconnecting an institution removes it at Plaid and deletes
  all of its data from Scuffed OS within 30 days.

Scuffed OS is not affiliated with Plaid, Coinbase, or your bank.
```

- [ ] **Step 2: Add the §3 provider-table row + §6 retention line + bump the effective date** (match the existing Gmail/Moodle rows' format). Add **Plaid** to the "Service providers" table (data shared: access to financial account data you authorize) and a §6 retention line ("Connected-institution data is deleted within 30 days of disconnecting").

- [ ] **Step 3: Rewrite `docs/finance.md` status** from "planned (no backend)" to the live slice-1 (Plaid, multi-item, read-only; Summary/Net worth/Transactions/Budgets/Holdings live; Subscriptions/Bills slice-2), and update the `docs/README.md` Finance row to link it and note "M7 · live (Plaid, read-only)".

- [ ] **Step 4: Commit** (docs only; the corp-site + gist mirror is a separate user-approved push):

```bash
git add docs/privacy-policy.md docs/finance.md docs/README.md
git commit -m "docs(finance): privacy wave 4 (Plaid) + finance.md/README status"
```

- [ ] **Step 5: Surface the external mirror to the user** — remind them to mirror the §4 block to the corp site and the gist (both are user-approval publish actions; do not push them automatically).

---

### Task 24: Live gate (no code)

**Files:** none — this is the manual end-to-end verification, run by the user.

- [ ] **Step 1: Prerequisite** — the user completes Plaid dashboard **Production** approval and sets `PLAID_CLIENT_ID` / `PLAID_SECRET` / `PLAID_ENV=production` in `backend/.env`.
- [ ] **Step 2:** Start backend + frontend; open the Finance screen; click **Connect a bank**, finish in the Plaid tab, click **Finish linking**; repeat with **Connect Coinbase or brokerage**.
- [ ] **Step 3:** Verify Summary (balance/income/spent), Net worth (incl. a real **Crypto** bucket from Coinbase), Recent transactions, Budgets (edit a limit → Save), and Holdings all render real data.
- [ ] **Step 4:** Run `python -m app.smoke_plaid` → expect exit `0` (ALL PASSED).
- [ ] **Step 5:** Resolve the `[confirm-against-live]` markers in `providers/plaid.py` and `store.py` against the real payloads (personal_finance_category → bucket map, security `type` values, account subtypes, the Hosted-Link `get_link_public_token` result shape). Adjust the mapping/parse if the live shapes differ; re-run the suite.
- [ ] **Step 6:** Confirm the full suite is green and report the final pass count. Open the PR (`m7-finance-plaid-slice1`), mirror the privacy §4 block to the corp site + gist (user-approved), and note the live-gate results in the PR description.

---

## Self-Review

- **Spec coverage:** §2 architecture → Tasks 2,10–14,16; §3 connect (Hosted Link, product-aware, multi-item) → Tasks 10,12,16; §4 six tables → Tasks 3,4; §5 reads/derivations → Tasks 6,9,17,18; §6 assistant → Task 19; §7 frontend → Tasks 20,21; §8 config → Task 1; §9 privacy → Task 23; §10 robustness (needs_reauth, no webhooks) → Tasks 11,14; §12 testing (fakes, conftest) → Tasks 10,13,14; §13 live gate → Task 24. All covered.
- **Type consistency:** `NormalizedItem.products` (`list[str]`) is set from `get_item` (Task 10) and consumed by `_sync_item` (Task 14) and `finance_status` (Task 5); `TransactionsDelta` fields match producer (`sync_transactions`, Task 11) and consumer (`apply_transaction_delta`, Task 6); `store.get_finance_item_cursor` (Task 5, renamed public) is consumed only in Task 14; `_finance_item_dict` omits `access_token`/`cursor` everywhere.
- **No placeholders:** every step has runnable code + exact commands + expected output; `[confirm-against-live]` markers are the deliberate, spec-mandated exception (resolved in Task 24), not gaps.

