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

const money = (n) => (n == null ? '—' : n.toLocaleString('en-US', { style: 'currency', currency: 'USD' }))

export function FinanceScreen() {
  const [status, setStatus] = React.useState(null)
  const [summary, setSummary] = React.useState(null)
  const [accounts, setAccounts] = React.useState(null)
  const [txns, setTxns] = React.useState(null)
  const [holdings, setHoldings] = React.useState(null)
  const [budgets, setBudgets] = React.useState(null)
  const [subs, setSubs] = React.useState(null)
  const [bills, setBills] = React.useState(null)
  const [invTxns, setInvTxns] = React.useState(null)
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
    api.financeSubscriptions().then((s) => { if (s) setSubs(s) }).catch(() => {})
    api.financeBills().then((b) => { if (b) setBills(b) }).catch(() => {})
    api.financeInvestmentTransactions().then((t) => { if (t) setInvTxns(t) }).catch(() => {})
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
  const reauth = (itemId) => {
    api.financeReauthStart(itemId).then((r) => {
      if (r?.hosted_link_url) {
        window.open(r.hosted_link_url, '_blank', 'noopener')
        setPendingLink({ reauthItemId: itemId })
        setLinkMsg('Finish reconnecting in the Plaid tab, then click "Finish linking".')
      }
    }).catch(() => setLinkMsg('Could not start reconnect. Try again.'))
  }
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
            {it.status === 'needs_reauth' && <Badge color="clay" style={{ cursor: 'pointer' }} onClick={() => reauth(it.item_id)}>Reconnect</Badge>}
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
          <Button variant="primary" size="sm" onClick={() => reauth(needsReauth[0].item_id)}>Reconnect</Button>
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

      {/* investment activity ledger */}
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

      {/* subscriptions + bills (live) */}
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
    </div>
  )
}
