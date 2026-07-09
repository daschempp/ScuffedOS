/* Scuffed OS — Settings › Connectors (M9 Slice 1). The single surface where all
   four sign-ins (Google, WHOOP, Moodle, Plaid) are connected, reconnected, and
   disconnected. Reads GET /api/connectors for state + settingsGetSecrets for
   vault_ok. Navigation to OAuth authorize URLs stays at the card layer so
   Slice 2 can swap only that one line for the system-browser opener. */
import React from 'react'
import { Card, Button } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'
import { api } from '../lib/api.js'
import { isTauri } from '@tauri-apps/api/core'

const WIPE_COPY = {
  google: 'all synced emails',
  whoop: 'all synced workouts and recovery data',
  moodle: 'all synced courses, grades and deadlines',
  plaid: 'all synced transactions for this account',
}

function StatusChip({ status }) {
  const map = {
    connected: ['Connected', 'var(--green-600)'],
    needs_reauth: ['Needs re-auth', 'var(--clay-600)'],
    not_connected: ['Not connected', 'var(--text-muted)'],
  }
  const [label, color] = map[status] || map.not_connected
  return <span className="kit-muted" style={{ fontSize: 'var(--text-sm)', color }}>{label}</span>
}

// Open an OAuth/hosted-link URL. In the packaged app (isTauri) route through the
// Tauri opener plugin so consent happens in the user's real system browser with
// their live session; in dev keep the webview new-tab behavior.
async function openExternal(url) {
  if (isTauri()) {
    const { openUrl } = await import('@tauri-apps/plugin-opener')
    await openUrl(url)
    return
  }
  window.open(url, '_blank', 'noopener')
}

export function ConnectorsPanel({ onOpenKeys }) {
  const [connectors, setConnectors] = React.useState(null)
  const [vaultOk, setVaultOk] = React.useState(true)
  const [error, setError] = React.useState('')
  const [busy, setBusy] = React.useState('')          // name/item currently acting
  const [confirming, setConfirming] = React.useState('')  // name or item_id awaiting confirm
  const [moodleToken, setMoodleToken] = React.useState('')
  const [pendingLink, setPendingLink] = React.useState(null)  // {link_token} | {reauthItemId} after a Plaid button
  const [linkMsg, setLinkMsg] = React.useState('')

  const refresh = React.useCallback(() => {
    api.getConnectors()
      .then((c) => { setConnectors(c); setError('') })
      .catch((e) => setError(e?.message || 'Failed to load connectors'))
    api.settingsGetSecrets()
      .then((s) => setVaultOk(s.vault_ok !== false))
      .catch(() => setVaultOk(true))
  }, [])

  React.useEffect(() => { refresh() }, [refresh])

  const pollRef = React.useRef(null)
  React.useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current) }, [])

  const snapshotOf = (c) => `${c?.status}|${c?.can_write_email}|${c?.connected_at}`

  // From a Connect click, poll the connectors read model (~2s, bounded ~2min) and
  // stop as soon as THIS connector's (status, can_write_email, connected_at) tuple
  // changes from its pre-click snapshot — covers both first-connect AND the
  // scope-upgrade reconnect (status stays 'connected', only can_write_email moves).
  const startConnectPoll = (name) => {
    const before = snapshotOf((connectors || []).find((c) => c.name === name))
    if (pollRef.current) clearInterval(pollRef.current)
    let ticks = 0
    pollRef.current = setInterval(() => {
      ticks += 1
      api.getConnectors().then((list) => {
        const now = snapshotOf(list.find((c) => c.name === name))
        if (now !== before) {
          clearInterval(pollRef.current); pollRef.current = null
          setConnectors(list); setError('')
        } else if (ticks >= 60) {          // ~2 min at 2s
          clearInterval(pollRef.current); pollRef.current = null
        }
      }).catch(() => {})
    }, 2000)
  }

  const connectOAuth = (name) => {
    setBusy(name)
    api.oauthConnect(name)
      .then((r) => {
        setBusy('')
        openExternal(r.authorize_url)
          .then(() => startConnectPoll(name))
          .catch((e) => setError(e?.message || 'Could not open the sign-in page'))
      })
      .catch((e) => { setError(e?.message || 'Connect failed'); setBusy('') })
  }

  const disconnectOAuth = (name) => {
    setBusy(name)
    api.oauthDisconnect(name)
      .then(() => { setConfirming(''); refresh() })
      .catch((e) => setError(e?.message || 'Disconnect failed'))
      .finally(() => setBusy(''))
  }

  const connectMoodle = () => {
    if (!moodleToken.trim()) return
    setBusy('moodle')
    api.moodleConnect({ token: moodleToken.trim() })
      .then(() => { setMoodleToken(''); refresh() })
      .catch((e) => setError(e?.message || 'Moodle connect failed'))
      .finally(() => setBusy(''))
  }

  // Plaid uses the EXISTING manual "Finish linking" pattern (ported verbatim
  // from FinanceScreen — NOT an auto-poll): open the hosted tab, the user
  // finishes there, then clicks Finish linking; link/complete returns 409 until
  // Plaid is done, surfaced as a "still waiting" message (ApiError.status===409).
  const startLink = (kind) => {
    setLinkMsg('')
    api.financeLinkStart(kind).then((r) => {
      if (r?.hosted_link_url) {
        openExternal(r.hosted_link_url).catch((e) => setError(e?.message || 'Could not open the link page'))
        setPendingLink({ link_token: r.link_token })
        setLinkMsg('Finish linking in the Plaid tab, then click “Finish linking”.')
      }
    }).catch((e) => setError(e?.message || 'Could not start the link flow'))
  }
  const reauthItem = (itemId) => {
    setLinkMsg('')
    api.financeReauthStart(itemId).then((r) => {
      if (r?.hosted_link_url) {
        openExternal(r.hosted_link_url).catch((e) => setError(e?.message || 'Could not open the link page'))
        setPendingLink({ reauthItemId: itemId })
        setLinkMsg('Finish reconnecting in the Plaid tab, then click “Finish linking”.')
      }
    }).catch((e) => setError(e?.message || 'Could not start reconnect'))
  }
  const finishLink = () => {
    if (!pendingLink) return
    const done = pendingLink.reauthItemId
      ? api.financeReauthComplete(pendingLink.reauthItemId)
      : api.financeLinkComplete(pendingLink.link_token)
    done.then(() => { setPendingLink(null); setLinkMsg(''); refresh() })
      .catch((e) => setLinkMsg(e?.status === 409
        ? 'Still waiting — finish in the Plaid tab, then try again.'
        : 'Linking failed. Try again.'))
  }

  if (error && !connectors) {
    return <Card variant="flat"><p className="kit-row__title">{error}</p></Card>
  }
  if (!connectors) {
    return <Card variant="flat"><p className="kit-muted">Loading connectors…</p></Card>
  }

  const connectDisabled = (c) => busy === c.name || (c.auth_kind !== 'token' && (!c.configured || !vaultOk))

  return (
    <div className="kit-stack" style={{ gap: 'var(--gutter)' }}>
      {error && (
        <Card variant="flat" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Icon name="alert-triangle" /><p className="kit-row__title">{error}</p>
        </Card>
      )}
      {!vaultOk && (
        <Card variant="flat" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Icon name="alert-triangle" />
          <p className="kit-muted">The secrets vault can’t be unlocked on this machine, so OAuth
            connects are disabled until you re-enter keys in the API keys tab. Moodle (paste-token) still works.</p>
        </Card>
      )}

      {connectors.map((c) => (
        <Card
          key={c.name}
          title={c.label}
          action={<StatusChip status={c.status} />}
        >
          <div className="kit-stack" style={{ marginTop: 4, gap: 12 }}>
            {c.connected_at && (
              <p className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>
                Connected {new Date(c.connected_at).toLocaleDateString()}
                {c.provider_user_id ? ` · ${c.provider_user_id}` : ''}
              </p>
            )}

            {/* Not-configured gate (OAuth/Plaid only; Moodle exempt) */}
            {c.auth_kind !== 'token' && !c.configured && (
              <div className="kit-inline" style={{ gap: 8, alignItems: 'center' }}>
                <span className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>API keys required.</span>
                <Button variant="secondary" size="sm" onClick={onOpenKeys}>Add API keys first →</Button>
              </div>
            )}

            {/* OAuth connectors: Google / WHOOP */}
            {c.auth_kind === 'oauth' && (
              <div className="kit-inline" style={{ gap: 8 }}>
                {c.status === 'not_connected' && (
                  <Button variant="primary" size="sm" disabled={connectDisabled(c)}
                    onClick={() => connectOAuth(c.name)}>Connect</Button>
                )}
                {c.status === 'needs_reauth' && (
                  <Button variant="primary" size="sm" disabled={connectDisabled(c)}
                    onClick={() => connectOAuth(c.name)}>Reconnect</Button>
                )}
                {c.status === 'connected' && c.name === 'google' && c.can_write_email === false && (
                  <Button variant="secondary" size="sm" disabled={connectDisabled(c)}
                    onClick={() => connectOAuth(c.name)}>Enable email actions</Button>
                )}
                {c.status !== 'not_connected' && confirming !== c.name && (
                  <Button variant="secondary" size="sm" disabled={busy === c.name}
                    onClick={() => setConfirming(c.name)}>Disconnect</Button>
                )}
              </div>
            )}

            {/* Token connector: Moodle */}
            {c.auth_kind === 'token' && (
              <div className="kit-stack" style={{ gap: 8 }}>
                {c.status !== 'connected' && (
                  <>
                    <p className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>
                      {c.status === 'needs_reauth' ? 'Your key expired — paste a fresh one.' : 'Paste your Moodle security key (wstoken).'}
                    </p>
                    <ol className="kit-muted" style={{ fontSize: 'var(--text-sm)', margin: 0, paddingLeft: 18, lineHeight: 1.6 }}>
                      <li>Open Moodle → your profile → <b>Preferences</b> → <b>Security keys</b>.</li>
                      <li>Copy the key for the <b>Moodle mobile web service</b>.</li>
                      <li>Paste it below and Connect.</li>
                    </ol>
                    <div className="kit-inline" style={{ gap: 8 }}>
                      <input type="password" autoComplete="off" placeholder="Paste wstoken"
                        value={moodleToken} onChange={(e) => setMoodleToken(e.target.value)}
                        style={{ flex: 1, padding: '8px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--paper-300)', fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)' }} />
                      <Button variant="primary" size="sm" disabled={busy === 'moodle' || !moodleToken.trim()}
                        onClick={connectMoodle}>Connect</Button>
                    </div>
                  </>
                )}
                {c.status === 'connected' && confirming !== c.name && (
                  <div className="kit-inline"><Button variant="secondary" size="sm"
                    onClick={() => setConfirming(c.name)}>Disconnect</Button></div>
                )}
              </div>
            )}

            {/* Link connector: Plaid (manual Finish-linking pattern) */}
            {c.auth_kind === 'link' && (
              <div className="kit-stack" style={{ gap: 10 }}>
                <div className="kit-inline" style={{ gap: 8 }}>
                  <Button variant="primary" size="sm" disabled={connectDisabled(c)}
                    onClick={() => startLink('bank')}>Link bank account</Button>
                  <Button variant="secondary" size="sm" disabled={connectDisabled(c)}
                    onClick={() => startLink('investments')}>Link investment account</Button>
                </div>
                {pendingLink && (
                  <div className="kit-inline" style={{ gap: 8, alignItems: 'center' }}>
                    <Button variant="primary" size="sm" iconLeft={<Icon name="check" />} onClick={finishLink}>Finish linking</Button>
                    {linkMsg && <span className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>{linkMsg}</span>}
                  </div>
                )}
                {c.items.map((it) => (
                  <div key={it.item_id} className="kit-inline" style={{ justifyContent: 'space-between', alignItems: 'center', gap: 8, borderTop: '1px solid var(--paper-200)', paddingTop: 8 }}>
                    <div>
                      <span className="kit-row__title" style={{ fontSize: 'var(--text-sm)' }}>{it.institution_name}</span>{' '}
                      <StatusChip status={it.status} />
                    </div>
                    {confirming === it.item_id ? (
                      <div className="kit-inline" style={{ gap: 6 }}>
                        <span className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>Delete this account’s transactions?</span>
                        <Button variant="primary" size="sm" disabled={busy === it.item_id}
                          onClick={() => { setBusy(it.item_id); api.financeDisconnect(it.item_id).then(() => { setConfirming(''); refresh() }).catch((e) => setError(e?.message || 'Disconnect failed')).finally(() => setBusy('')) }}>Disconnect</Button>
                        <Button variant="secondary" size="sm" onClick={() => setConfirming('')}>Cancel</Button>
                      </div>
                    ) : (
                      <div className="kit-inline" style={{ gap: 6 }}>
                        {it.status === 'needs_reauth' && (
                          <Button variant="secondary" size="sm" disabled={connectDisabled(c) || busy === it.item_id}
                            onClick={() => reauthItem(it.item_id)}>Reconnect</Button>
                        )}
                        <Button variant="secondary" size="sm" onClick={() => setConfirming(it.item_id)}>Disconnect</Button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {/* Destructive confirm for connector-level (google/whoop/moodle) disconnect */}
            {confirming === c.name && (
              <Card variant="flat" style={{ background: 'var(--clay-100)' }}>
                <p className="kit-row__title" style={{ fontSize: 'var(--text-sm)' }}>
                  This deletes {WIPE_COPY[c.name]} from ScuffedOS.
                </p>
                <div className="kit-inline" style={{ gap: 8, marginTop: 8 }}>
                  <Button variant="primary" size="sm" disabled={busy === c.name}
                    onClick={() => disconnectOAuth(c.name)}>Disconnect</Button>
                  <Button variant="secondary" size="sm" onClick={() => setConfirming('')}>Cancel</Button>
                </div>
              </Card>
            )}
          </div>
        </Card>
      ))}
    </div>
  )
}
