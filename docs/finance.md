# Finance — Architecture

> Status: **building** (M7 slice-1) · Last updated: 2026-07-05 · Owner: _Dylan_
>
> Part of the [backend overview](backend-overview.md). A **read-only**, multi-institution
> view of the user's real bank and Coinbase accounts via **Plaid** — balances, net worth,
> transactions, budgets, and investment holdings (including crypto).

## Responsibility

Own the user's money: balances and income/spend summaries, budget categories,
transactions, net-worth breakdown, and investment holdings — synced read-only from Plaid.
Serve the dashboard figures the assistant quotes ("you've spent $1,840 in June").
Subscriptions and bills remain a future slice.

## Surface / current state

Building in M7 slice-1. The screen is served from the DB — every `/api/finance/*` GET
reads stored rows; Plaid is only reached to link an institution (Hosted Link) and on
sync. **Summary, Net worth, Recent transactions, Budgets, and Holdings are live**;
Subscriptions and Bills panels still render sample data (slice 2).

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/finance/link/start` | Mint a Plaid Hosted Link token (bank or investments/Coinbase). |
| `POST` | `/api/finance/link/complete` | Poll the Hosted Link session, exchange the token, store the Item, kick a sync. |
| `GET` | `/api/finance/status` | Linked institutions + connection state. |
| `GET` | `/api/finance/summary` | Balance, income, spend, deltas. |
| `GET` | `/api/finance/accounts` | Linked accounts. |
| `GET` | `/api/finance/transactions` | Ledger (filter by date/category). |
| `GET` | `/api/finance/holdings` | Investment holdings, incl. Coinbase crypto. |
| `GET`/`PUT` | `/api/finance/budgets` | Budgets + spend. |
| `POST` | `/api/finance/budgets/reallocate` | Local budget-limit reallocation (never a Plaid write). |
| `POST` | `/api/finance/items/{item_id}/disconnect` | Unlink an institution and delete its data. |
| `POST` | `/api/finance/sync` | Pull the linked Items from Plaid (the tick). |

## Data model

Six owner-scoped tables (migration `0008_finance`): `finance_items` (one row per linked
Plaid Item — multi-institution from the start), `finance_accounts`, `finance_transactions`,
`finance_holdings`/securities, and `finance_budgets` (local, editable limits). Net worth is
computed from accounts + holdings at read time, not stored. See [data-store.md](data-store.md).

## Dependencies & interactions

- **Assistant → Finance.** The assistant can answer spend/budget questions ("you've spent
  $1,840 in Dining") and, on your instruction, reallocate **local** budget limits
  ("move $120 from Dining to Savings" shifts limits only — it is never a real bank
  transfer). See [assistant.md](assistant.md).
- **Subscriptions/Bills → Calendar/Notifications** (slice 2). Renewals and due dates will
  be reminder-worthy events — see [calendar.md](calendar.md).
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
- [ ] **Subscriptions + Bills** live sync (slice 2).

## Open questions / future work

- Subscriptions/Bills as live Plaid-derived data (recurring transactions, liabilities).
- Market-data prices/day-change for holdings.
- Hosted-Link update-mode re-auth, webhooks, custom budget categories.
