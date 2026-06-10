# Finance — Architecture

> Status: **planned** (no backend yet) · Last updated: 2026-06-09 · Owner: _TBD_
>
> Part of the [backend overview](backend-overview.md). The largest planned surface:
> accounts, transactions, budgets, net worth, investments, subscriptions, and bills.

## Responsibility

Own the user's money: balances and income/spend summaries, budget categories,
transactions, net-worth breakdown, investment holdings, subscriptions, and bills. Serve
the dashboard figures the assistant quotes ("you've spent $1,840 in June").

## Current state

Not implemented in the backend. `frontend/src/screens/FinanceScreen.jsx` renders
**sample data held in the component** across six panels. This doc describes the backend
function that should own it.

## Data model (from the prototype)

| Entity | Fields the UI uses | Notes |
| --- | --- | --- |
| **Summary** | `balance`, `income_month`, `spent_month`, deltas | Derived from accounts + transactions. |
| **Budget** | `name`, `spent`, `budget`, `color` | Per-category, per-month; `spent` derived from transactions. |
| **Transaction** | `title`/payee, `category`, `date`, `amount`, `positive?` | The ledger; everything else aggregates from it. |
| **Net worth** | breakdown `{name, value}` (Investments/Retirement/Cash/Crypto) + total + monthly % | Asset allocation. |
| **Holding** | `symbol`, `name`, `value`, `change%`, `up?` | Investment positions; needs price data. |
| **Subscription** | `name`, `price`, `cycle`, `renews` (date), `soon?` | Recurring spend; "renews soon" is derived. |
| **Bill** | `name`, `provider`, `amount`, `due` (date), `autopay?` | Upcoming bills. |

## Proposed surface (TODO — confirm)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/finance/summary` | Balance, income, spend, deltas. |
| `GET` | `/api/finance/transactions` | Ledger (filter by date/category). |
| `GET`/`PUT` | `/api/finance/budgets?month=` | Budgets + spent. |
| `GET` | `/api/finance/networth` | Breakdown + total. |
| `GET` | `/api/finance/holdings` | Investments (with live prices). |
| `GET` | `/api/finance/subscriptions`, `/api/finance/bills` | Recurring + upcoming. |
| `POST` | `/api/finance/transfer` | Move money between categories/accounts. |

## Dependencies & interactions

- **Assistant → Finance.** Two intents already target this surface: `move/transfer to
  savings` ("Moved $120 from Dining to Savings") and `spend/budget/how much` ("you've
  spent $1,840"). The transfer needs a real write path (`/transfer`); the spend figures
  should come from this service. The budget insight "$120 under dining — roll into
  savings?" closes the loop. See [assistant.md](assistant.md).
- **Subscriptions/Bills → Calendar/Notifications.** Renewals and due dates are reminder-
  worthy events — see [calendar.md](calendar.md).
- **Store.** Persists via the shared data layer — see [data-store.md](data-store.md).

## External integrations

- **Bank/transaction aggregation** (Plaid-style) for accounts + transactions.
- **Market data** for holding prices and day change.
- Open: which are real integrations vs. manual entry for v1? Money movement (`/transfer`)
  is sensitive — is it real, or a logical category reallocation only?

## How it _should_ function

- [ ] **Transaction ledger as source of truth**; budgets/summary/net-worth aggregate from
      it. Decimal money, currency, and date handling done right.
- [ ] **Categorization** (rules or assistant-assisted) feeding budgets.
- [ ] **Define `transfer` semantics** — real transfer vs. budget reallocation. Guardrails.

## Open questions / future work

- Real financial-institution links vs. manual import (CSV) for v1.
- Security/privacy posture for the most sensitive data in the app.
