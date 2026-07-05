/* Scuffed OS — Dashboard (home overview).
   Agenda + nutrition rings are live (M3); finance stays sample until Plaid (M6). */
import { Button, Card, IconButton, Badge, Stat, ProgressBar, ProgressRing, Checkbox } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'

export function DashboardScreen({ tasks, onToggleTask, voiceNotes, calendar, nutrition, onNavigate }) {
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
  const txns = [
    { title: 'Whole Foods', sub: 'Groceries · 8:42am', amt: '-$64.20', cat: 'var(--clay-600)' },
    { title: 'Salary', sub: 'Acme Inc · deposit', amt: '+$3,200', cat: 'var(--green-600)', pos: true },
    { title: 'Spotify', sub: 'Subscriptions', amt: '-$11.99', cat: 'var(--plum-600)' },
  ]
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

        <Card eyebrow="Sample data — real bank sync lands with Plaid (M6)" title="Finance snapshot" action={<Badge color="green" dot>On budget</Badge>}>
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
