/* Scuffed OS — Dashboard (home overview).
   Agenda + nutrition rings (M3) and the finance snapshot (M7, Plaid) are all live. */
import React from 'react'
import { Button, Card, IconButton, Badge, Stat, ProgressBar, ProgressRing, Checkbox } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'
import { api } from '../lib/api.js'

const money = (n) => (n == null ? '—' : n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }))

export function DashboardScreen({ tasks, onToggleTask, voiceNotes, calendar, nutrition, onNavigate }) {
  // Live finance snapshot (M7): real balance, month spend, recent transactions.
  const [finance, setFinance] = React.useState(null)  // { summary, txns } | null while loading
  React.useEffect(() => {
    let alive = true
    Promise.all([
      api.financeSummary().catch(() => null),
      api.financeTransactions({ days: 30 }).catch(() => null),
    ]).then(([summary, txns]) => { if (alive) setFinance({ summary, txns: txns || [] }) })
    return () => { alive = false }
  }, [])
  const summary = finance && finance.summary
  const financeTxns = (finance && finance.txns) || []
  // "Connected" once any real money/activity exists; otherwise show the empty state.
  const financeConnected = !!summary && (summary.balance !== 0 || financeTxns.length > 0)
  // Up-next occurrences double as the agenda; `when` arrives pre-formatted.
  const agenda = ((calendar && calendar.upNext) || []).map((u, i) => ({
    time: (u.when || '').split(' · ')[0],
    title: u.title,
    meta: (u.when || '').split(' · ').slice(1).join(' · '),
    icon: u.tint === 'sky' ? 'video' : undefined,
    moodle: u.source === 'moodle',
    active: i === 0,
  }))
  const today = new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' }).replace(',', ' ·')
  const day = nutrition && nutrition.day
  const totals = (day && day.totals) || { kcal: 0, protein_g: 0 }
  const targets = (day && day.targets) || { calories: 2100, protein_g: 160 }
  const water = (day && day.water) || { cups: 0, goal: 8 }
  return (
    <div className="kit-grid kit-grid--dash">
      <div className="kit-col">
        <Card eyebrow={today} title="Up next" action={<IconButton label="Open calendar" size="sm" onClick={() => onNavigate && onNavigate('calendar')}><Icon name="arrow-up-right" /></IconButton>}>
          <div className="kit-agenda">
            {agenda.length === 0 && <p className="kit-muted">Nothing scheduled — enjoy the quiet.</p>}
            {agenda.map((a, i) => (
              <div key={i} className={`kit-agenda__item ${a.active ? '' : 'kit-agenda__item--muted'}`}>
                <div className="kit-agenda__time">{a.time}</div>
                <div className="kit-agenda__body">
                  <p className="kit-agenda__title">{a.title}{a.moodle && <Badge color="plum" style={{ marginLeft: 8 }}>Moodle</Badge>}</p>
                  <p className="kit-agenda__meta">{a.icon && <Icon name={a.icon} />}{a.meta}</p>
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card eyebrow={summary ? `Live · ${summary.month}` : 'Finance'} title="Finance snapshot" action={<IconButton label="Open finance" size="sm" onClick={() => onNavigate && onNavigate('finance')}><Icon name="arrow-up-right" /></IconButton>}>
          {!financeConnected ? (
            <div className="kit-insight">
              <div className="kit-insight__icon"><Icon name="wallet" /></div>
              <p>No bank connected yet. Link an account to see your balance, spending and recent transactions here.</p>
            </div>
          ) : (
            <>
              <div className="kit-spread" style={{ marginBottom: 18 }}>
                <Stat label="Balance" value={money(summary.balance)} />
                <div style={{ flex: 1, maxWidth: 230 }}>
                  <ProgressBar label={`Spent · ${summary.month}`} meta={money(summary.spent_month)} value={summary.spent_month} max={Math.max(summary.spent_month, summary.income_month, 1)} color="clay" />
                </div>
              </div>
              {financeTxns.slice(0, 3).map((t) => (
                <div className="kit-row" key={t.id}>
                  <span className="kit-cat" style={{ background: t.positive ? 'var(--green-600)' : 'var(--clay-600)' }} />
                  <div className="kit-row__main">
                    <p className="kit-row__title">{t.merchant_name || t.name}</p>
                    <p className="kit-row__sub">{t.category} · {t.when}</p>
                  </div>
                  <span className={`kit-row__amt ${t.positive ? 'kit-amt--pos' : 'kit-amt--neg'}`}>{t.positive ? '+' : '−'}{money(Math.abs(t.amount))}</span>
                </div>
              ))}
              {financeTxns.length === 0 && <p className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>No transactions in the last 30 days.</p>}
            </>
          )}
        </Card>
      </div>

      <div className="kit-col">
        <Card eyebrow="Captured 4 min ago" title="Your assistant noticed" action={<Icon name="sparkles" />}>
          <div className="kit-insight">
            <div className="kit-insight__icon"><Icon name="lightbulb" /></div>
            <p>You've skipped logging <strong>lunch</strong> twice this week. Want me to set a gentle 1pm reminder and pre-fill your usual?</p>
          </div>
          <div className="kit-inline" style={{ marginTop: 14 }}>
            <Button variant="soft" size="sm" iconLeft={<Icon name="check" />}>Yes, do it</Button>
            <Button variant="ghost" size="sm">Not now</Button>
          </div>
        </Card>

        <Card title="Tasks" action={<span className="kit-muted">{tasks.filter((t) => !t.done).length} left</span>}>
          <div className="kit-stack" style={{ gap: 4 }}>
            {tasks.map((t) => {
              const readOnly = t.editable === false || t.source === 'moodle'
              return (
                <div key={t.id} style={{ padding: '7px 0', display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Checkbox checked={t.done} strikeWhenChecked label={t.label} disabled={readOnly} onChange={readOnly ? undefined : () => onToggleTask(t.id)} />
                  {readOnly && <Badge color="plum">Moodle</Badge>}
                </div>
              )
            })}
          </div>
        </Card>

        <Card title="Nutrition" variant="sunken">
          <div className="kit-rings">
            <div className="kit-ring-cell"><ProgressRing value={Math.round(totals.kcal)} max={targets.calories || 1} size={78} color="green" label={String(Math.round(totals.kcal))} sublabel="kcal" /><span className="kit-ring-cell__lab">Calories</span></div>
            <div className="kit-ring-cell"><ProgressRing value={Math.round(totals.protein_g)} max={targets.protein_g || 1} size={78} color="clay" label={`${Math.round(totals.protein_g)}g`} sublabel="protein" /><span className="kit-ring-cell__lab">Protein</span></div>
            <div className="kit-ring-cell"><ProgressRing value={water.cups} max={water.goal || 1} size={78} color="sky" label={`${water.cups}/${water.goal}`} sublabel="cups" /><span className="kit-ring-cell__lab">Water</span></div>
          </div>
        </Card>
      </div>
    </div>
  )
}
