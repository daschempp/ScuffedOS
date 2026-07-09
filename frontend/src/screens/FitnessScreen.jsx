/* Scuffed OS — Fitness & workout log (live, synced with WHOOP).
   Owns its own state (App.jsx renders <FitnessScreen /> with no props),
   mirroring MemoryScreen's in-component fetch convention. /status drives which
   connection state renders; /today, /workouts, /week feed the connected view.
   Reads come straight from the normalized tables server-side, so the screen
   works while a sync is mid-flight or WHOOP is down — it just shows what's
   landed so far. Tokens never reach the client. */
import React from 'react'
import { Card, Badge, ProgressRing, IconButton, Button } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'
import { api } from '../lib/api.js'
import { NotConnectedCard, NeedsReauthBanner } from '../components/ConnectorEmptyState.jsx'

const EMPTY_FORM = { name: '', sport: '', duration_min: '', strain: '', calories: '', avg_hr: '' }

const localIso = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

/* Green for a positive delta, clay for negative — matches the warm palette.
   Resting HR is the one vital where lower is better, so its sign flips. */
function deltaColor(key, delta) {
  if (delta == null || delta === 0) return 'var(--text-faint)'
  const better = key === 'resting_hr' ? delta < 0 : delta > 0
  return better ? 'var(--green-600)' : 'var(--clay-600)'
}
function fmtDelta(delta) {
  if (delta == null) return ''
  const r = Math.round(delta * 10) / 10
  return (r > 0 ? '+' : r < 0 ? '−' : '') + Math.abs(r)
}

export function FitnessScreen({ onOpenConnectors }) {
  const [status, setStatus] = React.useState(null)   // null = /status not answered yet
  const [today, setToday] = React.useState(null)
  const [workouts, setWorkouts] = React.useState([])
  const [week, setWeek] = React.useState(null)
  const [logging, setLogging] = React.useState(false)
  const [form, setForm] = React.useState(EMPTY_FORM)
  const setField = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

  const refresh = React.useCallback(() => {
    api.oauthStatus().then((s) => { if (s) setStatus(s) }).catch(() => {})
    api.fitnessToday().then((t) => { if (t) setToday(t) }).catch(() => {})
    api.fitnessWorkouts().then((w) => { if (Array.isArray(w)) setWorkouts(w) }).catch(() => {})
    api.fitnessWeek().then((w) => { if (w) setWeek(w) }).catch(() => {})
  }, [])

  React.useEffect(() => { refresh() }, [refresh])

  const whoop = (status?.providers || []).find((p) => p.provider === 'whoop') || null
  const connected = !!whoop
  const needsReauth = whoop?.status === 'needs_reauth'
  // Connected + an account exists, but no day data has landed yet → first sync
  // is still running. has_data===false with a connected account = "Syncing…".
  const syncing = connected && !needsReauth && today != null && today.has_data === false && !whoop?.last_sync_at

  const sync = () => { api.fitnessSync().then(() => refresh()).catch(() => {}) }

  const submitWorkout = () => {
    if (!form.name.trim()) return
    // duration_min/strain/calories/avg_hr are numeric server-side; an empty
    // string would 422 and the .catch would silently drop the workout.
    const payload = {
      name: form.name.trim(),
      started_at: new Date().toISOString(),
      duration_min: Math.round(+form.duration_min) || 0,
    }
    if (form.sport.trim()) payload.sport = form.sport.trim()
    if (form.strain !== '') payload.strain = +form.strain
    if (form.calories !== '') payload.calories = Math.round(+form.calories) || 0
    if (form.avg_hr !== '') payload.avg_hr = Math.round(+form.avg_hr) || 0
    api.logWorkout(payload).then(() => refresh()).catch(() => {})
    setForm(EMPTY_FORM)
    setLogging(false)
  }
  const onFormKey = (e) => {
    if (e.key === 'Enter') submitWorkout()
    else if (e.key === 'Escape') { setForm(EMPTY_FORM); setLogging(false) }
  }
  const removeWorkout = (id) => {
    setWorkouts((ws) => ws.filter((w) => w.id !== id))
    api.deleteWorkout(id).then(() => refresh()).catch(() => {})
  }

  const inputStyle = {
    padding: '8px 11px', borderRadius: 'var(--radius-sm)', background: 'var(--surface-sunken)',
    border: 'none', outline: 'none', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)',
    color: 'var(--text-strong)',
  }

  // —— not connected: shared empty-state, deep-links to Settings › Connectors ——
  if (status && !connected && !needsReauth) {
    return (
      <NotConnectedCard title="Fitness isn’t connected"
        blurb="Connect WHOOP to see recovery, sleep, strain and workouts."
        onOpenConnectors={onOpenConnectors} icon="activity" />
    )
  }

  const recovered = (today?.recovery_pct ?? 0) >= 67
  const eyebrow = whoop?.last_sync_at
    ? `Synced with WHOOP · ${new Date(whoop.last_sync_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`
    : 'Connected with WHOOP'
  const todayIso = localIso(new Date())
  const weekDays = week?.days || Array.from({ length: 7 }, () => ({ date: '', dow: '', strain: 0, frac: 0 }))

  return (
    <div className="kit-stack" style={{ gap: 'var(--gutter)' }}>
      {needsReauth && <NeedsReauthBanner onOpenConnectors={onOpenConnectors} />}

      {syncing && (
        <Card variant="flat" style={{ textAlign: 'center', padding: '48px 24px' }}>
          <div style={{ display: 'inline-flex', width: 56, height: 56, borderRadius: 'var(--radius-lg)', background: 'var(--accent-soft)', color: 'var(--accent-text)', alignItems: 'center', justifyContent: 'center', marginBottom: 14 }}>
            <Icon name="refresh-cw" />
          </div>
          <h3 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-xl)', color: 'var(--text-strong)', margin: '0 0 6px' }}>Syncing…</h3>
          <p className="kit-muted" style={{ maxWidth: 360, margin: '0 auto 18px' }}>Pulling your recovery, sleep and workouts from WHOOP. This usually takes a moment — hang tight.</p>
          <Button variant="secondary" size="sm" iconLeft={<Icon name="refresh-cw" />} onClick={sync}>Check again</Button>
        </Card>
      )}

      {!syncing && (
        <div className="kit-grid" style={{ gridTemplateColumns: '1.3fr 1fr' }}>
          <Card eyebrow={eyebrow} title="Today"
            action={
              <div className="kit-inline" style={{ gap: 8 }}>
                {today?.has_data && <Badge color={recovered ? 'green' : 'honey'} dot>{recovered ? 'Recovered' : 'Take it easy'}</Badge>}
                <IconButton label="Sync now" size="sm" onClick={sync}><Icon name="refresh-cw" /></IconButton>
              </div>
            }>
            {today?.has_data ? (
              <div className="kit-rings" style={{ justifyContent: 'space-around', marginTop: 6 }}>
                <div className="kit-ring-cell"><ProgressRing value={today.recovery_pct ?? 0} max={100} size={108} thickness={12} color="green" label={`${today.recovery_pct ?? 0}%`} sublabel="recovery" /><span className="kit-ring-cell__lab">Recovery</span></div>
                <div className="kit-ring-cell"><ProgressRing value={today.day_strain ?? 0} max={21} size={108} thickness={12} color="sky" label={`${today.day_strain ?? 0}`} sublabel="of 21" /><span className="kit-ring-cell__lab">Day strain</span></div>
                <div className="kit-ring-cell"><ProgressRing value={today.sleep_quality_pct ?? 0} max={100} size={108} thickness={12} color="plum" label={`${today.sleep_quality_pct ?? 0}%`} sublabel="quality" /><span className="kit-ring-cell__lab">Sleep</span></div>
              </div>
            ) : (
              <p className="kit-muted" style={{ marginTop: 6 }}>No data for today yet — it'll appear after the next sync.</p>
            )}
          </Card>
          <Card title="Vitals" action={<IconButton label="History" size="sm"><Icon name="chart-line" /></IconButton>}>
            <div className="kit-statgrid" style={{ marginTop: 4 }}>
              {(today?.vitals || []).map((v) => (
                <div className="kit-statline" key={v.key}>
                  <span className="kit-statline__ico" style={{ background: `var(--${v.tint}-100)`, color: `var(--${v.tint}-600)` }}><Icon name={v.icon} /></span>
                  <div>
                    <div className="kit-statline__lab">{v.label}</div>
                    <div className="kit-statline__val">{v.value ?? '—'}<span style={{ fontSize: 11, color: 'var(--text-faint)' }}> {v.unit}</span>
                      {v.delta != null && <span style={{ fontFamily: 'var(--font-sans)', fontSize: 11, fontWeight: 600, color: deltaColor(v.key, v.delta), marginLeft: 6 }}>{fmtDelta(v.delta)}</span>}
                    </div>
                  </div>
                </div>
              ))}
              {(!today?.vitals || today.vitals.length === 0) && <p className="kit-muted">No vitals yet.</p>}
            </div>
          </Card>
        </div>
      )}

      <div className="kit-grid" style={{ gridTemplateColumns: '1.3fr 1fr' }}>
        <Card title="Workouts" action={<Button variant="soft" size="sm" iconLeft={<Icon name="plus" />} onClick={() => setLogging((v) => !v)}>Log workout</Button>}>
          {logging && (
            <div className="kit-stack" style={{ gap: 8, marginBottom: 12 }}>
              <div className="kit-addrow" style={{ marginTop: 0 }}>
                <Icon name="activity" />
                <input autoFocus placeholder="What did you do?" value={form.name} onChange={setField('name')} onKeyDown={onFormKey} />
              </div>
              <div className="kit-inline" style={{ gap: 8, flexWrap: 'wrap' }}>
                <input placeholder="sport" value={form.sport} onChange={setField('sport')} onKeyDown={onFormKey} style={inputStyle} />
                <input type="number" placeholder="min" value={form.duration_min} onChange={setField('duration_min')} onKeyDown={onFormKey} style={{ ...inputStyle, width: 80 }} />
                <input type="number" placeholder="strain" value={form.strain} onChange={setField('strain')} onKeyDown={onFormKey} style={{ ...inputStyle, width: 90 }} />
                <input type="number" placeholder="cal" value={form.calories} onChange={setField('calories')} onKeyDown={onFormKey} style={{ ...inputStyle, width: 80 }} />
                <input type="number" placeholder="avg bpm" value={form.avg_hr} onChange={setField('avg_hr')} onKeyDown={onFormKey} style={{ ...inputStyle, width: 90 }} />
                <Button variant="soft" size="sm" onClick={submitWorkout}>Add</Button>
              </div>
            </div>
          )}
          {workouts.map((w) => (
            <div className="kit-row" key={w.id}>
              <span className="kit-workout__ico" style={{ background: `var(--${w.tint}-100)`, color: `var(--${w.tint}-600)` }}><Icon name={w.icon} /></span>
              <div className="kit-row__main">
                <p className="kit-row__title">{w.name}{w.source === 'manual' && <span className="kit-muted" style={{ fontWeight: 400 }}> · manual</span>}</p>
                <p className="kit-row__sub">{[w.when, w.duration_min ? `${w.duration_min} min` : null, w.calories != null ? `${w.calories} cal` : null, w.avg_hr != null ? `${w.avg_hr} bpm` : null].filter(Boolean).join(' · ')}</p>
              </div>
              {w.strain != null && <Badge color="sky">{w.strain}</Badge>}
              <IconButton label="Delete" variant="ghost" size="sm" onClick={() => removeWorkout(w.id)}><Icon name="trash-2" /></IconButton>
            </div>
          ))}
          {workouts.length === 0 && !logging && <p className="kit-muted">No workouts logged yet.</p>}
        </Card>
        <Card title="Weekly strain" variant="sunken" action={<span className="kit-muted">avg {week?.avg_strain ?? 0}</span>}>
          <div className="kit-chart">
            {weekDays.map((c, i) => (
              <div className="kit-chart__col" key={i}>
                <div className={'kit-chart__bar' + (c.date && c.date === todayIso ? ' kit-chart__bar--hi' : '')} style={{ height: (Math.max(0, Math.min(1, c.frac || 0)) * 100) + '%' }} />
                <span className="kit-chart__lab">{c.dow}</span>
              </div>
            ))}
          </div>
          <div className="kit-insight" style={{ marginTop: 14 }}>
            <div className="kit-insight__icon"><Icon name="sparkles" /></div>
            <p>{recovered
              ? <>Recovery is high — a good day for a <strong>hard session</strong>. Want me to schedule one?</>
              : <>Recovery is on the lower side — consider an <strong>easy day</strong>.</>}</p>
          </div>
        </Card>
      </div>
    </div>
  )
}
