/* Scuffed OS — Email triage (live, synced with Gmail via Google OAuth).
   Owns its own state (App.jsx renders <EmailScreen /> with no props), mirroring
   FitnessScreen's in-component fetch convention. /api/oauth/status drives which
   connection state renders; /api/email/inbox feeds the two-pane view. The inbox
   comes straight from the emails table server-side (never a live Gmail call), so
   it works while a sync is mid-flight or Gmail is down — it shows what's landed.
   Only the reading pane fetches a body live (/api/email/{id}), with a graceful
   fallback string. Message bodies are never persisted; tokens never reach the
   client. Draft/send is a later slice — no draft UI here. */
import React from 'react'
import { Card, Badge, Button } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'
import { api } from '../lib/api.js'

/* Category → the left-column group label + list. Untriaged messages still show
   (under 'Other') so a triage hiccup never hides mail. */
const GROUPS = [
  { key: 'needs_reply', label: 'Needs reply' },
  { key: 'fyi', label: 'FYI' },
  { key: 'untriaged', label: 'Other' },
]

export function EmailScreen() {
  const [status, setStatus] = React.useState(null)   // null = /status not answered yet
  const [inbox, setInbox] = React.useState(null)     // null = not loaded
  const [selId, setSelId] = React.useState(null)
  const [detail, setDetail] = React.useState(null)   // full email incl. body, for selId

  const refresh = React.useCallback(() => {
    api.oauthStatus().then((s) => { if (s) setStatus(s) }).catch(() => {})
    api.emailInbox().then((i) => { if (i) setInbox(i) }).catch(() => {})
  }, [])

  React.useEffect(() => { refresh() }, [refresh])

  const google = (status?.providers || []).find((p) => p.provider === 'google') || null
  const connected = !!google
  const needsReauth = google?.status === 'needs_reauth'
  // Raw scopes never reach the client (privacy decision from slice-1) — the
  // server derives this boolean from the stored granted scopes (contract §A).
  const canWrite = connected && !needsReauth && !!google?.can_write_email

  const groups = React.useMemo(() => GROUPS.map((g) => ({
    ...g, items: (inbox?.[g.key] || []),
  })), [inbox])
  const total = groups.reduce((n, g) => n + g.items.length, 0)
  // Connected, no reauth, nothing has landed yet, and google has never synced →
  // first backfill is still running. This is a pre-first-tick state (matches
  // FitnessScreen): email_sync always stamps last_sync_at, so once the first
  // tick completes a genuinely-empty inbox shows the "Inbox is clear" state, not
  // this banner.
  const syncing = connected && !needsReauth && inbox != null && total === 0 && !google?.last_sync_at

  // Auto-select the first message once the inbox lands (and keep a valid
  // selection if the current one disappears after a refresh).
  React.useEffect(() => {
    if (total === 0) { setSelId(null); return }
    const flat = groups.flatMap((g) => g.items)
    if (selId == null || !flat.some((e) => e.id === selId)) setSelId(flat[0].id)
  }, [groups, total, selId])

  // Load the body (and fresh metadata) whenever the selection changes.
  React.useEffect(() => {
    if (selId == null) { setDetail(null); return }
    let live = true
    setDetail(null)
    api.emailDetail(selId).then((d) => { if (live && d) setDetail(d) }).catch(() => {})
    return () => { live = false }
  }, [selId])

  const connect = () => {
    api.oauthConnect('google')
      .then((r) => { if (r?.authorize_url) window.location = r.authorize_url })
      .catch(() => {})
  }
  const sync = () => { api.emailSync().then(() => refresh()).catch(() => {}) }

  // —— not connected: single CTA card ——
  if (status && !connected && !needsReauth) {
    return (
      <Card variant="flat" style={{ textAlign: 'center', padding: '56px 24px' }}>
        <div style={{ display: 'inline-flex', width: 56, height: 56, borderRadius: 'var(--radius-lg)', background: 'var(--accent-soft)', color: 'var(--accent-text)', alignItems: 'center', justifyContent: 'center', marginBottom: 14 }}>
          <Icon name="mail" />
        </div>
        <h3 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-xl)', color: 'var(--text-strong)', margin: '0 0 6px' }}>Connect Google</h3>
        <p className="kit-muted" style={{ maxWidth: 380, margin: '0 auto 18px' }}>Sync your Gmail inbox into Scuffed OS. Messages are triaged into what needs a reply vs. FYI, with AI summaries. Read-only — your tokens stay server-side and message bodies are never stored.</p>
        <Button variant="primary" iconLeft={<Icon name="mail" />} onClick={connect}>Connect Google</Button>
      </Card>
    )
  }

  const eyebrow = google?.last_sync_at
    ? `Synced with Gmail · ${new Date(google.last_sync_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`
    : 'Connected with Gmail'
  const needCount = inbox?.needs_reply_count ?? 0

  return (
    <div className="kit-stack" style={{ gap: 'var(--gutter)' }}>
      {needsReauth && (
        <Card variant="flat" style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <span className="kit-statline__ico" style={{ background: 'var(--clay-100)', color: 'var(--clay-600)' }}><Icon name="alert-triangle" /></span>
          <div style={{ flex: 1 }}>
            <p className="kit-row__title">Google needs to be reconnected</p>
            <p className="kit-muted">Your authorization expired or was revoked. Reconnect to resume syncing your inbox.</p>
          </div>
          <Button variant="primary" size="sm" onClick={connect}>Reconnect</Button>
        </Card>
      )}

      {connected && !needsReauth && !canWrite && (
        <Card variant="flat" style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <span className="kit-statline__ico" style={{ background: 'var(--sky-100)', color: 'var(--sky-600)' }}><Icon name="mail" /></span>
          <div style={{ flex: 1 }}>
            <p className="kit-row__title">Enable email actions</p>
            <p className="kit-muted">ScuffedOS has read-only access. Re-connect Google and tick the Gmail checkboxes to allow replying, deleting, starring and labeling.</p>
          </div>
          <Button variant="primary" size="sm" onClick={connect}>Enable</Button>
        </Card>
      )}

      {syncing && (
        <Card variant="flat" style={{ textAlign: 'center', padding: '48px 24px' }}>
          <div style={{ display: 'inline-flex', width: 56, height: 56, borderRadius: 'var(--radius-lg)', background: 'var(--accent-soft)', color: 'var(--accent-text)', alignItems: 'center', justifyContent: 'center', marginBottom: 14 }}>
            <Icon name="refresh-cw" />
          </div>
          <h3 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-xl)', color: 'var(--text-strong)', margin: '0 0 6px' }}>Syncing…</h3>
          <p className="kit-muted" style={{ maxWidth: 380, margin: '0 auto 18px' }}>Pulling and triaging your inbox from Gmail. This usually takes a moment — hang tight.</p>
          <Button variant="secondary" size="sm" iconLeft={<Icon name="refresh-cw" />} onClick={sync}>Check again</Button>
        </Card>
      )}

      {!syncing && (
        <div className="kit-grid" style={{ gridTemplateColumns: '1fr 1.15fr' }}>
          <Card title="Inbox" eyebrow={eyebrow}
            action={
              <div className="kit-inline" style={{ gap: 8, alignItems: 'center' }}>
                {needCount > 0 && <Badge color="green" dot>{needCount} need you</Badge>}
                <Button variant="soft" size="sm" iconLeft={<Icon name="refresh-cw" />} onClick={sync}>Sync</Button>
              </div>
            }>
            {total === 0 && <p className="kit-muted" style={{ marginTop: 6 }}>Inbox is clear — nothing to triage right now.</p>}
            {groups.map((g) => g.items.length === 0 ? null : (
              <div key={g.key}>
                <p className="sa-card__eyebrow" style={{ margin: '12px 0 4px' }}>{g.label}</p>
                {g.items.map((e) => (
                  <div key={e.id} className={'kit-mail' + (e.id === selId ? ' is-active' : '')} onClick={() => setSelId(e.id)}>
                    <span className={'kit-mail__dot' + (e.unread ? '' : ' read')} />
                    <div className="kit-mail__main">
                      <div className="kit-mail__top">
                        <span className="kit-mail__from">{e.from_name || e.from_email}</span>
                        <span className="kit-mail__time">{e.when}</span>
                      </div>
                      <p className="kit-mail__subj">{e.subject || '(no subject)'}</p>
                      <p className="kit-mail__snip">{e.snippet}</p>
                    </div>
                  </div>
                ))}
              </div>
            ))}
          </Card>

          <div className="kit-col">
            {detail ? (
              <>
                <Card eyebrow={`${detail.from_name || detail.from_email}${detail.from_email && detail.from_name ? ` · ${detail.from_email}` : ''}`} title={detail.subject || '(no subject)'}>
                  {(detail.summary || []).length > 0 && (
                    <>
                      <p className="sa-card__eyebrow" style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 }}><Icon name="sparkles" style={{ width: 13, height: 13 }} />AI summary</p>
                      <div className="kit-bullets" style={{ marginBottom: 14 }}>
                        {detail.summary.map((b, i) => (
                          <div className="kit-bullet" key={i}><Icon name="check" />{b}</div>
                        ))}
                      </div>
                    </>
                  )}
                  <div className="kit-draft">{detail.body}</div>
                </Card>

                {detail.category === 'fyi' && (
                  <Card variant="sunken">
                    <div className="kit-insight">
                      <div className="kit-insight__icon"><Icon name="check-check" /></div>
                      <p>No reply needed — I've filed this as <strong>FYI</strong>.</p>
                    </div>
                  </Card>
                )}
              </>
            ) : (
              <Card><p className="kit-muted">{selId == null ? 'Select a message to read it.' : 'Loading…'}</p></Card>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
