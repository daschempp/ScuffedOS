# M7 Finance Slice-2 — "Recurring & bills": subscriptions, bills, liabilities, investment ledger + calendar merge

**Status:** user-approved design (brainstormed 2026-07-06). Implementation plan to follow via writing-plans.
**Depends on:** M7 slice 1 (`m7-finance-plaid-slice1`) — its `providers/plaid.py`, `finance_sync.py`, `finance_*` tables (migration `0008`), `routers/finance.py`, and `FinanceScreen.jsx`. Slice 1 is not yet merged to `main`, so slice 2 **branches from `m7-finance-plaid-slice1`**, not `main`.
**Branch:** `m7-finance-plaid-slice2`.
**Owner:** Dylan Schempp.
**Target:** the user's **real** accounts via Plaid **Production** (`PLAID_ENV=production`) — same target and live-gate model as slice 1. Sandbox behind the same env switch for dev/tests.
**Supersedes:** the sample `SAMPLE_SUBS`/`SAMPLE_BILLS` panels in `FinanceScreen.jsx` (the "Sample · slice 2" badge is removed when the panels go live). Updates `docs/finance.md` status + `docs/README.md` row + privacy policy (Wave 5).

## 1. Goal

Graduate the two remaining sample panels — **Subscriptions** and **Bills** — to live Plaid data, and add the two
adjacent slice-2 enhancements from the roadmap: **investment transaction history** and **user-flexible budget
categories**. Plus one refinement: **Hosted-Link update-mode reauth**, replacing today's disconnect+relink (which,
as built, would silently create a *duplicate* item — §8). All still **read-only against Plaid**; the only mutation
remains local budgets. Renewals and bill due dates also surface on the **Calendar** via a read-time merge (no
schema change), the same seam Moodle deadlines already use.

**Frozen scope decisions (from brainstorming 2026-07-06):**

1. **Subscriptions + Bills live** from `/transactions/recurring/get` (recurring streams) and `/liabilities/get`
   (loan/credit-card statement + due dates). Feature-detected: an item lacking a product renders an empty pane,
   never a crash.
2. **Bills/renewals → Calendar** via read-time merge inside `store.events_between()` (like `moodle_calendar_events`,
   contract §H). **No write to `events`/`tasks`.** Bill/subscription **notifications** are **deferred to slice 3**.
3. **Budget categories = expanded fixed set** — a longer built-in list (10, §6), **not** user-defined free-form.
   No new table, no data migration: `BUDGET_CATEGORIES`/`_BUDGET_COLORS`/`budget_bucket()` are constants and
   `finance_budgets.category` is already a free string.
4. **Investment transaction history** from `/investments/transactions/get`, shown as a **separate ledger under
   Holdings** (not merged into the bank transactions view).
5. **Update-mode reauth** — `create_link_token(access_token=…)` mints an update-mode Hosted Link that repairs the
   expired item **in place** (same `access_token`, no new item). Completion is **optimistic** (§8).
6. **Reallocate hardening** — `reallocate_budget` clamps limits at `0` (fixes a latent slice-1 bug: it could
   silently produce negative limits).
7. **Money movement stays a permanent non-goal.** No bank writes, no transfers, no autonomous assistant writes.

## 2. Program roadmap (unchanged; this spec = slice 2)

| Slice | Name | Scope |
|---|---|---|
| 1 (`…slice1`) | Core money glance | Hosted-Link connect + multi-item tokens; accounts/balances, `/transactions/sync`, `/investments/holdings/get`; Summary/Net worth/Transactions/Budgets/Holdings live; local budgets + reallocation; read tools; privacy wave 4; migration `0008` |
| **2 (this spec)** | Recurring & bills | Subscriptions + Bills panels via `/transactions/recurring/get` (+ `/liabilities/get`); Bills/renewals → Calendar (read-time merge); expanded budget categories; investment transaction history (`/investments/transactions/get`); update-mode reauth; migration `0009`; privacy wave 5 |
| 3+ | Advanced | Market-data day-change for holdings; **bill/renewal notifications + reminders**; webhooks (replace polling); asset-report/statements; autonomous assistant proposals (still confirm-first) |

Explicitly deferred beyond slice 2: bill/renewal **notifications/reminders** (slice 3); market-data day-change;
webhooks; asset reports/statements; user-defined free-form budget categories; multi-currency arithmetic; any bank
write / real transfer (permanent non-goal); autonomous assistant writes.

## 3. Architecture (extends the slice-1 seam)

Same layout — **provider → registry → sync loop → store → domain router → screen** — with three new Plaid
read endpoints threaded through it. Plaid field/endpoint names stay confined to `providers/plaid.py`; everything
downstream speaks normalized dataclasses. Reads still come only from Postgres; the sync tick is still the only
scheduled Plaid caller and still never crashes.

Modules touched (all *modify* unless noted):

- `backend/app/providers/plaid.py` — 3 new methods (`get_recurring`, `get_liabilities`,
  `get_investment_transactions`) + update-mode branch in `create_link_token`. New endpoint-path constants
  (`TRANSACTIONS_RECURRING_GET`, `LIABILITIES_GET`, `INVESTMENTS_TRANSACTIONS_GET`). `PRODUCTS_NOT_SUPPORTED` (and
  siblings) treated as a **feature-absent** signal, not an error, by the callers (§4).
- `backend/app/providers/base.py` — 3 new dataclasses (`NormalizedRecurringStream`, `NormalizedLiability`,
  `NormalizedInvestmentTransaction`) + the 3 methods added to the `PlaidProvider` protocol.
- `backend/app/models.py` + `backend/alembic/versions/0009_finance_recurring.py` (new; `down_revision = "0008"`)
  — 3 new tables (§5). Register all 3 in `tests/test_migrations.py` `ALL_TABLES`.
- `backend/app/finance_sync.py` — `_sync_item` gains a recurring + liabilities fetch on `transactions` items and an
  investment-transactions fetch on `investments` items (§5).
- `backend/app/store.py` — new `recurring_kind()` classifier; read methods
  `finance_subscriptions()`, `finance_bills()`, `finance_investment_transactions()`,
  `finance_calendar_events()`; upsert methods for the 3 new tables; expanded budget constants; reallocate clamp;
  `delete_finance_item` cascade extended to the 3 new tables.
- `backend/app/routers/finance.py` — 3 new GET endpoints + 2 reauth endpoints (§7).
- `backend/app/schemas.py` — `SubscriptionOut`, `BillOut`, `InvestmentTxnOut`, `ReauthStartOut` (§7).
- `backend/app/tools.py` — 3 read tools (`get_subscriptions`, `get_bills`, `get_investment_transactions`).
- `frontend/src/screens/FinanceScreen.jsx` + `frontend/src/lib/api.js` — wire the two panels, add the investment
  ledger, rewire reauth (§9).
- `docs/finance.md`, `docs/README.md`, privacy policy trio (§11).

## 4. Provider layer (`providers/plaid.py` + `base.py`)

Three normalized dataclasses (aware-UTC dates, `Decimal` money, `source`/`source_id`), mirroring the slice-1 set:

- **`NormalizedRecurringStream`** — `source`, `source_id`(=stream_id), `item_id`, `account_id`, `stream_type`
  (`inflow`/`outflow`), `description`, `merchant_name`, `category_primary`/`category_detailed`, `average_amount`
  (Decimal), `last_amount` (Decimal), `frequency` (WEEKLY/BIWEEKLY/SEMI_MONTHLY/MONTHLY/ANNUALLY/UNKNOWN),
  `first_date`, `last_date`, `predicted_next_date` (Decimal→date; may be computed from `last_date`+`frequency` if
  Plaid omits it — `[confirm-against-live]`), `is_active`, `status`, `iso_currency`.
- **`NormalizedLiability`** — `source`, `source_id`(=account_id), `item_id`, `account_id`, `liability_type`
  (`credit`/`mortgage`/`student`), `last_statement_balance` (Decimal), `minimum_payment` (Decimal),
  `next_payment_due_date` (date), `last_payment_amount`/`last_payment_date`, `apr_percentage` (Decimal),
  `iso_currency`.
- **`NormalizedInvestmentTransaction`** — `source`, `source_id`(=investment_transaction_id), `item_id`,
  `account_id`, `security_id`, `type` (buy/sell/cash/fee/transfer/…), `subtype`, `name`, `quantity` (Decimal),
  `amount` (Decimal), `price` (Decimal), `fees` (Decimal), `date`, `iso_currency`.

Three new methods (each confines Plaid JSON to this module, like `sync_transactions`/`get_holdings`):

- **`get_recurring(access_token)` → `list[NormalizedRecurringStream]`** — `/transactions/recurring/get`; returns
  `inflow_streams` + `outflow_streams` normalized into one list tagged by `stream_type`. Recurring is part of the
  **`transactions` product** (already consented in slice 1), and requires prior `/transactions/sync` — so it runs
  *after* the sync loop in `_sync_item`.
- **`get_liabilities(access_token)` → `list[NormalizedLiability]`** — `/liabilities/get`; flattens
  `liabilities.{credit,mortgage,student}[]` into one list tagged by `liability_type`. **Liabilities is a separate
  Plaid product** (§8 connect change); an item that never consented raises `PRODUCTS_NOT_SUPPORTED` /
  `NO_LIABILITY_ACCOUNTS`, which the caller catches and treats as **empty** (feature-absent, never a crash).
- **`get_investment_transactions(access_token, start, end)` → `tuple[list[NormalizedAccount],
  list[NormalizedSecurity], list[NormalizedInvestmentTransaction]]`** — `/investments/transactions/get` over
  `[start, end]`, **paginated** via `offset`/`count` until `total_investment_transactions` reached; returns
  `securities` (upserted like holdings' securities) alongside the transactions. Under the **`investments` product**
  (already consented). Empty for non-investment items.

**Update-mode link token.** `create_link_token(kind, access_token=None)`: when `access_token` is given, mint an
**update-mode** token — include `access_token`, **omit** `products`/`additional_consented_products` (Plaid rule),
keep `hosted_link`/`user`/`client_name`/`country_codes`. Returns the same `{link_token, hosted_link_url,
expiration}` shape.

`[confirm-against-live]` markers on: recurring stream field names + `predicted_next_date` presence; liabilities
per-type field names + the exact feature-absent `error_code`; investment-transaction `type`/`subtype` values and
the Hosted-Link update-mode completion signal (§8). Constant **names** are frozen by this contract.

## 5. Data model + sync (migration `0009` — three tables)

Same conventions as slice 1: `owner` (default `settings.owner`), aware-UTC `DateTime(timezone=True)` with
`default=utcnow`, `JSONField` `meta`, unique on `(owner, source, source_id)` with `source="plaid"`. **Money is
`Numeric(16, 2)`; quantities `Numeric(24, 8)`; prices `Numeric(20, 8)` — never float.** Add all three names to
`tests/test_migrations.py` `ALL_TABLES`.

| Table | Key columns | Source |
|---|---|---|
| `finance_recurring` | `source_id`(=stream_id), `item_id`, `account_id`, `stream_type`(inflow/outflow), `description`, `merchant_name`, `category_primary`/`category_detailed`, `average_amount`(Numeric), `last_amount`(Numeric), `frequency`, `first_date`, `last_date`, `predicted_next_date`(Date null), `is_active`(bool), `status`, `iso_currency`, `meta` | `/transactions/recurring/get` |
| `finance_liabilities` | `source_id`(=account_id), `item_id`, `account_id`, `liability_type`(credit/mortgage/student), `last_statement_balance`(Numeric null), `minimum_payment`(Numeric null), `next_payment_due_date`(Date null), `last_payment_amount`(Numeric null), `last_payment_date`(Date null), `apr_percentage`(Numeric null), `iso_currency`, `meta` | `/liabilities/get` |
| `finance_investment_transactions` | `source_id`(=investment_transaction_id), `item_id`, `account_id`, `security_id`, `type`, `subtype`, `name`, `quantity`(Numeric 24,8), `amount`(Numeric 16,2), `price`(Numeric 20,8 null), `fees`(Numeric 16,2 null), `date`(Date), `iso_currency`, `meta` | `/investments/transactions/get` |

**Sync (`finance_sync._sync_item`).** Extend the existing per-item product branches (order matters — recurring
needs transactions synced first):

- `"transactions"` item → after the cursor `sync_transactions` loop: `get_recurring()` →
  `upsert_finance_recurring(...)` for each stream; then `get_liabilities()` (feature-detected) →
  `upsert_finance_liability(...)`.
- `"investments"` item → after `get_holdings`: `get_investment_transactions(access_token, now-backfill, now)` →
  upsert securities + `upsert_finance_investment_transaction(...)`.

Per-item isolation is unchanged: one item's `PRODUCTS_NOT_SUPPORTED` or `PlaidAuthError` never poisons others (the
existing per-item try/except handles it; auth still flips only that item to `needs_reauth`). Feature-absent
products are swallowed in the provider caller (empty list), so mixed-product multi-item states never crash.

**`delete_finance_item` cascade** extended: the model loop deletes `finance_recurring`, `finance_liabilities`, and
`finance_investment_transactions` for the item alongside accounts/transactions/holdings. Investment-transaction
securities participate in the existing orphan-security prune.

## 6. Store reads, classifier, calendar merge, expanded budgets

- **`recurring_kind(stream)` classifier** — a `budget_bucket`-style constant map (with `[confirm-against-live]`
  PFC markers) labeling each **outflow** stream `subscription` vs `bill`: subscription ≈
  `ENTERTAINMENT`/`GENERAL_SERVICES` streaming/SaaS PFCs; bill ≈
  `RENT_AND_UTILITIES`/`LOAN_PAYMENTS`/insurance PFCs. Inflow streams (income/paychecks) are neither.
- **`finance_subscriptions()`** → active outflow streams classified `subscription`, each
  `{name, merchant_name, amount, frequency, next_date, category, currency}`, sorted by `next_date`.
- **`finance_bills()`** → outflow streams classified `bill` **⊕** `finance_liabilities` rows (statement/due),
  unified into `{name, sub, amount, due_date, kind, auto, currency}` and sorted by `due_date`. Recurring bills
  carry their `predicted_next_date`; liabilities carry `next_payment_due_date` + `minimum_payment`.
- **`finance_investment_transactions(days=None)`** → ledger joined to `finance_securities` for name/ticker, each
  `{date, type, name, ticker, quantity, amount, price, currency}`, newest first.
- **`finance_calendar_events(window_start, window_end)`** → read-time projection mirroring
  `moodle_calendar_events` (contract §H): bill due dates (`finance_bills`) + subscription renewals
  (`finance_subscriptions`) whose date falls in the window, rendered as `_occurrence_dict`-shaped occurrences with
  `id="finance:<source_id>"`, `source="finance"`, `editable=False`, a distinct `tint` (proposed `honey`
  `[confirm palette]`), `title` like `"Rent · $1,450 due"`. **Appended inside `events_between()`** right after the
  Moodle append — so Home / Calendar / `up_next` all show them with **no `events`-table write**, and the int-typed
  `/api/calendar/events/{id}` routes can never mutate them.
- **Expanded budget categories** — replace the slice-1 constants with a 10-category fixed set. Slice-1's six are
  preserved verbatim (existing `finance_budgets` rows keep working — `category` is a free string; no data
  migration):

  `Groceries · Dining out · Rent & bills · Transport · Shopping · Entertainment · Health · Travel · Savings · Other`

  Extend `_BUDGET_COLORS` (proposed, `[confirm palette tokens in kit.css]`): Groceries→clay, Dining out→plum,
  Rent & bills→honey, Transport→sky, **Shopping→grape**, **Entertainment→lime**, **Health→rose**, **Travel→teal**,
  Savings→green, Other→slate (any missing token falls back to a distinct existing shade). Extend `budget_bucket()`
  PFC mapping for the four new buckets (`GENERAL_MERCHANDISE`→Shopping, `ENTERTAINMENT`→Entertainment,
  `MEDICAL`→Health, `TRAVEL`→Travel), `[confirm-against-live]`. `finance_budgets()`/`upsert_budgets()` iterate the
  constant, so they pick up the new buckets with no signature change.
- **`reallocate_budget` clamp** — floor both resulting limits at `Decimal("0")` (no silent negatives).

## 7. Finance API surface (new endpoints)

```
GET  /api/finance/subscriptions                              -> [SubscriptionOut]
GET  /api/finance/bills                                      -> [BillOut]
GET  /api/finance/investment-transactions  ?days=            -> [InvestmentTxnOut]
POST /api/finance/items/{item_id}/reauth/start              -> ReauthStartOut     # {hosted_link_url, link_token}
POST /api/finance/items/{item_id}/reauth/complete           -> FinanceStatus      # optimistic flip + sync (§8)
```

- **`reauth/start`** — look up the item's `access_token`, then `create_link_token(item_kind, access_token=token)`
  where `item_kind` is derived from the item's `products` (and is **ignored** in update mode, which omits
  `products`); return `{hosted_link_url, link_token}`. `404` if no such item; `502` on Plaid failure.
- **`reauth/complete`** — set the item's status back to `active`, then `finance_sync.tick()`. If reauth truly
  succeeded the sync passes and it stays `active`; if not, the next tick re-flips it to `needs_reauth`. This
  self-healing path avoids depending on Plaid's uncertain update-mode completion payload
  (`[confirm-against-live]` — adopt a cleaner completion signal later if one exists).

Reads serve store rows only (never a live Plaid call). Response models: `SubscriptionOut`
`{name, merchant_name, amount, frequency, next_date, category}`; `BillOut`
`{name, sub, amount, due_date, kind, auto}`; `InvestmentTxnOut`
`{date, type, name, ticker, quantity, amount, price}`; `ReauthStartOut` `{hosted_link_url, link_token}`.

## 8. Update-mode reauth — the correctness fix

**Latent slice-1 bug.** `FinanceScreen.jsx`'s "Reconnect" / needs-reauth buttons call `startLink('bank')` — a
*fresh* connect that exchanges a new `public_token` into a **new** `finance_items` row, i.e. a **duplicate item**,
not a repair of the expired one. Slice 2 fixes it end-to-end:

- Provider: `create_link_token(access_token=…)` → update-mode token (§4).
- API: `reauth/start` + `reauth/complete` (§7).
- Frontend: the reauth buttons call `api.financeReauthStart(itemId)` → open `hosted_link_url` in a new tab →
  `api.financeReauthComplete(itemId)` → `refresh()`. No new item is ever created for an existing institution.

`[confirm-against-live]`: whether Plaid Hosted-Link update mode exposes a completion signal via `/link/token/get`
we could poll (today's `get_link_public_token` returns no `item_add_results` in update mode). The optimistic
flip+sync path is correct regardless.

## 9. Frontend — Finance screen

`screens/FinanceScreen.jsx` (self-owned state, existing render ladder). No new deps; reuse `ui.jsx` primitives +
`kit-*` classes + tokens. Verify with `npm run build` (no frontend tests, per repo convention).

- **Subscriptions panel** — delete `SAMPLE_SUBS` + the "Sample · slice 2" badge; add `subscriptions` state +
  `api.financeSubscriptions()` in `refresh()`; render the existing `.kit-sub` rows from live data
  (logo initial from name, `amount`/`frequency`, "Renews <next_date>"). Empty state: "No subscriptions detected
  yet — they appear after a few weeks of transactions."
- **Bills panel** — delete `SAMPLE_BILLS` + badge; add `bills` state + `api.financeBills()`; render `.kit-sub`
  rows (icon by `kind`, `amount`, "Due <due_date>", auto-pay chip). Empty state mirrors subscriptions.
- **Investment transactions ledger** — new card under Holdings, `api.financeInvestmentTransactions()`, rows
  `{date · type · name/ticker}` with signed `amount`; empty state "No investment activity — connect a brokerage or
  Coinbase." (matches the Holdings empty state).
- **Reauth rewire** — the needs-reauth banner + per-item "Reconnect" call the new
  `api.financeReauthStart(itemId)`/`financeReauthComplete(itemId)` flow (§8), not `startLink`.
- **Budgets** — no code change; the panel already maps over whatever `financeBudgets()` returns, so the four new
  categories render automatically once the store constants expand.
- `lib/api.js` finance block — add `financeSubscriptions()`, `financeBills()`, `financeInvestmentTransactions(days)`,
  `financeReauthStart(itemId)`, `financeReauthComplete(itemId)`.

## 10. Assistant (chat) stance

Add read-only tools in `app/tools.py`, each returning data + a `{"screen":"finance"}` deep-link card, mirroring the
slice-1 finance read tools: **`get_subscriptions`**, **`get_bills`**, **`get_investment_transactions`**. **No new
write tools** — budgets remain the only mutation, and the assistant still cannot move money, link/unlink, or reauth
on the user's behalf. Register with tests mirroring `test_finance_tools.py`.

## 11. Privacy policy — Wave 5 (liabilities disclosure)

Slice 2 stores a **new, more sensitive** category: **liabilities** (loan/credit statement balances, minimum
payments, next-payment due dates, APRs) and **recurring stream** metadata. Privacy Wave 4 disclosed
balances/transactions/holdings but not liability *terms*. Wave 5 amends the Plaid block across the canonical
`docs/privacy-policy.md`, corp `scuffed-corporation/privacy/index.html`, and the gist (**gist sync is a
user-approval publish action**): what is now **stored** (recurring subscription/bill streams; loan & credit-card
statement balances, minimum payments, due dates, APRs; investment transaction history), that it is still
**read-only** and **never sent to Anthropic except** on an explicit finance question, and that disconnect deletes it
with the rest within 30 days. Effective-date bump. **This publish step is a gate requiring the user's approval**,
handled like prior waves.

## 12. Feature/robustness notes

- **Product consent for liabilities.** `/liabilities/get` needs the **`liabilities`** product. Slice 2 adds it to
  the bank link's `additional_consented_products` (so **newly** linked banks surface bills). **Already-linked**
  items never consented to it → `get_liabilities` returns empty (feature-absent) until the item is re-linked. This
  is graceful and expected, and called out in the live gate. Recurring (transactions product) and investment
  transactions (investments product) need **no** new consent.
- **Recurring needs history.** `/transactions/recurring/get` returns meaningful streams only after enough
  transaction history; a freshly linked item may return few/none — the empty state covers it.
- **`[confirm-against-live]`** on: recurring/liabilities/investment-transaction payload shapes; the feature-absent
  `error_code`; the subscription-vs-bill PFC classifier; the new budget-bucket PFC mappings; the calendar tint +
  new budget colors against `kit.css`; the update-mode completion signal. All resolved at the live gate.
- **No webhooks, no rate limiting, no multi-currency arithmetic** (unchanged). Sync ticks never crash.

## 13. Testing + validation

- TDD per task; full suite stays green (**slice-1 finance baseline: 49 finance tests**; report the combined pass
  count after changes, per user rule). Frontend `npm run build` green.
- **Fakes** (`tests/fakes.py`): extend `FakePlaidHTTP` with routable JSON for `/transactions/recurring/get`
  (inflow + outflow streams), `/liabilities/get` (credit/mortgage/student + a feature-absent `error_code` case),
  and `/investments/transactions/get` (multi-page via `offset`/`count`). Add matching `FakePlaidProvider`
  builders. Update-mode `create_link_token(access_token=…)` path.
- **Provider tests** (`test_plaid_provider.py`): recurring parse (stream_type split, frequency, amounts,
  predicted-next fallback), liabilities parse (three types → one list), investment-transactions parse + paging,
  update-mode token (access_token in / products out), feature-absent → caller-visible empty.
- **Sync tests** (`test_finance_sync.py`): recurring + liabilities fetched on a transactions item; investment
  transactions on an investments item; liabilities feature-absent → no rows, no crash; mixed-product multi-item
  (item A transactions-only, item B investments-only) each populate the right tables; disconnect cascade removes
  all three new tables.
- **Store tests** (`test_finance_store.py`): `recurring_kind` classification; `finance_subscriptions`/
  `finance_bills` shaping + sort; liabilities merged into bills; `finance_investment_transactions` join;
  `finance_calendar_events` window filtering + `editable=False`; expanded budget categories (all 10 present,
  new PFC mappings, spend derivation); reallocate clamp (move > source limit → floors at 0, not negative).
- **Calendar test** (`test_calendar_*`): a bill/renewal in-window appears in `events_between()` tagged
  `source="finance"`/`editable=False`, and is **not** mutable through `/api/calendar/events/{id}`; out-of-window
  bills are excluded; no `events` rows are written.
- **API tests** (`test_finance_api.py`): `GET /subscriptions|/bills|/investment-transactions`; `reauth/start`
  (update-mode token minted, `404` for unknown item) and `reauth/complete` (status flips active + sync kicked).
- **Tools tests** (`test_finance_tools.py`): the three new read tools registered + shaped.
- **Migration** (`test_migrations.py`): the three new tables in `ALL_TABLES`; `0009` up/down.
- **Live smoke** (`app/smoke_plaid.py`, not in CI): extend to print recurring/liabilities/investment-transaction
  counts after a live link; still read-only.

## 14. Live gate (final task, no code)

With Production keys set (from slice 1): **re-link** a real bank so the `liabilities` consent is granted; verify the
Subscriptions and Bills panels populate, bills appear on the Calendar, the investment ledger fills from Coinbase/a
brokerage, and expired-item **update-mode reauth** repairs in place (no duplicate item). Resolve all
`[confirm-against-live]` markers (recurring/liabilities/investment shapes, the classifier + budget PFC maps, the
update-mode completion signal). Publish privacy Wave 5. Read-only throughout — no writes to any institution.

## 15. Out of scope (this slice)

Bill/renewal **notifications & reminders** (slice 3); market-data prices/day-change; webhooks;
asset-report/statements; **user-defined free-form** budget categories (this slice is a fixed expanded set);
multi-currency arithmetic; a dedicated Coinbase API provider; any bank write / real transfer (**permanent
non-goal**); autonomous assistant writes; the iPhone client.
