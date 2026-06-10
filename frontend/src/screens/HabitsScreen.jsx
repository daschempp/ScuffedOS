/* Scuffed OS — Habit tracker.
   A view over the shared habits state (useHabits() in App.jsx, passed down as
   the `habits` prop). Streaks, week percentages and today's index all come
   from the server — never recomputed here. Renders an empty grid when the
   backend is down or data hasn't loaded yet. */
import React from 'react'
import { Card, Button, ProgressRing, Stat } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'

const DOW = ['M', 'T', 'W', 'T', 'F', 'S', 'S'] // Mon-first, matching the API's days array

export function HabitsScreen({ habits }) {
  const list = habits?.habits || []
  const doneToday = habits?.doneToday ?? 0
  const weekPct = habits?.weekPct ?? 0
  const prevWeekPct = habits?.prevWeekPct ?? 0
  const todayIndex = habits?.todayIndex ?? null

  const [adding, setAdding] = React.useState(false)
  const [newName, setNewName] = React.useState('')

  const submitNewHabit = () => {
    if (!newName.trim()) return
    habits.addHabit(newName.trim())
    setNewName('')
    setAdding(false)
  }

  const bestStreak = list.length ? Math.max(...list.map((h) => h.best_streak ?? 0)) : 0
  const diff = weekPct - prevWeekPct

  const headAction = adding ? (
    <div className="kit-quickadd" style={{ padding: '7px 11px', minWidth: 200 }}>
      <Icon name="plus" />
      <input
        autoFocus
        placeholder="New habit…"
        value={newName}
        onChange={(e) => setNewName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') submitNewHabit()
          else if (e.key === 'Escape') { setNewName(''); setAdding(false) }
        }}
      />
    </div>
  ) : (
    <Button variant="soft" size="sm" iconLeft={<Icon name="plus" />} onClick={() => setAdding(true)}>New habit</Button>
  )

  return (
    <div className="kit-grid" style={{ gridTemplateColumns: '1.5fr 1fr' }}>
      <Card title="This week" eyebrow="Tap to mark complete" action={headAction}>
        <div className="kit-habits">
          <div />
          {DOW.map((d, i) => <div className="kit-habits__dow" key={i} style={i === todayIndex ? { color: 'var(--accent-text)' } : null}>{d}</div>)}
          {list.map((h) => (
            <React.Fragment key={h.id}>
              <div className="kit-habits__name">
                <span className="kit-habits__ico" style={{ background: `var(--${h.tint}-100)`, color: `var(--${h.tint}-600)` }}><Icon name={h.icon} /></span>
                <div style={{ minWidth: 0 }}>
                  <div className="kit-habits__title">{h.name}</div>
                  <div className="kit-habits__streak"><Icon name="flame" />{h.streak} day streak</div>
                </div>
              </div>
              {(h.days || []).map((done, di) => (
                <div key={di}
                  className={'kit-hcell' + (done ? ' is-done' : '') + (di === todayIndex ? ' is-today' : '')}
                  style={done ? { background: `var(--${h.tint}-600)` } : null}
                  onClick={() => habits.toggle(h.id, di)}>
                  <Icon name="check" />
                </div>
              ))}
            </React.Fragment>
          ))}
        </div>
      </Card>

      <div className="kit-col">
        <Card title="Today" variant="sunken">
          <div style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
            <ProgressRing value={doneToday} max={list.length || 1} size={92} thickness={11} color="green" label={`${doneToday}/${list.length}`} sublabel="done" />
            <div>
              <p className="kit-row__title" style={{ fontSize: 'var(--text-md)' }}>{doneToday === list.length ? 'All done — nice!' : `${list.length - doneToday} to go`}</p>
              <p className="kit-muted" style={{ marginTop: 4 }}>Keep your streaks alive before midnight.</p>
            </div>
          </div>
        </Card>

        <Card title="Streaks">
          <div className="kit-spread" style={{ marginBottom: 14 }}>
            <Stat label="Best streak" value={bestStreak} unit="days" icon={<Icon name="flame" />} />
            <Stat label="This week" value={`${weekPct}%`} trend={diff >= 0 ? 'up' : 'down'} delta={`${diff >= 0 ? '+' : ''}${diff}%`} />
          </div>
          <div className="kit-insight">
            <div className="kit-insight__icon"><Icon name="sparkles" /></div>
            <p>You're most consistent in the <strong>morning</strong>. Want me to stack “Read” right after “Meditate”?</p>
          </div>
        </Card>
      </div>
    </div>
  )
}
