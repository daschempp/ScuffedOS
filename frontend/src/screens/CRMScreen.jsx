/* Scuffed OS — Personal CRM */
import { Card, Avatar, Badge, IconButton, Button } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'

export function CRMScreen() {
  const Strength = ({ n }) => (
    <span className="kit-strength">{[0, 1, 2, 3, 4].map((i) => <i key={i} className={i < n ? 'on' : ''} />)}</span>
  )
  const people = [
    { name: 'Priya Anand', rel: 'Colleague', relColor: 'sky', last: 'Talked 2 days ago', strength: 4, tint: 'sky' },
    { name: 'Lila Rivera', rel: 'Family', relColor: 'plum', last: 'Called 1 week ago', strength: 5, tint: 'plum' },
    { name: 'Jordan Lee', rel: 'Friend', relColor: 'green', last: '3 weeks ago', due: true, strength: 3, tint: 'green' },
    { name: 'Alex Mehta', rel: 'Friend', relColor: 'green', last: '2 months ago', over: true, strength: 2, tint: 'honey' },
    { name: 'Dr. Chen', rel: 'Network', relColor: 'neutral', last: '5 months ago', over: true, strength: 1, tint: 'clay' },
  ]
  const reachOut = [
    { name: 'Jordan Lee', why: 'You usually catch up every 2 weeks', tint: 'green' },
    { name: 'Alex Mehta', why: "It's been 2 months", tint: 'honey' },
  ]
  const upcoming = [
    { name: "Lila's birthday", when: 'Jun 14 · in 5 days', icon: 'cake', tint: 'plum' },
    { name: 'Anniversary with Jo', when: 'Jun 20 · in 11 days', icon: 'heart', tint: 'clay' },
    { name: 'Priya — work-iversary', when: 'Jun 28', icon: 'party-popper', tint: 'sky' },
  ]
  return (
    <div className="kit-grid" style={{ gridTemplateColumns: '1.5fr 1fr' }}>
      <Card title="People" eyebrow="142 contacts" action={
        <div className="kit-search" style={{ width: 180 }}><Icon name="search" /><input placeholder="Search people" /></div>
      }>
        {people.map((p, i) => (
          <div className="kit-person" key={i}>
            <Avatar name={p.name} tint={p.tint} />
            <div className="kit-person__main">
              <p className="kit-person__name">{p.name} <Badge color={p.relColor}>{p.rel}</Badge></p>
              <p className="kit-person__sub" style={p.over ? { color: 'var(--clay-600)' } : null}>{p.last}</p>
            </div>
            <Strength n={p.strength} />
            <IconButton label="Draft a note"><Icon name="pen-line" /></IconButton>
          </div>
        ))}
      </Card>

      <div className="kit-col">
        <Card title="Reach out" eyebrow="Assistant nudges" action={<Badge color="honey" dot>2 due</Badge>}>
          <div className="kit-stack">
            {reachOut.map((r, i) => (
              <div className="kit-memory" key={i}>
                <div className="kit-memory__top">
                  <Avatar name={r.name} tint={r.tint} size="sm" />
                  <span className="kit-row__title" style={{ fontSize: 'var(--text-sm)' }}>{r.name}</span>
                </div>
                <p style={{ margin: 0, fontSize: 'var(--text-sm)', color: 'var(--text-muted)' }}>{r.why}</p>
                <div className="kit-inline">
                  <Button variant="soft" size="sm" iconLeft={<Icon name="sparkles" />}>Draft a hello</Button>
                  <Button variant="ghost" size="sm">Snooze</Button>
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card title="Upcoming" variant="sunken">
          {upcoming.map((u, i) => (
            <div className="kit-row" key={i}>
              <span className="kit-workout__ico" style={{ width: 36, height: 36, background: `var(--${u.tint}-100)`, color: `var(--${u.tint}-600)` }}><Icon name={u.icon} /></span>
              <div className="kit-row__main">
                <p className="kit-row__title">{u.name}</p>
                <p className="kit-row__sub">{u.when}</p>
              </div>
            </div>
          ))}
        </Card>
      </div>
    </div>
  )
}
