/* Scuffed OS — Dashboard (home overview) */
import { Card, IconButton, Badge, Stat, ProgressBar, ProgressRing, Checkbox } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'

export function DashboardScreen({ tasks, onToggleTask, voiceNotes }) {
  const agenda = [
    { time: '09:00', title: 'Deep work — Q3 planning', meta: 'Focus block', active: true },
    { time: '11:30', title: 'Standup with design', meta: 'Google Meet', icon: 'video', active: true },
    { time: '13:00', title: 'Lunch — log it!', meta: 'Assistant reminder', icon: 'utensils', active: false },
    { time: '16:00', title: 'Dentist', meta: '12 Oak Street', icon: 'map-pin', active: false },
  ]
  const txns = [
    { title: 'Whole Foods', sub: 'Groceries · 8:42am', amt: '-$64.20', cat: 'var(--clay-600)' },
    { title: 'Salary', sub: 'Acme Inc · deposit', amt: '+$3,200', cat: 'var(--green-600)', pos: true },
    { title: 'Spotify', sub: 'Subscriptions', amt: '-$11.99', cat: 'var(--plum-600)' },
  ]
  return (
    <div className="kit-grid kit-grid--dash">
      <div className="kit-col">
        <Card eyebrow="Tuesday · June 8" title="Today's agenda" action={<IconButton label="Open calendar" size="sm"><Icon name="arrow-up-right" /></IconButton>}>
          <div className="kit-agenda">
            {agenda.map((a, i) => (
              <div key={i} className={`kit-agenda__item ${a.active ? '' : 'kit-agenda__item--muted'}`}>
                <div className="kit-agenda__time">{a.time}</div>
                <div className="kit-agenda__body">
                  <p className="kit-agenda__title">{a.title}</p>
                  <p className="kit-agenda__meta">{a.icon && <Icon name={a.icon} />}{a.meta}</p>
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card title="Finance snapshot" action={<Badge color="green" dot>On budget</Badge>}>
          <div className="kit-spread" style={{ marginBottom: 18 }}>
            <Stat label="Balance" value="$4,820" delta="+3.2% this week" trend="up" />
            <div style={{ flex: 1, maxWidth: 230 }}>
              <ProgressBar label="June spending" meta="$1,840 / $2,400" value={1840} max={2400} color="clay" />
            </div>
          </div>
          {txns.map((t, i) => (
            <div className="kit-row" key={i}>
              <span className="kit-cat" style={{ background: t.cat }} />
              <div className="kit-row__main">
                <p className="kit-row__title">{t.title}</p>
                <p className="kit-row__sub">{t.sub}</p>
              </div>
              <span className={`kit-row__amt ${t.pos ? 'kit-amt--pos' : 'kit-amt--neg'}`}>{t.amt}</span>
            </div>
          ))}
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
            {tasks.map((t) => (
              <div key={t.id} style={{ padding: '7px 0' }}>
                <Checkbox checked={t.done} strikeWhenChecked label={t.label} onChange={() => onToggleTask(t.id)} />
              </div>
            ))}
          </div>
        </Card>

        <Card title="Nutrition" variant="sunken">
          <div className="kit-rings">
            <div className="kit-ring-cell"><ProgressRing value={1840} max={2100} size={78} color="green" label="1840" sublabel="kcal" /><span className="kit-ring-cell__lab">Calories</span></div>
            <div className="kit-ring-cell"><ProgressRing value={138} max={160} size={78} color="clay" label="138g" sublabel="protein" /><span className="kit-ring-cell__lab">Protein</span></div>
            <div className="kit-ring-cell"><ProgressRing value={5} max={8} size={78} color="sky" label="5/8" sublabel="cups" /><span className="kit-ring-cell__lab">Water</span></div>
          </div>
        </Card>
      </div>
    </div>
  )
}
