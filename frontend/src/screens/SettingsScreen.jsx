/* Scuffed OS — Settings: integration secrets (M8 Slice 2).
   Shows which integrations are configured (masked presence only — the backend
   never returns raw values), lets the user paste/update keys, nudges first-run
   onboarding, and surfaces a re-authenticate recovery path when the vault fails
   to decrypt (e.g. IOPlatformUUID changed after a hardware move). Mirrors the
   FinanceScreen template + the shared ui/Icon kit. */
import React from 'react'
import { Card, Button } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'
import { api } from '../lib/api.js'

export function SettingsScreen() {
  const [state, setState] = React.useState(null) // { integrations, vault_ok }
  const [error, setError] = React.useState('')
  const [edits, setEdits] = React.useState({})   // { KEY: 'new value' }
  const [saving, setSaving] = React.useState(false)
  const [saved, setSaved] = React.useState(false)

  const refresh = React.useCallback(() => {
    api.settingsGetSecrets()
      .then((s) => { setState(s); setError('') })
      .catch((e) => setError(e?.message || 'Failed to load settings'))
  }, [])

  React.useEffect(() => { refresh() }, [refresh])

  const startEdit = (key) => setEdits((p) => ({ ...p, [key]: '' }))
  const cancelEdit = (key) => setEdits((p) => { const n = { ...p }; delete n[key]; return n })
  const setEdit = (key, val) => setEdits((p) => ({ ...p, [key]: val }))

  const save = () => {
    const values = { ...edits }
    if (Object.keys(values).length === 0) return
    setSaving(true)
    api.settingsPutSecrets(values)
      .then((s) => {
        setState(s)
        setEdits({})
        setSaved(true)
        setTimeout(() => setSaved(false), 2500)
      })
      .catch((e) => setError(e?.message || 'Failed to save settings'))
      .finally(() => setSaving(false))
  }

  const integrations = state ? Object.entries(state.integrations) : []
  const anyConfigured = integrations.some(([, ig]) => ig.keys.some((k) => k.present))
  const dirty = Object.keys(edits).length > 0

  // Re-authenticate recovery: the vault could not be decrypted.
  if (state && state.vault_ok === false) {
    return (
      <Card variant="flat" style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <span className="kit-statline__ico" style={{ background: 'var(--clay-100)', color: 'var(--clay-600)' }}>
          <Icon name="alert-triangle" />
        </span>
        <div style={{ flex: 1 }}>
          <p className="kit-row__title">Re-authenticate your integrations</p>
          <p className="kit-muted">
            The local secrets vault could not be unlocked on this machine (this
            happens if the hardware changed). Your keys are safe but must be
            re-entered. Paste them again below to repair the vault.
          </p>
        </div>
        <Button variant="primary" size="sm" iconLeft={<Icon name="refresh-cw" />}
          onClick={() => setState({ ...state, vault_ok: true })}>
          Re-enter keys
        </Button>
      </Card>
    )
  }

  // First-run onboarding nudge: nothing configured yet.
  if (state && !anyConfigured && !dirty) {
    return (
      <Card variant="flat" style={{ maxWidth: 560, margin: '0 auto', padding: '40px 28px', textAlign: 'center' }}>
        <div style={{ display: 'inline-flex', width: 56, height: 56, borderRadius: 'var(--radius-lg)', background: 'var(--accent-soft)', color: 'var(--accent-text)', alignItems: 'center', justifyContent: 'center', marginBottom: 14 }}>
          <Icon name="sliders-horizontal" />
        </div>
        <h3 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-xl)', color: 'var(--text-strong)', margin: '0 0 6px' }}>
          Connect your integrations
        </h3>
        <p className="kit-muted" style={{ maxWidth: 420, margin: '0 auto 18px' }}>
          Add API keys and OAuth credentials for the assistant, nutrition, and
          your connected services. They are encrypted in a machine-bound vault on
          this Mac — never uploaded, never shown again.
        </p>
        <Button variant="primary" iconLeft={<Icon name="plus" />}
          onClick={() => setState({ ...state, __expandAll: true })}>
          Add keys
        </Button>
      </Card>
    )
  }

  return (
    <div className="kit-stack" style={{ gap: 'var(--gutter)' }}>
      {error && (
        <Card variant="flat" style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <span className="kit-statline__ico" style={{ background: 'var(--clay-100)', color: 'var(--clay-600)' }}>
            <Icon name="alert-triangle" />
          </span>
          <p className="kit-row__title">{error}</p>
        </Card>
      )}
      {saved && (
        <Card variant="flat" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Icon name="check" /><p>Settings saved.</p>
        </Card>
      )}

      {integrations.map(([id, ig]) => (
        <Card
          key={id}
          title={ig.label}
          action={
            <span className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>
              {ig.keys.every((k) => k.present)
                ? 'Configured'
                : ig.keys.some((k) => k.present) ? 'Partial' : 'Not set'}
            </span>
          }
        >
          <div className="kit-stack" style={{ marginTop: 4, gap: 12 }}>
            {ig.keys.map((k) => (
              <div key={k.key}>
                <label style={{ display: 'block', marginBottom: 6, fontFamily: 'var(--font-display)', fontSize: 'var(--text-sm)', color: 'var(--text-strong)' }}>
                  {k.key}
                </label>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <div style={{ flex: 1, padding: '8px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--paper-300)', fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)', color: 'var(--text-muted)', background: 'var(--paper-100)' }}>
                    {k.present ? '••••••••••••' : '(not set)'}
                  </div>
                  {edits[k.key] === undefined ? (
                    <Button variant="secondary" size="sm" iconLeft={<Icon name="pen-line" />}
                      onClick={() => startEdit(k.key)}>
                      {k.present ? 'Replace' : 'Add'}
                    </Button>
                  ) : (
                    <Button variant="secondary" size="sm" iconLeft={<Icon name="x" />}
                      onClick={() => cancelEdit(k.key)}>
                      Cancel
                    </Button>
                  )}
                </div>
                {edits[k.key] !== undefined && (
                  <input
                    type="password"
                    autoComplete="off"
                    placeholder={`Paste ${k.key}`}
                    value={edits[k.key]}
                    onChange={(e) => setEdit(k.key, e.target.value)}
                    style={{ marginTop: 8, width: '100%', padding: '8px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--paper-300)', fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)' }}
                  />
                )}
              </div>
            ))}
          </div>
        </Card>
      ))}

      {dirty && (
        <div className="kit-inline" style={{ justifyContent: 'flex-end', gap: 8 }}>
          <Button variant="secondary" size="sm" onClick={() => setEdits({})} disabled={saving}>Discard</Button>
          <Button variant="primary" size="sm" onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save changes'}
          </Button>
        </div>
      )}
    </div>
  )
}
