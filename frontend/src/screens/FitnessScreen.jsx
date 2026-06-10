/* Scuffed OS — Fitness & workout log (syncs with Whoop) */
import { Card, Badge, ProgressRing, IconButton, Button } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'

export function FitnessScreen() {
  const vitals = [
    { lab: 'HRV', val: '68', unit: 'ms', icon: 'activity', tint: 'green', delta: '+6' },
    { lab: 'Resting HR', val: '52', unit: 'bpm', icon: 'heart', tint: 'clay', delta: '−2' },
    { lab: 'Respiratory', val: '14.2', unit: 'rpm', icon: 'wind', tint: 'sky', delta: '' },
    { lab: 'Sleep', val: '7:38', unit: 'hrs', icon: 'moon', tint: 'plum', delta: '+0:24' },
  ]
  const workouts = [
    { name: 'Morning run', when: 'Today · 6:10am', icon: 'footprints', tint: 'green', strain: '9.4', dur: '32 min', cal: '318', hr: '148' },
    { name: 'Strength — push', when: 'Yesterday · 7:05pm', icon: 'dumbbell', tint: 'clay', strain: '11.2', dur: '48 min', cal: '286', hr: '121' },
    { name: 'Cycling', when: 'Mon · 6:30am', icon: 'bike', tint: 'sky', strain: '13.1', dur: '1:05', cal: '540', hr: '139' },
    { name: 'Yoga & mobility', when: 'Sun · 8:00am', icon: 'flower-2', tint: 'plum', strain: '4.8', dur: '25 min', cal: '96', hr: '92' },
  ]
  const week = [
    { d: 'M', v: 0.62 }, { d: 'T', v: 0.74 }, { d: 'W', v: 0.45 }, { d: 'T', v: 0.83 },
    { d: 'F', v: 0.68 }, { d: 'S', v: 0.91 }, { d: 'S', v: 0.5, hi: true },
  ]
  return (
    <div className="kit-stack" style={{ gap: 'var(--gutter)' }}>
      <div className="kit-grid" style={{ gridTemplateColumns: '1.3fr 1fr' }}>
        <Card eyebrow="Synced with Whoop · 6:42am" title="Today" action={<Badge color="green" dot>Recovered</Badge>}>
          <div className="kit-rings" style={{ justifyContent: 'space-around', marginTop: 6 }}>
            <div className="kit-ring-cell"><ProgressRing value={82} max={100} size={108} thickness={12} color="green" label="82%" sublabel="recovery" /><span className="kit-ring-cell__lab">Recovery</span></div>
            <div className="kit-ring-cell"><ProgressRing value={14.2} max={21} size={108} thickness={12} color="sky" label="14.2" sublabel="of 21" /><span className="kit-ring-cell__lab">Day strain</span></div>
            <div className="kit-ring-cell"><ProgressRing value={91} max={100} size={108} thickness={12} color="plum" label="91%" sublabel="quality" /><span className="kit-ring-cell__lab">Sleep</span></div>
          </div>
        </Card>
        <Card title="Vitals" action={<IconButton label="History" size="sm"><Icon name="chart-line" /></IconButton>}>
          <div className="kit-statgrid" style={{ marginTop: 4 }}>
            {vitals.map((v, i) => (
              <div className="kit-statline" key={i}>
                <span className="kit-statline__ico" style={{ background: `var(--${v.tint}-100)`, color: `var(--${v.tint}-600)` }}><Icon name={v.icon} /></span>
                <div>
                  <div className="kit-statline__lab">{v.lab}</div>
                  <div className="kit-statline__val">{v.val}<span style={{ fontSize: 11, color: 'var(--text-faint)' }}> {v.unit}</span>
                    {v.delta && <span style={{ fontFamily: 'var(--font-sans)', fontSize: 11, fontWeight: 600, color: 'var(--green-600)', marginLeft: 6 }}>{v.delta}</span>}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <div className="kit-grid" style={{ gridTemplateColumns: '1.3fr 1fr' }}>
        <Card title="Workouts" action={<Button variant="soft" size="sm" iconLeft={<Icon name="plus" />}>Log workout</Button>}>
          {workouts.map((w, i) => (
            <div className="kit-row" key={i}>
              <span className="kit-workout__ico" style={{ background: `var(--${w.tint}-100)`, color: `var(--${w.tint}-600)` }}><Icon name={w.icon} /></span>
              <div className="kit-row__main">
                <p className="kit-row__title">{w.name}</p>
                <p className="kit-row__sub">{w.when} · {w.dur} · {w.cal} cal · {w.hr} bpm</p>
              </div>
              <Badge color="sky">{w.strain}</Badge>
            </div>
          ))}
        </Card>
        <Card title="Weekly strain" variant="sunken" action={<span className="kit-muted">avg 8.9</span>}>
          <div className="kit-chart">
            {week.map((c, i) => (
              <div className="kit-chart__col" key={i}>
                <div className={'kit-chart__bar' + (c.hi ? ' kit-chart__bar--hi' : '')} style={{ height: (c.v * 100) + '%' }} />
                <span className="kit-chart__lab">{c.d}</span>
              </div>
            ))}
          </div>
          <div className="kit-insight" style={{ marginTop: 14 }}>
            <div className="kit-insight__icon"><Icon name="sparkles" /></div>
            <p>Recovery is high — a good day for a <strong>hard session</strong>. Want me to schedule one?</p>
          </div>
        </Card>
      </div>
    </div>
  )
}
