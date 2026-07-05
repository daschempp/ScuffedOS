/* Scuffed OS — School (live, synced with NC State WolfWare Moodle).
   Owns its own state (App.jsx renders <SchoolScreen /> with no props),
   mirroring EmailScreen's in-component fetch convention. /api/oauth/status
   drives which connection state renders; the five /api/moodle/* reads feed a
   course list + deadline timeline + grades + announcements + notifications.
   Every read comes straight from the moodle_* tables server-side (never a
   live Moodle call), so it works while a sync is mid-flight or Moodle is
   down — it shows what's landed. Read-only this slice: no submit, forum
   post, or message send. Moodle uses a static per-user wstoken (not an OAuth
   code exchange), so connecting is a one-time token paste; the token lives
   server-side only and never reaches the client again. Announcement/
   notification text is rendered as plain text (no dangerouslySetInnerHTML) —
   the backend already strips HTML. */
import React from 'react'
import { Card, Badge, Button } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'
import { api } from '../lib/api.js'

export function SchoolScreen() {
  const [status, setStatus] = React.useState(null)          // null = /status not answered yet
  const [courses, setCourses] = React.useState(null)        // null = not loaded
  const [deadlines, setDeadlines] = React.useState(null)
  const [grades, setGrades] = React.useState(null)
  const [announcements, setAnnouncements] = React.useState(null)
  const [notifications, setNotifications] = React.useState(null)
  const [selCourse, setSelCourse] = React.useState(null)    // selected course_id (string) for the grades pane
  const [token, setToken] = React.useState('')              // wstoken paste field (connect form)
  const [connectError, setConnectError] = React.useState('')

  const refresh = React.useCallback(() => {
    api.oauthStatus().then((s) => { if (s) setStatus(s) }).catch(() => {})
    api.moodleCourses().then((c) => { if (c) setCourses(c) }).catch(() => {})
    api.moodleDeadlines().then((d) => { if (d) setDeadlines(d) }).catch(() => {})
    api.moodleGrades().then((g) => { if (g) setGrades(g) }).catch(() => {})
    api.moodleAnnouncements().then((a) => { if (a) setAnnouncements(a) }).catch(() => {})
    api.moodleNotifications().then((n) => { if (n) setNotifications(n) }).catch(() => {})
  }, [])

  React.useEffect(() => { refresh() }, [refresh])

  const moodle = (status?.providers || []).find((p) => p.provider === 'moodle') || null
  const connected = !!moodle
  const needsReauth = moodle?.status === 'needs_reauth'
  // Connected, no reauth, nothing has landed yet, and Moodle has never synced
  // → the first backfill is still running (mirrors EmailScreen's pre-first-
  // tick state: moodle_sync always stamps last_sync_at, so once the first
  // tick completes a genuinely-empty account shows the normal panes).
  const noData = (courses?.length || 0) === 0 && (deadlines?.length || 0) === 0
  const syncing = connected && !needsReauth && courses != null && noData && !moodle?.last_sync_at

  // Keep the grades pane pointed at a valid course once courses land.
  React.useEffect(() => {
    const list = courses || []
    if (list.length === 0) { setSelCourse(null); return }
    if (selCourse == null || !list.some((c) => c.source_id === selCourse)) setSelCourse(list[0].source_id)
  }, [courses, selCourse])

  const connect = () => {
    if (!token.trim()) { setConnectError('Paste your Moodle security key first.'); return }
    setConnectError('')
    api.moodleConnect({ token: token.trim() })
      .then(() => { setToken(''); refresh() })
      .catch(() => setConnectError("Moodle rejected that key — double-check you copied the whole value."))
  }
  const sync = () => { api.moodleSync().then(() => refresh()).catch(() => {}) }

  const courseName = (courseId) => {
    const c = (courses || []).find((x) => x.source_id === courseId)
    return c ? (c.shortname || c.fullname) : courseId
  }

  // —— not connected: paste-field connect card ——
  if (status && !connected && !needsReauth) {
    return (
      <Card variant="flat" style={{ maxWidth: 560, margin: '0 auto', padding: '40px 28px' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ display: 'inline-flex', width: 56, height: 56, borderRadius: 'var(--radius-lg)', background: 'var(--accent-soft)', color: 'var(--accent-text)', alignItems: 'center', justifyContent: 'center', marginBottom: 14 }}>
            <Icon name="graduation-cap" />
          </div>
          <h3 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-xl)', color: 'var(--text-strong)', margin: '0 0 6px' }}>Connect Moodle</h3>
          <p className="kit-muted" style={{ maxWidth: 420, margin: '0 auto 18px' }}>Sync your WolfWare courses, deadlines and grades into Scuffed OS. Read-only — your security key stays server-side and message bodies are never stored.</p>
        </div>
        <div className="kit-stack" style={{ gap: 10 }}>
          <input
            className="kit-input"
            placeholder="Paste your Moodle security key…"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && connect()}
            style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-md)', border: '1px solid var(--paper-300)', fontFamily: 'var(--font-mono, monospace)', fontSize: 'var(--text-sm)' }}
          />
          {connectError && <p className="kit-muted" style={{ color: 'var(--clay-600)' }}>{connectError}</p>}
          <Button variant="primary" fullWidth iconLeft={<Icon name="graduation-cap" />} onClick={connect}>Connect Moodle</Button>
        </div>
        <div className="kit-divider" style={{ margin: '18px 0 12px' }} />
        <p className="sa-card__eyebrow" style={{ margin: '0 0 6px' }}>Where do I find my security key?</p>
        <ol className="kit-muted" style={{ margin: 0, paddingLeft: 18, fontSize: 'var(--text-sm)', lineHeight: 1.7 }}>
          <li>Sign in to WolfWare Moodle in your browser.</li>
          <li>Open <strong>Preferences → Security keys</strong> (under your profile menu).</li>
          <li>Copy the key for the <strong>Moodle mobile web service</strong>.</li>
          <li>Paste it above and press Connect.</li>
        </ol>
      </Card>
    )
  }

  const eyebrow = moodle?.last_sync_at
    ? `Synced · ${new Date(moodle.last_sync_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`
    : 'Connected'
  // Course drill-down: the selected course drives the whole detail column.
  const sel = (courses || []).find((c) => c.source_id === selCourse) || null
  const courseDeadlines = (deadlines || []).filter((d) => d.course_id === selCourse)
  const selGrades = (grades || []).filter((g) => g.course_id === selCourse)
  const courseTotal = selGrades.find((g) => g.item_type === 'course') || null
  const courseItems = selGrades.filter((g) => g.item_type !== 'course' && g.item_name && g.item_name.trim())
  const courseAnns = (announcements || []).filter((a) => a.course_id === selCourse)

  return (
    <div className="kit-stack" style={{ gap: 'var(--gutter)' }}>
      {needsReauth && (
        <Card variant="flat" style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <span className="kit-statline__ico" style={{ background: 'var(--clay-100)', color: 'var(--clay-600)' }}><Icon name="alert-triangle" /></span>
          <div style={{ flex: 1 }}>
            <p className="kit-row__title">Moodle needs to be reconnected</p>
            <p className="kit-muted">Your security key expired or was revoked. Paste a fresh key to resume syncing your courses.</p>
          </div>
        </Card>
      )}

      {needsReauth && (
        <Card variant="flat" style={{ maxWidth: 560, padding: '20px 24px' }}>
          <p className="sa-card__eyebrow" style={{ margin: '0 0 8px' }}>Reconnect Moodle</p>
          <div className="kit-stack" style={{ gap: 10 }}>
            <input
              className="kit-input"
              placeholder="Paste your Moodle security key…"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && connect()}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-md)', border: '1px solid var(--paper-300)', fontFamily: 'var(--font-mono, monospace)', fontSize: 'var(--text-sm)' }}
            />
            {connectError && <p className="kit-muted" style={{ color: 'var(--clay-600)' }}>{connectError}</p>}
            <Button variant="primary" size="sm" onClick={connect}>Reconnect</Button>
          </div>
        </Card>
      )}

      {syncing && (
        <Card variant="flat" style={{ textAlign: 'center', padding: '48px 24px' }}>
          <div style={{ display: 'inline-flex', width: 56, height: 56, borderRadius: 'var(--radius-lg)', background: 'var(--accent-soft)', color: 'var(--accent-text)', alignItems: 'center', justifyContent: 'center', marginBottom: 14 }}>
            <Icon name="refresh-cw" />
          </div>
          <h3 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-xl)', color: 'var(--text-strong)', margin: '0 0 6px' }}>Syncing…</h3>
          <p className="kit-muted" style={{ maxWidth: 380, margin: '0 auto 18px' }}>Pulling your courses, deadlines and grades from Moodle. This usually takes a moment — hang tight.</p>
          <Button variant="secondary" size="sm" iconLeft={<Icon name="refresh-cw" />} onClick={sync}>Check again</Button>
        </Card>
      )}

      {!syncing && !needsReauth && (
        <div className="kit-stack" style={{ gap: 14 }}>
          {/* course tabs + sync */}
          <div className="kit-inline" style={{ flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
            {(courses || []).map((c) => {
              const active = c.source_id === selCourse
              return (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => setSelCourse(c.source_id)}
                  style={{
                    cursor: 'pointer',
                    borderRadius: 999,
                    padding: '6px 14px',
                    fontFamily: 'inherit',
                    fontSize: 'var(--text-sm)',
                    background: active ? 'var(--accent-soft)' : 'transparent',
                    color: active ? 'var(--accent-text)' : 'var(--text-strong)',
                    border: active ? '1px solid transparent' : '1px solid var(--paper-300)',
                  }}
                >
                  {c.shortname || c.fullname}
                </button>
              )
            })}
            <span className="kit-inline" style={{ marginLeft: 'auto', gap: 8, alignItems: 'center' }}>
              <span className="kit-muted" style={{ fontSize: 12 }}>{eyebrow}</span>
              <Button variant="soft" size="sm" iconLeft={<Icon name="refresh-cw" />} onClick={sync}>Sync</Button>
            </span>
          </div>

          {(courses || []).length === 0 && (
            <Card><p className="kit-muted">No courses yet — press Sync to pull your enrollment.</p></Card>
          )}

          {sel && (
            <div className="kit-grid" style={{ gridTemplateColumns: '1.7fr 1fr' }}>
              {/* selected-course detail */}
              <Card
                title={sel.shortname || sel.fullname}
                eyebrow={`${sel.fullname}${sel.progress != null ? ` · ${Math.round(sel.progress)}% complete` : ''}`}
              >
                <p className="sa-card__eyebrow" style={{ margin: '14px 0 6px' }}>Due in this course</p>
                {courseDeadlines.length === 0 && <p className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>Nothing due in the next 60 days.</p>}
                <div className="kit-stack" style={{ gap: 0 }}>
                  {courseDeadlines.map((d) => (
                    <div className="kit-listrow" key={d.id} style={d.overdue ? { background: 'var(--clay-100)', borderRadius: 'var(--radius-md)' } : undefined}>
                      <span className="kit-listrow__dot" style={{ background: d.overdue ? 'var(--clay-600)' : 'var(--plum-600)' }} />
                      <div className="kit-row__main">
                        <p className="kit-row__title" style={{ fontSize: 'var(--text-sm)' }}>{d.name}</p>
                        <p className="kit-row__sub" style={{ fontSize: 12 }}>{d.when}</p>
                      </div>
                      {d.overdue && <Badge color="clay">Overdue</Badge>}
                    </div>
                  ))}
                </div>

                <p className="sa-card__eyebrow" style={{ margin: '16px 0 6px' }}>Grade</p>
                <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', background: 'var(--accent-soft)', color: 'var(--accent-text)', borderRadius: 'var(--radius-md)', padding: '12px 14px' }}>
                  <span style={{ fontSize: 'var(--text-sm)' }}>Course total</span>
                  <span style={{ fontSize: 'var(--text-xl)', fontWeight: 500 }}>
                    {courseTotal && courseTotal.grade_formatted && courseTotal.grade_formatted !== '-' ? courseTotal.grade_formatted : 'Not yet graded'}
                  </span>
                </div>
                {courseItems.length > 0 && (
                  <div className="kit-stack" style={{ gap: 0, marginTop: 8 }}>
                    {courseItems.map((g) => (
                      <div className="kit-listrow" key={g.id}>
                        <div className="kit-row__main">
                          <p className="kit-row__title" style={{ fontSize: 'var(--text-sm)' }}>{g.item_name}</p>
                        </div>
                        <span className="kit-row__amt">{g.grade_formatted}</span>
                      </div>
                    ))}
                  </div>
                )}

                <p className="sa-card__eyebrow" style={{ margin: '16px 0 6px' }}>Announcements</p>
                {courseAnns.length === 0 && <p className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>No announcements.</p>}
                <div className="kit-stack" style={{ gap: 10 }}>
                  {courseAnns.map((a) => (
                    <div key={a.id}>
                      <p className="kit-row__title" style={{ fontSize: 'var(--text-sm)' }}>{a.subject}</p>
                      {a.author && <p className="kit-row__sub" style={{ fontSize: 12 }}>{a.author}</p>}
                      {a.summary_html && <p className="kit-muted" style={{ fontSize: 12, marginTop: 2 }}>{a.summary_html}</p>}
                    </div>
                  ))}
                </div>
              </Card>

              {/* persistent cross-course rail */}
              <div className="kit-col">
                <Card title="Upcoming · all courses">
                  {(deadlines || []).length === 0 && <p className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>Nothing due in the next 60 days.</p>}
                  <div className="kit-stack" style={{ gap: 6 }}>
                    {(deadlines || []).map((d) => {
                      const mine = d.course_id === selCourse
                      return (
                        <div
                          className="kit-listrow"
                          key={d.id}
                          style={{ borderRadius: 'var(--radius-md)', background: d.overdue ? 'var(--clay-100)' : mine ? 'var(--accent-soft)' : undefined }}
                        >
                          <span className="kit-listrow__dot" style={{ background: d.overdue ? 'var(--clay-600)' : 'var(--plum-600)' }} />
                          <div className="kit-row__main">
                            <p className="kit-row__title" style={{ fontSize: 'var(--text-sm)' }}>{d.name}</p>
                            <p className="kit-row__sub" style={{ fontSize: 11 }}>{courseName(d.course_id)} · {d.when}</p>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </Card>

                {(notifications || []).length > 0 && (
                  <Card title="Notifications" variant="sunken">
                    <div className="kit-stack" style={{ gap: 6 }}>
                      {(notifications || []).map((n) => (
                        <div className="kit-listrow" key={n.id}>
                          <span className={'kit-mail__dot' + (n.read ? ' read' : '')} />
                          <div className="kit-row__main">
                            <p className="kit-row__title" style={{ fontSize: 'var(--text-sm)' }}>{n.subject}</p>
                            {n.full_message && <p className="kit-row__sub" style={{ fontSize: 12 }}>{n.full_message}</p>}
                          </div>
                        </div>
                      ))}
                    </div>
                  </Card>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
