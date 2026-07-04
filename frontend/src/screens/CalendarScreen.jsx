/* Scuffed OS — Calendar (week view), backed by the real API via useCalendar()
   (passed down from App.jsx as the `calendar` prop). Renders an empty grid
   when the backend is down — never crashes on missing data. */
import React from 'react'
import { Card, IconButton, Button, Badge } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'

const DEFAULT_START = 8, DEFAULT_END = 18, ROW = 52 // the prototype's 8:00 → 18:00

export function CalendarScreen({ calendar }) {
  const [view, setView] = React.useState('Week')
  const {
    days = [], events = [], upNext = [], monthLabel = '', monthDays = [],
    goPrev = () => {}, goNext = () => {}, goToday = () => {},
  } = calendar || {}

  // Collect the week's occurrences first: the visible hour window grows to
  // fit them, so a 7pm dinner or 6am run is never silently dropped.
  const placed = []
  for (const o of events) {
    if (!o || !o.start) continue
    const sd = new Date(o.start)
    if (isNaN(sd)) continue
    const ed = o.end ? new Date(o.end) : null
    let s = sd.getHours() + sd.getMinutes() / 60
    let e = ed && !isNaN(ed) ? ed.getHours() + ed.getMinutes() / 60 : s + 1
    if (e <= s) e = s + 0.5
    placed.push({ ...o, s, e, col: (sd.getDay() + 6) % 7 })
  }
  const START = Math.max(0, Math.min(DEFAULT_START, ...placed.map((p) => Math.floor(p.s))))
  const END = Math.min(24, Math.max(DEFAULT_END, ...placed.map((p) => Math.ceil(p.e))))
  const hours = Array.from({ length: END - START }, (_, i) => START + i)

  const eventsByCol = Array.from({ length: 7 }, () => [])
  for (const p of placed) {
    eventsByCol[p.col].push({ ...p, s: Math.max(START, p.s), e: Math.min(END, p.e) })
  }

  const monthName = monthLabel.split(' ')[0] || ''

  return (
    <div className="kit-grid" style={{ gridTemplateColumns: '1fr 300px' }}>
      <Card>
        <div className="kit-cal__toolbar">
          <span className="kit-cal__month">{monthLabel}</span>
          <IconButton label="Previous" size="sm" onClick={goPrev}><Icon name="chevron-left" /></IconButton>
          <IconButton label="Next" size="sm" onClick={goNext}><Icon name="chevron-right" /></IconButton>
          <Button variant="secondary" size="sm" onClick={goToday}>Today</Button>
          <div className="kit-cal__seg">
            {['Day', 'Week', 'Month'].map((v) => (
              <button key={v} className={view === v ? 'is-on' : ''} onClick={() => setView(v)}>{v}</button>
            ))}
          </div>
        </div>

        <div className="kit-week">
          <div className="kit-week__corner" />
          {days.map((d, i) => (
            <div className="kit-week__dayhead" key={i}>
              <div className="kit-week__dow">{d.dow}</div>
              <div className={'kit-week__date' + (d.isToday ? ' is-today' : '')}>{d.dayNum}</div>
            </div>
          ))}

          <div className="kit-week__body">
            <div className="kit-week__hours">
              {hours.map((h) => (
                <div className="kit-week__hour" key={h}>{h > 12 ? (h - 12) + 'p' : h + 'a'}</div>
              ))}
            </div>
            {days.map((d, i) => (
              <div className={'kit-week__col' + (d.isToday ? ' is-today' : '')} key={i}>
                {hours.map((h) => <div className="kit-week__row" key={h} />)}
                {eventsByCol[i].map((ev) => (
                  <div key={ev.id + '-' + ev.start} className={'kit-event kit-ev--' + (ev.tint || 'green')}
                    style={{ top: (ev.s - START) * ROW + 1, height: (ev.e - ev.s) * ROW - 3 }}>
                    <b>{ev.title}</b>
                    <span>{ev.at}{ev.source === 'moodle' ? ' · Moodle' : ''}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      </Card>

      <div className="kit-col">
        <Card title={monthName} action={<div style={{ display: 'flex', gap: 2 }}><IconButton label="Previous" size="sm" onClick={goPrev}><Icon name="chevron-left" /></IconButton><IconButton label="Next" size="sm" onClick={goNext}><Icon name="chevron-right" /></IconButton></div>}>
          <div className="kit-month">
            {['M', 'T', 'W', 'T', 'F', 'S', 'S'].map((d, i) => <div className="kit-month__dow" key={i}>{d}</div>)}
            {monthDays.map((m, i) => (
              m.d == null
                ? <div key={i} className="kit-month__day" />
                : <div key={i} className={'kit-month__day' + (m.today ? ' is-today' : '') + (m.dot ? ' has-dot' : '')}>{m.d}</div>
            ))}
          </div>
        </Card>

        <Card title="Up next" variant="sunken">
          <div className="kit-stack" style={{ gap: 2 }}>
            {upNext.length === 0 && (
              <p className="kit-row__sub" style={{ fontSize: 12 }}>Nothing coming up</p>
            )}
            {upNext.map((u, i) => (
              <div className="kit-listrow" key={i}>
                <span className="kit-listrow__dot" style={{ background: `var(--${u.tint || 'green'}-600)` }} />
                <div className="kit-row__main">
                  <p className="kit-row__title" style={{ fontSize: 'var(--text-sm)' }}>{u.title}</p>
                  <p className="kit-row__sub" style={{ fontSize: 12 }}>{u.when}</p>
                </div>
                {u.source === 'moodle' && <Badge color="plum">Moodle</Badge>}
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}
