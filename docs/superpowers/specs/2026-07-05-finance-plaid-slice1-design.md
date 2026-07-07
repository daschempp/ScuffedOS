# M7 Finance Slice-1 — "Core money glance": Plaid accounts, transactions, holdings + budgets

**Status:** user-approved design (brainstormed 2026-07-05). Implementation plan to follow via writing-plans.
**Depends on:** nothing in M5/M6; branches from `main`. Roadmap (user-approved 2026-07-03): School = M6, **Plaid finance = M7**, Ship/Tauri = M8. Corrects the stale `docs/backend-overview.md`/`docs/finance.md` label ("M6").
**Branch:** `m7-finance-plaid-slice1`.
**Owner:** Dylan Schempp.
**Target:** the user's **real** accounts via Plaid **Production** (`PLAID_ENV=production`) — banks (checking/savings/credit) **and Coinbase** (crypto, via Plaid's Investments product). Sandbox is available behind the same env switch for development/tests, but the milestone target is Production; the final live gate links the real bank + Coinbase.
**Supersedes:** the "planned" Finance sketch in `docs/finance.md` (sample-only `FinanceScreen.jsx`). Adds/rewrites `docs/finance.md` status + `docs/README.md` row.

## 1. Goal

Graduate the **Finance** screen from in-component sample data to live data from the user's real financial
institutions via **Plaid**, all **read-only against Plaid** (we never move money or write to a bank). Slice 1
delivers the daily money glance: **balances/summary**, **net worth** (across cash, investments, retirement,
**crypto**, and credit/loans), the **transaction ledger**, **budgets** (editable local limits vs. Plaid-derived
spend), and **investment holdings** (equities/ETFs/**Coinbase crypto**). This is slice 1 of a program whose end
state replaces day-to-day use of a banking/budgeting app.

**Frozen scope decisions (from brainstorming 2026-07-05):**

1. **Environment:** Production from day one (`PLAID_ENV` is a config setting defaulting to `production`; tests
   never touch real Plaid — see §12). Requires the user to complete Plaid's dashboard use-case approval and
   obtain production `PLAID_CLIENT_ID`/`PLAID_SECRET` (a live-gate prerequisite, §13).
2. **Slice-1 surface:** Summary, Net worth, Recent transactions, Budgets, **and Holdings** live. Subscriptions +
   Bills remain sample (slice 2).
3. **Connect flow:** Plaid **Hosted Link** (open Plaid's hosted page in a new tab → return → poll for the
   `public_token`). No `react-plaid-link`, no `cdn.plaid.com` script, no public callback URL — localhost-friendly.
   **Product-aware** (§3): a "bank" entry point and a "Coinbase / brokerage" entry point.
4. **Budgets:** editable **local** limits (`finance_budgets`) + Plaid-derived spend. Local writes only; never a
   Plaid write. Fixed set of 5 categories + "Other" in slice 1 (custom categories → slice 2).
5. **Money movement:** "move $X to savings" = **logical budget reallocation** (shifts local limits), user-
   initiated + confirm-first, never autonomous. **Real bank transfers are a permanent non-goal.**
6. **Institutions:** **multiple** from the start (`finance_items`, one row per linked Item; balances/
   transactions/net-worth aggregate across all).
7. **Coinbase:** integrated **through Plaid's Investments product** (crypto = holdings whose security
   `type = cryptocurrency`), not a dedicated Coinbase API. If Plaid's Coinbase coverage proves inadequate at the
   live gate, a dedicated `providers/coinbase.py` is a future slice, not this one.

## 2. Program roadmap (read-first, writes-last)

| Slice | Name | Scope |
|---|---|---|
| **1 (this spec)** | Core money glance | Product-aware Hosted-Link connect + multi-item token storage; sync accounts+balances (`/accounts/get`, `/accounts/balance/get`), transactions (`/transactions/sync`), holdings+securities (`/investments/holdings/get`); Finance screen Summary + Net worth + Transactions + Budgets + Holdings live; editable local budgets + logical reallocation; read assistant tools; privacy wave 4; migration `0008_finance` |
| 2 | Recurring & bills | Subscriptions + Bills panels via `/transactions/recurring/get` (+ `/liabilities/get` for loan/card due dates); Bills/renewals → Calendar feed (read-time merge, like Moodle §8); custom budget categories; investment **transaction history** (`/investments/transactions/get`) |
| 3+ | Advanced | Market-data day-change for holdings; webhooks (replace polling); asset-report/statements; autonomous assistant proposals (still confirm-first) |

Explicitly deferred beyond slice 1: any bank **write** / real transfer (permanent non-goal); recurring/bills;
liabilities; investment transaction history; market prices/day-change; custom/user-defined budget categories;
Calendar/Notification feeds; webhooks; multi-currency arithmetic (display currency code only); autonomous
assistant writes.

## 3. Architecture (clones the WHOOP→Gmail→Moodle groove)

Layout: **provider → registry → connect router → sync loop → store → domain router → screen.** Plaid is **not**
an OAuth-redirect provider (no `authorize_url`/`refresh`; access tokens are long-lived and exchanged, not
refreshed), so — like `MoodleProvider` — it is a **custom provider seam**, not the `OAuthProvider` protocol. All
reads come from Postgres; the synced tables *are* the cache (no separate caching/rate-limiting; the sync tick is
the only scheduled caller). Sync ticks never crash.

Module layout (all new unless noted):

- `backend/app/providers/plaid.py` — hand-rolled `httpx` client (**no `plaid-python`**, repo rule). All Plaid
  endpoint/field names confined here; downstream speaks normalized dataclasses. `configure(fake_http=)` test seam;
  lazy `httpx.Client(timeout=20.0)`; host from `PLAID_ENV` (`https://{sandbox|production}.plaid.com`); every
  request injects `client_id`/`secret`. `PlaidAuthError(AuthError)` for item-auth failures
  (`ITEM_LOGIN_REQUIRED`, `INVALID_ACCESS_TOKEN`). `logging.getLogger("scuffed_os.plaid")`. Methods:
  `create_link_token(kind)`, `get_link_public_token(link_token)` (poll `/link/token/get`),
  `exchange_public_token(public_token)` → `(access_token, item_id)`, `get_item(access_token)` (institution meta +
  products), `get_accounts(access_token)`, `sync_transactions(access_token, cursor)` →
  `(added, modified, removed, next_cursor, has_more)`, `get_holdings(access_token)` →
  `(accounts, holdings, securities)`, `remove_item(access_token)`.
- `backend/app/providers/base.py` (modify) — add `NormalizedItem`, `NormalizedAccount`, `NormalizedTransaction`,
  `NormalizedSecurity`, `NormalizedHolding` dataclasses (aware-UTC datetimes; `Decimal` money;
  `source`/`source_id`) and a `PlaidProvider` protocol (custom seam; distinguishing method `get_accounts` used by
  the sync `hasattr` filter, mirroring Moodle's `fetch_school_snapshot`).
- `backend/app/providers/__init__.py` (modify) — register `PlaidProvider()` in `_build_real` try/except.
- `backend/app/finance_sync.py` — clone of `moodle_sync.py`: `configure()` seam; `tick()` (never crashes;
  `except PlaidAuthError` → `set_item_status(item, "needs_reauth")`; DATABASE_URL `RuntimeError` → no-op);
  `trigger()`; `run_loop()` gated by `settings.finance_sync_enabled`. **Loops over all `finance_items`** and, per
  item, branches on its `products`: `transactions` → cursor `sync_transactions`; `investments` →
  `get_holdings`; and always refreshes `get_accounts` balances.
- `backend/app/models.py` (modify) + `backend/alembic/versions/0008_finance.py` — six new tables (§4).
- `backend/app/store.py` (modify) — `# ---- finance ----` section (§4/§5).
- `backend/app/routers/finance.py` — `APIRouter(prefix="/api/finance")`; reads from store only + the connect
  endpoints (§5).
- `backend/app/schemas.py` (modify) — Finance response models (§5).
- `backend/app/main.py` (modify) — `include_router`; lifespan sync loop behind `finance_sync_enabled`.
- `backend/app/config.py` + `backend/.env.example` (modify) — settings (§8).
- `backend/app/tools.py` (modify) — read tools + local budget write tools + deep-link card (§6).
- `frontend/src/screens/FinanceScreen.jsx` + `lib/api.js` (modify; `wallet` icon already exists) — §7.

## 4. Data model + store (migration `0008_finance` — six tables)

All tables carry `owner` (default `settings.owner`), aware-UTC `DateTime(timezone=True)` with Python-side
`default=utcnow`, `JSONField = JSON().with_variant(JSONB(), "postgresql")`, and a unique constraint on
`(owner, source, source_id)` where `source="plaid"` — except `finance_budgets` (keyed `(owner, category, month)`)
and `finance_holdings` (a holding is an account×security pair with no Plaid id of its own, keyed
`(owner, account_id, security_id)`). Idempotent upserts every pass. **Money is `Numeric(16, 2)` + an ISO currency code —
never float** (`docs/finance.md`: "Decimal money done right"). Add all six table names to
`tests/test_migrations.py` `ALL_TABLES`.

| Table | Key columns | Source |
|---|---|---|
| `finance_items` | `source_id`(=item_id), `access_token`(**server-only**, Text), `institution_id`, `institution_name`, `products`(JSON: `["transactions"]`/`["investments"]`/both), `status`(`active`/`needs_reauth`), `cursor`(txn-sync cursor, Text null), `last_sync_at`, `connected_at`, `meta` | `/item/public_token/exchange` + `/item/get` |
| `finance_accounts` | `source_id`(=account_id), `item_id`, `name`, `official_name`, `mask`, `type`(depository/investment/credit/loan), `subtype`(checking/savings/ira/401k/brokerage/credit card/…), `current_balance`(Numeric), `available_balance`(Numeric null), `iso_currency`, `meta` | `/accounts/get`, `/accounts/balance/get` |
| `finance_transactions` | `source_id`(=transaction_id), `account_id`, `item_id`, `name`, `merchant_name`, `amount`(Numeric; **Plaid sign: + = outflow / money leaving**), `iso_currency`, `date`(posted), `authorized_date`(null), `pending`(bool), `category_primary`(PFC primary), `category_detailed`, `payment_channel`, `meta` | `/transactions/sync` |
| `finance_securities` | `source_id`(=security_id), `name`, `ticker_symbol`(null), `type`(equity/etf/mutual fund/**cryptocurrency**/derivative/cash/…), `close_price`(Numeric null), `iso_currency`, `is_cash_equivalent`(bool), `meta` | `/investments/holdings/get` (`securities[]`) |
| `finance_holdings` | unique `(owner, account_id, security_id)`; `item_id`, `account_id`, `security_id`, `quantity`(Numeric), `cost_basis`(Numeric null), `institution_value`(Numeric), `institution_price`(Numeric null), `iso_currency`, `meta` | `/investments/holdings/get` (`holdings[]`) |
| `finance_budgets` | unique `(owner, category, month)`; `limit_amount`(Numeric) — **local, user-editable** | local (UI/assistant) |

Store `# ---- finance ----` section: `_finance_<x>_row` finders, `_<x>_dict` serializers, idempotent
`upsert_finance_item/account/transaction/security/holding`, `apply_transaction_delta(added, modified, removed)`
(applies a `/transactions/sync` page: upsert added/modified by `transaction_id`, delete removed), read methods
(`summary(month)`, `accounts()` + `networth()`, `transactions(window, account_id, category)`, `holdings()`,
`budgets(month)`), budget writes (`upsert_budget`, `reallocate_budget(src, dst, amount, month)`),
`set_item_status`, `set_item_cursor`, `set_item_synced`, and `delete_finance_item(item_id)` (cascade: the item +
its accounts/transactions/holdings; `finance_securities` are shared and pruned when orphaned) for disconnect.
`_finance_item_dict` and `/api/oauth/status` expose **only** derived fields (institution name, status, product
booleans) — **never `access_token`**.

**Category mapping (fixed, slice 1).** Plaid `personal_finance_category.primary` (16 values) → 5 display buckets +
`Other`, defined as a constant map in `store.py`/`plaid.py`:
`FOOD_AND_DRINK→Dining out`; `GROCERIES`(or `FOOD_AND_DRINK` detailed `GROCERIES`)→`Groceries`;
`RENT_AND_UTILITIES`/`LOAN_PAYMENTS`(housing) → `Rent & bills`; `TRANSPORTATION`/`TRAVEL`→`Transport`;
`TRANSFER_OUT`(to savings/investment) → `Savings`; everything else → `Other`. Budget "spent" = Σ outflow amounts of
the current month grouped by mapped bucket. The exact mapping carries `[confirm-against-live]` markers resolved at
the live gate (real PFC values vary).

## 5. Finance API surface (`routers/finance.py`) — reads from DB only

```
POST /api/finance/link/start        {kind: "bank"|"investments"}  -> {hosted_link_url, link_token}
POST /api/finance/link/complete     {link_token}                  -> ProviderStatus   # poll->exchange->store->kick sync
GET  /api/finance/summary           ?month=YYYY-MM                 -> FinanceSummary   # balance, income, spent, deltas
GET  /api/finance/accounts                                         -> AccountsOut      # accounts + networth breakdown + total
GET  /api/finance/transactions      ?days=90&account_id=&category= -> [TransactionOut]
GET  /api/finance/holdings                                         -> [HoldingOut]     # holding ⋈ security
GET  /api/finance/budgets           ?month=YYYY-MM                 -> [BudgetOut]       # limit + derived spent + color
PUT  /api/finance/budgets           {month, budgets:[{category,limit_amount}]} -> [BudgetOut]  # local upsert
POST /api/finance/budgets/reallocate {month, from, to, amount}     -> [BudgetOut]       # logical move, confirm-first
POST /api/finance/items/{item_id}/disconnect                       -> ProviderStatus    # /item/remove + cascade delete
POST /api/finance/sync                                             -> {synced_at, items}# delegates to finance_sync.tick()
```

Derivations (all from synced rows):

- **Summary** (`FinanceSummary`): `balance` = Σ `available_balance` of depository accounts; `income_month` = Σ
  inflows (`amount < 0`) this month; `spent_month` = Σ outflows (`amount > 0`) this month; deltas vs prior month.
  Internal transfers excluded best-effort by category (`TRANSFER_IN`/`TRANSFER_OUT`).
- **Net worth** (`AccountsOut.networth`): buckets — **Cash** (depository balances) · **Crypto** (Σ
  `finance_holdings.institution_value` where the joined security `type = cryptocurrency`) · **Investments** (other
  investment holdings/accounts, non-retirement) · **Retirement** (investment subtypes `ira`/`401k`/`403b`/…) ·
  **Credit/Loans** (credit + loan balances, **negative**). `total` = Σ buckets. (Reverses the earlier "drop
  Crypto" call now that Coinbase is in scope.)
- **Transactions:** synced rows within the window, sign normalized for display (`positive` = inflow).
- **Holdings:** each holding joined to its security → `{name, ticker, type, quantity, value, currency}`. Value =
  `institution_value`. **No day-change %** in slice 1 (needs a market-data feed, out of scope) — the UI omits the
  change chip.
- **Budgets:** per fixed category → `{category, limit_amount, spent (derived), color}`.

Connect/disconnect specifics: `link/complete` polls `get_link_public_token` (Hosted Link delivers the
`public_token` via `/link/token/get` after the user finishes on Plaid's page), exchanges it, fetches item +
accounts (+ holdings if the item has `investments`), and kicks `finance_sync.tick()`. Any live Plaid failure inside
a connect endpoint → `HTTPException(502, "Plaid rejected the request")`. Error envelope via `app/errors.py`.
Provider methods looked up defensively via `getattr(impl, "…", None)`.

## 6. Assistant (chat) stance

New tools in `app/tools.py`:

- **Read (always available):** `get_finance_summary`, `get_transactions` (windowed/filtered), `get_networth`,
  `get_holdings`, `get_budgets` — each returns data + a `{"screen":"finance"}` deep-link action card. Serves the
  existing "how much have I spent" / spend-budget intents for real.
- **Local writes (user-initiated, confirm-first):** `set_budget` (edit a category limit) and `reallocate_budget`
  (the "move $120 Dining→Savings" intent = **budget-limit shift only**, `POST …/budgets/reallocate`). Returns an
  action card. **Never autonomous.**
- **No Plaid write tools, ever.** The assistant cannot move real money, link/unlink institutions, or mutate any
  Plaid-sourced row. Tools registered with tests mirroring `test_email_tools.py`/`test_fitness_tools.py`.

## 7. Frontend — Finance screen + connect

`screens/FinanceScreen.jsx` (self-owned state; clones the Fitness/Email render-state ladder). No new deps; reuse
`ui.jsx` primitives + `kit-*` classes + tokens (no hardcoded colors). No frontend tests — verify with
`npm run build`.

- **Render-state ladder:** not-connected (**connect card**, §below) → awaiting-finish ("Finish linking" after a
  tab was opened) → syncing first backfill ("Fetching your accounts…") → **needs-reauth** banner per item
  ("Reconnect \<institution\>") → main.
- **Connect card (product-aware):** two buttons — **"Connect a bank"** (`link/start {kind:"bank"}`) and **"Connect
  Coinbase or brokerage"** (`link/start {kind:"investments"}`). Each opens `hosted_link_url` in a new tab; on
  return the user clicks **Finish linking** → `link/complete {link_token}`. A small **linked-institutions** list
  (name + status) with per-item **disconnect** and an **add-another** affordance.
- **Live panels:** Summary (3 stats), Net worth (bucket bar + legend incl. Crypto), Recent transactions, Budgets
  (editable limits via the pencil; real "$X under — roll into savings?" insight), **Holdings** (value; **no**
  day-change chip). Manual **Sync** button in the header (`POST /api/finance/sync` → refresh).
- **Slice-2 panels:** Subscriptions + Bills keep rendering their current sample data with a subtle **"Sample ·
  slice 2"** badge (honest, not hidden). This badge is the one small new marker element.
- No polling; `refresh()` on mount + after Sync/connect (`.catch(()=>{})` so a down backend keeps the UI).
- `lib/api.js`: `finance*` method block (`financeStart`, `financeComplete`, `financeSummary`, `financeAccounts`,
  `financeTransactions`, `financeHoldings`, `financeBudgets`, `financeSaveBudgets`, `financeReallocate`,
  `financeDisconnect(itemId)`, `financeSync`).

## 8. Settings + `.env.example`

```
# ---- M7 Finance (Plaid) ----
PLAID_CLIENT_ID=""              # from Plaid dashboard (Production keys)
PLAID_SECRET=""                 # Production secret
PLAID_ENV="production"          # sandbox | production  (host derived: {env}.plaid.com)
PLAID_COUNTRY_CODES="US"
FINANCE_SYNC_ENABLED=True
FINANCE_SYNC_SECONDS=1800       # 30 min
PLAID_BACKFILL_DAYS=90          # first-sync transaction history window
```

`link_token` products are chosen **per connect kind** in code (not a single env list): `bank` →
`products=["transactions"]`, `additional_consented_products=["investments"]` (so a bank that also holds a brokerage
surfaces holdings); `investments` (Coinbase/brokerage) → `products=["investments"]`. `client_name="Scuffed OS"`,
`language="en"`, `hosted_link={ completion_redirect_uri: <app url, optional> }`, `client_user_id=settings.owner`.

## 9. Privacy policy — Wave 4 (most-sensitive-data disclosure, all three copies)

New "If you choose to connect a bank or Coinbase (Plaid)" disclosure across canonical `docs/privacy-policy.md`
(§1 connected-service data, §3 provider table row for **Plaid**, §4 per-integration block, §6 retention), corp
`scuffed-corporation/privacy/index.html`, and the gist (**gist sync is a user-approval action**). Content:
explicit-consent linking via Plaid's hosted flow; **we never see your bank/Coinbase login** (Plaid handles
credentials); what is **stored** (institution + account names/masks/types, balances, transaction metadata +
amounts + categories, investment holdings + securities incl. crypto) vs **derived/local** (budgets are local; net
worth is computed); that **no data is sent to Anthropic except** when the user asks the assistant about finances
(the relevant snapshot transits, not stored beyond the reply); that we **never move money / initiate transfers**;
disconnect deletes all Plaid data within 30 days; "not affiliated with Plaid, Coinbase, or your bank." Effective-
date bump. This is the app's most sensitive data category → strongest disclosure.

## 10. Feature/robustness notes

- **Multi-item, mixed products.** Different institutions support different products; the connect flow is product-
  aware and each `finance_items.products` drives its sync branch. A bank returns `transactions` + accounts; Coinbase
  returns `investments` (holdings) + accounts; a full-service brokerage may return both.
- **Token lifecycle.** Plaid access tokens are long-lived (no refresh). Expiry/de-auth surfaces as
  `ITEM_LOGIN_REQUIRED`/`INVALID_ACCESS_TOKEN` on the next tick → `PlaidAuthError` → item `needs_reauth` → per-item
  "Reconnect" banner (reuses the email/moodle re-auth machinery; re-linking via Hosted Link **update mode** is a
  slice-2 refinement — slice 1 disconnects + re-links).
- **`[confirm-against-live]` markers** on the PFC→bucket map, security `type` values, and account subtype lists,
  resolved at the live gate. Feature-detect (empty pane, never a crash) when an item lacks a product.
- **No webhooks** (polling model; localhost-friendly). **No rate limiting** (the sync tick is the only scheduled
  caller). Sync ticks never crash.

## 11. Cross-domain feeds

**None in slice 1.** (Subscriptions/Bills → Calendar/Notifications is a natural read-time merge like Moodle §8, but
those panels are slice 2, so their Calendar feed defers with them.) No schema change to `tasks`/`events`.

## 12. Testing + validation

- TDD per task; full suite stays green (**baseline 526 passed / 1 skipped**, verified 2026-07-05 over SQLite); M4/M5/M6
  guardrails intact; frontend `npm run build` green. Report pass count after changes (user rule).
- **Fakes** (`tests/fakes.py`): `FakePlaidHTTP` (transport-level — scriptable `endpoint`→JSON routing, records
  calls, `status`/error injection to exercise error handling incl. `ITEM_LOGIN_REQUIRED`, `INVALID_ACCESS_TOKEN`,
  and `/transactions/sync` `has_more` pagination) drives the **real** `PlaidProvider` parsing/auth;
  `FakePlaidProvider` (protocol-level) drives sync/router logic. Payload builders for accounts/transactions/
  holdings/securities (incl. a `cryptocurrency` security for the Coinbase path).
- **conftest:** add `finance_sync.configure(None)` to `no_external_services` (setup + teardown) and register
  `FakePlaidProvider` so no test reaches the network.
- **Test files:** `test_finance_{config,models,store,sync,api,tools}.py` + `test_plaid_provider.py`. Provider tests
  cover link-token create (per kind), Hosted-Link `public_token` poll, `public_token` exchange, `/transactions/sync`
  cursor + `added/modified/removed` idempotency + `has_more` paging, `/investments/holdings/get` parsing
  (holdings ⋈ securities, crypto type), the HTTP-error→`PlaidAuthError` mapping, `Decimal` money, epoch/ISO date
  handling. Store/API tests cover net-worth bucketing (incl. Crypto), month income/spent, category mapping, budget
  reallocation math, per-item `needs_reauth`, cascade delete on disconnect. Migration parity via `test_migrations.py`.
- **Live smoke** `app/smoke_plaid.py` (Reporter pattern, exit 0/1/2, **not in CI**): create link tokens →
  (manual Hosted Link for a bank **and** Coinbase) → exchange → accounts → `/transactions/sync` → holdings → print
  counts; read-only.

## 13. Live gate (final task, no code)

Prerequisite: the user completes Plaid's dashboard use-case/**Production** approval and sets
`PLAID_CLIENT_ID`/`PLAID_SECRET` (+ `PLAID_ENV=production`). Then: link a **real bank** and **Coinbase** via Hosted
Link; verify Summary, Net worth (incl. a real Crypto bucket), Transactions, Budgets, and Holdings render; resolve
`[confirm-against-live]` markers (PFC map, security types, subtypes). Read-only — no writes to any institution.

## 14. Out of scope (this slice)

Any bank write / real transfer (**permanent non-goal**); Subscriptions + Bills (recurring/liabilities, slice 2);
Bills/renewals → Calendar feed; investment transaction history; market-data prices/day-change; custom/user-defined
budget categories; Hosted-Link update-mode re-auth; webhooks; multi-currency arithmetic; a dedicated Coinbase API
provider; autonomous assistant writes; the iPhone client.
