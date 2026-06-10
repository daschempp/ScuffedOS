/* Scuffed OS — Calendar (week view) */
import React from 'react'
import { Card, IconButton, Button } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'

export function CalendarScreen() {
  const [view, setView] = React.useState('Week')
  const days = [
    { dow: 'Mon', date: 7 }, { dow: 'Tue', date: 8, today: true }, { dow: 'Wed', date: 9 },
    { dow: 'Thu', date: 10 }, { dow: 'Fri', date: 11 }, { dow: 'Sat', date: 12 }, { dow: 'Sun', date: 13 },
  ]
  const START = 8, END = 18, ROW = 52 // 8:00 → 18:00
  const hours = Array.from({ length: END - START }, (_, i) => START + i)
  // events keyed by day index
  const events = {
    0: [{ t: 'Design review', s: 10, e: 11, c: 'green', at: '10:00' }, { t: 'Gym', s: 17, e: 18, c: 'sky', at: '5:00pm' }],
    1: [{ t: 'Deep work — Q3 plan', s: 9, e: 10.5, c: 'green', at: '9:00' }, { t: 'Design standup', s: 11.5, e: 12, c: 'plum', at: '11:30' }, { t: 'Lunch', s: 13, e: 13.5, c: 'honey', at: '1:00pm' }, { t: 'Dentist', s: 16, e: 17, c: 'clay', at: '4:00pm' }],
    2: [{ t: '1:1 with Priya', s: 14, e: 14.75, c: 'plum', at: '2:00pm' }],
    3: [{ t: 'Lighthouse sync', s: 10, e: 11.5, c: 'green', at: '10:00' }, { t: 'Meal prep', s: 16, e: 17, c: 'honey', at: '4:00pm' }],
    4: [{ t: 'Focus block', s: 9, e: 11, c: 'green', at: '9:00' }, { t: 'Coffee w/ Al', s: 15, e: 15.5, c: 'sky', at: '3:00pm' }],
    5: [{ t: 'Farmers market', s: 9, e: 10, c: 'honey', at: '9:00' }],
    6: [{ t: 'Morning run', s: 8, e: 9, c: 'sky', at: '8:00' }],
  }
  const monthDays = []
  // June 2026 starts on Monday June 1. Show Mon-start grid.
  for (let d = 1; d <= 30; d++) monthDays.push({ d, today: d === 8, dot: [7, 8, 9, 10, 11, 12].includes(d) })
  const upNext = [
    { t: 'Deep work — Q3 plan', when: 'Now · 9:00–10:30', c: 'green' },
    { t: 'Design standup', when: '11:30am · Google Meet', c: 'plum' },
    { t: 'Lunch — log it!', when: '1:00pm', c: 'honey' },
    { t: 'Dentist', when: '4:00pm · Oak Street', c: 'clay' },
  ]

  return (
    <div className="kit-grid" style={{ gridTemplateColumns: '1fr 300px' }}>
      <Card>
        <div className="kit-cal__toolbar">
          <span className="kit-cal__month">June 2026</span>
          <IconButton label="Previous" size="sm"><Icon name="chevron-left" /></IconButton>
          <IconButton label="Next" size="sm"><Icon name="chevron-right" /></IconButton>
          <Button variant="secondary" size="sm">Today</Button>
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
              <div className={'kit-week__date' + (d.today ? ' is-today' : '')}>{d.date}</div>
            </div>
          ))}

          <div className="kit-week__body">
            <div className="kit-week__hours">
              {hours.map((h) => (
                <div className="kit-week__hour" key={h}>{h > 12 ? (h - 12) + 'p' : h + 'a'}</div>
              ))}
            </div>
            {days.map((d, i) => (
              <div className={'kit-week__col' + (d.today ? ' is-today' : '')} key={i}>
                {hours.map((h) => <div className="kit-week__row" key={h} />)}
                {(events[i] || []).map((ev, j) => (
                  <div key={j} className={'kit-event kit-ev--' + ev.c}
                    style={{ top: (ev.s - START) * ROW + 1, height: (ev.e - ev.s) * ROW - 3 }}>
                    <b>{ev.t}</b><span>{ev.at}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      </Card>

      <div className="kit-col">
        <Card title="June" action={<div style={{ display: 'flex', gap: 2 }}><IconButton label="Previous" size="sm"><Icon name="chevron-left" /></IconButton><IconButton label="Next" size="sm"><Icon name="chevron-right" /></IconButton></div>}>
          <div className="kit-month">
            {['M', 'T', 'W', 'T', 'F', 'S', 'S'].map((d, i) => <div className="kit-month__dow" key={i}>{d}</div>)}
            {monthDays.map((m) => (
              <div key={m.d} className={'kit-month__day' + (m.today ? ' is-today' : '') + (m.dot ? ' has-dot' : '')}>{m.d}</div>
            ))}
          </div>
        </Card>

        <Card title="Up next" variant="sunken">
          <div className="kit-stack" style={{ gap: 2 }}>
            {upNext.map((u, i) => (
              <div className="kit-listrow" key={i}>
                <span className="kit-listrow__dot" style={{ background: `var(--${u.c}-600)` }} />
                <div className="kit-row__main">
                  <p className="kit-row__title" style={{ fontSize: 'var(--text-sm)' }}>{u.t}</p>
                  <p className="kit-row__sub" style={{ fontSize: 12 }}>{u.when}</p>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}
