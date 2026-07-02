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
import { Card, Badge, Button, IconButton, Checkbox } from '../components/ui.jsx'
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
  const [sortKey, setSortKey] = React.useState('newest')  // newest | oldest | sender | unread
  const [composeMode, setComposeMode] = React.useState(null)  // null | 'new' | 'reply' | 'forward' (Task 17)
  const [labels, setLabels] = React.useState(null)   // LabelOut[] | null = not loaded yet
  const [labelMenuOpen, setLabelMenuOpen] = React.useState(false)
  const [actionError, setActionError] = React.useState('')  // transient inline error, cleared on next successful action
  const [composeTo, setComposeTo] = React.useState('')
  const [composeSubject, setComposeSubject] = React.useState('')
  const [composeBody, setComposeBody] = React.useState('')
  const [composeError, setComposeError] = React.useState('')  // separate from actionError — scoped to the overlay, never clears the box
  const [aiOpen, setAiOpen] = React.useState(false)
  const [aiInstructions, setAiInstructions] = React.useState('')
  const [aiDrafted, setAiDrafted] = React.useState(false)  // false = "Draft", true = "Regenerate"
  const [aiBusy, setAiBusy] = React.useState(false)
  const [sending, setSending] = React.useState(false)

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

  const sortItems = React.useCallback((items) => {
    const arr = [...items]
    if (sortKey === 'oldest') arr.sort((a, b) => new Date(a.received_at) - new Date(b.received_at))
    else if (sortKey === 'sender') arr.sort((a, b) => (a.from_name || a.from_email).localeCompare(b.from_name || b.from_email))
    else if (sortKey === 'unread') arr.sort((a, b) => (b.unread === a.unread ? 0 : b.unread ? 1 : -1))
    else arr.sort((a, b) => new Date(b.received_at) - new Date(a.received_at))  // 'newest' (default)
    return arr
  }, [sortKey])
  const groups = React.useMemo(() => GROUPS.map((g) => ({
    ...g, items: sortItems(inbox?.[g.key] || []),
  })), [inbox, sortItems])
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

  // Confirm-first writes (contract §F): the Gmail call happens server-side
  // before any local change; on failure the store is untouched and we only
  // set actionError — nothing else in the pane changes.
  const runAction = (promise) => {
    setActionError('')
    return promise
      .then((result) => { refresh(); return result })
      .catch((err) => { setActionError(err?.message || 'That action failed. Try again.') })
  }
  const toggleStar = (e) => {
    runAction(api.emailFlags(e.id, { starred: !e.starred })).then(() => {
      if (selId === e.id) api.emailDetail(e.id).then((d) => { if (d) setDetail(d) }).catch(() => {})
    })
  }
  const toggleRead = (e) => {
    runAction(api.emailFlags(e.id, { unread: !e.unread })).then(() => {
      if (selId === e.id) api.emailDetail(e.id).then((d) => { if (d) setDetail(d) }).catch(() => {})
    })
  }
  const trashSelected = () => {
    if (selId == null) return
    runAction(api.emailTrash(selId)).then(() => { setSelId(null); setDetail(null) })
  }
  const openLabelMenu = () => {
    setLabelMenuOpen((v) => !v)
    if (labels == null) api.emailLabelList().then((ls) => { if (Array.isArray(ls)) setLabels(ls) }).catch(() => setLabels([]))
  }
  const toggleLabel = (labelId) => {
    if (!detail) return
    const has = (detail.label_ids || []).includes(labelId)
    const payload = has ? { add: [], remove: [labelId] } : { add: [labelId], remove: [] }
    runAction(api.emailLabels(detail.id, payload)).then(() => {
      api.emailDetail(detail.id).then((d) => { if (d) setDetail(d) }).catch(() => {})
    })
  }

  // Quote-block divider format is frozen by contract §I: reply/forward prefill
  // quotes the already-loaded detail.body below this exact divider line.
  const quoteBlock = (d) => `\n\n--- On ${d.when}, ${d.from_name || d.from_email} wrote: ---\n${d.body || ''}`

  const openCompose = (mode) => {
    setComposeError('')
    setAiOpen(false); setAiInstructions(''); setAiDrafted(false)
    if (mode === 'reply' && detail) {
      setComposeTo(detail.from_email)
      setComposeSubject(detail.subject?.toLowerCase().startsWith('re:') ? detail.subject : `Re: ${detail.subject || '(no subject)'}`)
      setComposeBody(quoteBlock(detail))
    } else if (mode === 'forward' && detail) {
      setComposeTo('')
      setComposeSubject(detail.subject?.toLowerCase().startsWith('fwd:') ? detail.subject : `Fwd: ${detail.subject || '(no subject)'}`)
      setComposeBody(quoteBlock(detail))
    } else {
      setComposeTo(''); setComposeSubject(''); setComposeBody('')
    }
    setComposeMode(mode)
  }
  const closeCompose = () => {
    setComposeMode(null); setComposeTo(''); setComposeSubject(''); setComposeBody('')
    setComposeError(''); setAiOpen(false); setAiInstructions(''); setAiDrafted(false)
  }
  const draftWithAi = () => {
    if (!aiInstructions.trim()) return
    setAiBusy(true)
    // notes must be only what the user has actually typed — for reply/forward,
    // composeBody was seeded with the full quote block (quoteBlock(detail)),
    // which is redundant with (and differently formatted from) the same
    // content the backend already fetches live via original.body_excerpt
    // (contract §G). Strip everything from the quote divider onward before
    // sending, matching the pre-quote-only framing used when the response
    // handler below re-appends the quote after drafting.
    const notes = composeBody.split(/\n\n--- On .+ wrote: ---\n/)[0]
    api.emailDraft({
      instructions: aiInstructions,
      notes,
      mode: composeMode,
      email_id: composeMode !== 'new' && detail ? detail.id : null,
    }).then((r) => {
      setAiBusy(false)
      if (!r || typeof r.draft !== 'string') { setComposeError("Couldn't draft — try again."); return }
      // Pin (contract §I / spec §8): the draft replaces only the pre-quote
      // section; the quote block (if any) stays appended below it.
      const quote = (composeMode === 'reply' || composeMode === 'forward') && detail ? quoteBlock(detail) : ''
      setComposeBody(r.draft + quote)
      setAiDrafted(true)
    }).catch(() => { setAiBusy(false); setComposeError("Couldn't draft — try again.") })
  }
  const sendCompose = () => {
    if (!composeTo.trim() && composeMode !== 'reply') { setComposeError('To is required.'); return }
    if (!composeSubject.trim() && composeMode !== 'reply') { setComposeError('Subject is required.'); return }
    setSending(true)
    setComposeError('')
    let promise
    if (composeMode === 'reply' && detail) promise = api.emailReply(detail.id, { body: composeBody })
    else if (composeMode === 'forward' && detail) promise = api.emailForward(detail.id, { to: composeTo, body: composeBody })
    else promise = api.emailSend({ to: composeTo, subject: composeSubject, body: composeBody })
    promise.then(() => {
      setSending(false)
      closeCompose()
      refresh()
    }).catch((err) => {
      // Failure keeps EVERYTHING intact (contract §Global Constraints) — only
      // composeError is set; composeTo/composeSubject/composeBody untouched.
      setSending(false)
      setComposeError(err?.message || 'Send failed. Your draft is still here — try again.')
    })
  }

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

  const sortSelectStyle = {
    padding: '8px 11px', borderRadius: 'var(--radius-sm)', background: 'var(--surface-sunken)',
    border: 'none', outline: 'none', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)',
    color: 'var(--text-strong)', cursor: 'pointer',
  }
  const composeInputStyle = {
    padding: '8px 11px', borderRadius: 'var(--radius-sm)', background: 'var(--surface-sunken)',
    border: 'none', outline: 'none', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)',
    color: 'var(--text-strong)', width: '100%',
  }
  const composeTextareaStyle = {
    padding: '10px 12px', borderRadius: 'var(--radius-md)', background: 'var(--surface-sunken)',
    border: 'none', outline: 'none', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)',
    color: 'var(--text-strong)', width: '100%', resize: 'vertical', lineHeight: 1.5,
  }

  return (
    <div className="kit-stack" style={{ gap: 'var(--gutter)' }}>
      {canWrite && composeMode != null && (
        <Card variant="flat" title={composeMode === 'reply' ? 'Reply' : composeMode === 'forward' ? 'Forward' : 'New message'}
          action={<IconButton label="Close" size="sm" onClick={closeCompose}><Icon name="x" /></IconButton>}>
          <div className="kit-stack" style={{ gap: 10 }}>
            <div className="kit-field">
              <span className="kit-field__label">To</span>
              {composeMode === 'reply' ? (
                <p className="kit-muted" style={{ margin: 0 }}>{composeTo}</p>
              ) : (
                <input value={composeTo} onChange={(e) => setComposeTo(e.target.value)} placeholder="name@example.com" style={composeInputStyle} />
              )}
            </div>
            {/* cc omitted from the UI this slice — the API supports it (SendEmail.cc), not exposed here. */}
            <div className="kit-field">
              <span className="kit-field__label">Subject</span>
              <input value={composeSubject} onChange={(e) => setComposeSubject(e.target.value)} placeholder="Subject" style={composeInputStyle} disabled={composeMode === 'reply'} />
            </div>
            <div className="kit-inline" style={{ gap: 8 }}>
              <IconButton label={aiDrafted ? 'Regenerate with AI' : 'Draft with AI'} size="sm" onClick={() => setAiOpen((v) => !v)}><Icon name="sparkles" /></IconButton>
              {aiOpen && (
                <>
                  <input value={aiInstructions} onChange={(e) => setAiInstructions(e.target.value)} placeholder="What should it say?" style={{ ...composeInputStyle, flex: 1 }} />
                  <Button variant="soft" size="sm" onClick={draftWithAi} disabled={aiBusy || !aiInstructions.trim()}>{aiBusy ? 'Drafting…' : aiDrafted ? 'Regenerate' : 'Draft'}</Button>
                </>
              )}
            </div>
            <textarea className="kit-desc" value={composeBody} onChange={(e) => setComposeBody(e.target.value)} rows={10} placeholder="Write your message…" style={composeTextareaStyle} />
            {composeError && <p className="kit-muted" style={{ color: 'var(--clay-600)' }}>{composeError}</p>}
            <div className="kit-inline" style={{ gap: 8, justifyContent: 'flex-end' }}>
              <Button variant="ghost" size="sm" onClick={closeCompose}>Cancel</Button>
              <Button variant="primary" size="sm" iconLeft={<Icon name="send" />} onClick={sendCompose} disabled={sending}>{sending ? 'Sending…' : 'Send'}</Button>
            </div>
          </div>
        </Card>
      )}

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
                <select value={sortKey} onChange={(e) => setSortKey(e.target.value)} style={sortSelectStyle} aria-label="Sort inbox">
                  <option value="newest">Newest</option>
                  <option value="oldest">Oldest</option>
                  <option value="sender">Sender</option>
                  <option value="unread">Unread first</option>
                </select>
                {canWrite && <Button variant="soft" size="sm" iconLeft={<Icon name="pen-line" />} onClick={() => openCompose('new')}>Compose</Button>}
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
                        <span className="kit-inline" style={{ gap: 6 }}>
                          {e.starred && <Icon name="star" style={{ width: 13, height: 13, color: 'var(--honey-600)', fill: 'var(--honey-600)' }} />}
                          <span className="kit-mail__time">{e.when}</span>
                        </span>
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
                  {canWrite && (
                    <div className="kit-inline" style={{ gap: 6, flexWrap: 'wrap', marginBottom: 12, position: 'relative' }}>
                      <Button variant="soft" size="sm" iconLeft={<Icon name="reply" />} onClick={() => openCompose('reply')}>Reply</Button>
                      <Button variant="soft" size="sm" iconLeft={<Icon name="forward" />} onClick={() => openCompose('forward')}>Forward</Button>
                      <IconButton label={detail.starred ? 'Unstar' : 'Star'} size="sm" onClick={() => toggleStar(detail)}>
                        <Icon name="star" style={detail.starred ? { color: 'var(--honey-600)', fill: 'var(--honey-600)' } : undefined} />
                      </IconButton>
                      <IconButton label={detail.unread ? 'Mark read' : 'Mark unread'} size="sm" onClick={() => toggleRead(detail)}><Icon name="check-check" /></IconButton>
                      <IconButton label="Labels" size="sm" onClick={openLabelMenu}><Icon name="tag" /></IconButton>
                      <IconButton label="Trash" size="sm" onClick={trashSelected}><Icon name="trash-2" /></IconButton>
                      {labelMenuOpen && (
                        <div className="sa-card" style={{ position: 'absolute', top: 40, left: 0, zIndex: 20, padding: 10, minWidth: 180, boxShadow: 'var(--shadow-lg)' }}>
                          {(labels || []).length === 0 && <p className="kit-muted">No labels.</p>}
                          {(labels || []).map((l) => (
                            <Checkbox key={l.id} checked={(detail.label_ids || []).includes(l.id)} onChange={() => toggleLabel(l.id)} label={l.name} />
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                  {actionError && <p className="kit-muted" style={{ color: 'var(--clay-600)', marginBottom: 10 }}>{actionError}</p>}
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
