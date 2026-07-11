# Finance — Architecture

> Status: **built** (M7 — live Plaid: reads + local budget writes) · Last updated: 2026-07-11 · Owner: _Dylan_
>
> Part of the [backend overview](backend-overview.md). A **read-only**, multi-institution
> view of the user's real bank and Coinbase accounts via **Plaid** — balances, net worth,
> transactions, budgets, investment holdings (including crypto), subscriptions, and bills.

## Responsibility

Own the user's money: balances and income/spend summaries, budget categories,
transactions, net-worth breakdown, and investment holdings — synced read-only from Plaid.
Serve the dashboard figures the assistant quotes ("you've spent $1,840 in June").
Subscriptions and bills are live as of slice 2, sourced from Plaid recurring streams
and liabilities.

## Surface / current state

Building in M7 slice-2. The screen is served from the DB — every `/api/finance/*` GET
reads stored rows; Plaid is only reached to link an institution (Hosted Link) and on
sync. **Summary, Net worth, Recent transactions, Budgets, Holdings, Subscriptions, and
Bills are live.** Subscriptions and Bills are derived from Plaid's
`/transactions/recurring/get` and `/liabilities/get`; bills/renewals also appear on the
Calendar via a read-time merge (no notifications yet — deferred to slice 3). Holdings
now includes an investment transaction history ledger from
`/investments/transactions/get`. Shipped and unit-tested against fakes; not yet
verified against a live Plaid production pull (see Open questions).

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/finance/link/start` | Mint a Plaid Hosted Link token (bank or investments/Coinbase). |
| `POST` | `/api/finance/link/complete` | Poll the Hosted Link session, exchange the token, store the Item, kick a sync. |
| `GET` | `/api/finance/status` | Linked institutions + connection state. |
| `GET` | `/api/finance/summary` | Balance, income, spend, deltas. |
| `GET` | `/api/finance/accounts` | Linked accounts. |
| `GET` | `/api/finance/transactions` | Ledger (filter by date/category). |
| `GET` | `/api/finance/holdings` | Investment holdings, incl. Coinbase crypto. |
| `GET` | `/api/finance/investment-transactions` | Investment transaction history ledger (buys/sells/dividends/etc). |
| `GET` | `/api/finance/subscriptions` | Recurring outflow streams (subscriptions), classified from Plaid recurring transactions. |
| `GET` | `/api/finance/bills` | Recurring inflow/liability-backed bills (credit card, mortgage, student loan). |
| `GET`/`PUT` | `/api/finance/budgets` | Budgets + spend (10 categories). |
| `POST` | `/api/finance/budgets/reallocate` | Local budget-limit reallocation (never a Plaid write). |
| `POST` | `/api/finance/items/{item_id}/disconnect` | Unlink an institution and delete its data. |
| `POST` | `/api/finance/items/{item_id}/reauth/start` | Mint an update-mode Hosted Link token to fix a broken/expired Item. |
| `POST` | `/api/finance/items/{item_id}/reauth/complete` | Poll the update-mode Hosted Link session and clear the error state. |
| `POST` | `/api/finance/sync` | Pull the linked Items from Plaid (the tick); also syncs recurring streams, liabilities, and investment transactions. |

## Data model

Nine owner-scoped tables (migrations `0008_finance` + `0009_finance_recurring`):
`finance_items` (one row per linked Plaid Item — multi-institution from the start),
`finance_accounts`, `finance_transactions`, `finance_holdings`/securities, and
`finance_budgets` (local, editable limits, now 10 categories) from `0008`; plus
`finance_recurring` (subscriptions/bills classified from Plaid recurring streams),
`finance_liabilities` (credit/mortgage/student-loan detail backing the Bills panel), and
`finance_investment_transactions` (the Holdings ledger) from `0009`. Net worth is
computed from accounts + holdings at read time, not stored. See [data-store.md](data-store.md).

## Dependencies & interactions

- **Assistant → Finance.** The assistant can answer spend/budget questions ("you've spent
  $1,840 in Dining") and, on your instruction, reallocate **local** budget limits
  ("move $120 from Dining to Savings" shifts limits only — it is never a real bank
  transfer). See [assistant.md](assistant.md).
- **Subscriptions/Bills → Calendar.** Renewals and due dates are merged read-time into
  `events_between` — no new rows are written to the calendar store. **Notifications are
  deferred to slice 3** — see [calendar.md](calendar.md).
- **Store.** Persists via the shared data layer — see [data-store.md](data-store.md).

## External integrations

- **Plaid** (Production, `PLAID_ENV`) — Hosted Link connect flow (no `react-plaid-link`,
  no public callback URL); reads accounts, transactions, and investment holdings.
  **Coinbase crypto** is covered through Plaid's Investments product (holdings whose
  security type is `cryptocurrency`), not a dedicated Coinbase API. Read-only this slice —
  the app never moves money or writes back to a bank/Coinbase. See
  [privacy-policy.md](privacy-policy.md) §4 for the user-facing disclosure.

## How it _should_ function

- [x] **Transaction ledger as source of truth**; budgets/summary/net-worth aggregate from
      it, synced from Plaid.
- [x] **Multi-institution** — balances/transactions/net-worth aggregate across all linked
      Items.
- [x] **Budget reallocation is local-only** — a logical limit shift, user-initiated, never
      a real transfer.
- [x] **Subscriptions + Bills** live sync (slice 2) — recurring streams + liabilities,
      classified and stored via migration `0009`.
- [x] **Investment transaction history ledger** (slice 2) — surfaced under Holdings from
      `/investments/transactions/get`.
- [x] **Budget categories expanded to 10** (slice 2).
- [x] **Hosted-Link update-mode reauth** (slice 2) — replaces the old disconnect+relink
      flow for a broken/expired Item.
- [x] **Bills/renewals on the Calendar** (slice 2) — read-time merge, no new writes.

## Open questions / future work

- Bill/renewal **notifications** (reminder-worthy alerts, not just calendar visibility) —
  deferred to slice 3.
- Market-data prices/day-change for holdings.
- Webhooks (push-based sync instead of poll/tick).
- Live verification against a real Plaid production pull — slice 2 is shipped and
  unit-tested against fakes, but not yet exercised against live production data (see
  `smoke_plaid.py`, not run in CI).
