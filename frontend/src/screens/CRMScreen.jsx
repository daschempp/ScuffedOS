/* Scuffed OS — Personal CRM (M10 s1): a usable People/CRM backed by real rows.
   Rows come from api.listPeople() — a union of manually-created people and the
   one-way macOS Contacts import (source='macos_contacts'). Imported IDENTITY is
   READ-ONLY here (edit it in the Contacts app); the CRM-native fields
   (relationship, notes, pinned) are editable on every person. The header status
   model makes the distinct sync states legible; the list never blocks on a sync. */
import React from 'react'
import { Card, Avatar, Badge, Button, IconButton, Checkbox } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'
import { api } from '../lib/api.js'

const TINTS = ['sky', 'plum', 'green', 'honey', 'clay']
const tintFor = (p) => TINTS[(p.id || 0) % TINTS.length]
const isImported = (p) => p.source === 'macos_contacts'

const SR_ONLY = {
  position: 'absolute', width: 1, height: 1, padding: 0, margin: -1,
  overflow: 'hidden', clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap', border: 0,
}
const INPUT_STYLE = {
  padding: '8px 11px', borderRadius: 'var(--radius-sm)', background: 'var(--surface-sunken)',
  border: '1px solid var(--border-soft)', fontFamily: 'var(--font-sans)',
  fontSize: 'var(--text-sm)', color: 'var(--text-strong)', width: '100%',
}
const TONE_TINT = {
  sky: { background: 'var(--sky-100)', color: 'var(--sky-600)' },
  honey: { background: 'var(--honey-100)', color: 'var(--honey-600)' },
  clay: { background: 'var(--clay-100)', color: 'var(--clay-600)' },
  muted: { background: 'var(--paper-200)', color: 'var(--text-muted)' },
}

// probe_access (Design Contract) returns only granted|denied|unknown; 'unsupported'
// is a frontend projection for a non-macOS host or an UNSUPPORTED_SCHEMA snapshot,
// kept distinct so we never mislabel it "denied".
function contactsCapability(c) {
  if (!c) return 'unknown'
  if (c.configured === false || c.sync_status === 'unsupported') return 'unsupported'
  return c.access || 'unknown'
}

// The sync-state banner descriptor (null when the import is off or idle-ready).
// Covers the distinct states: first-sync, syncing, access-denied, stale,
// last-error, and unsupported. (genuinely-empty / no-search-matches are handled
// in the list region below.)
function syncBanner(c) {
  if (!c || !c.enabled) return null
  const cap = contactsCapability(c)
  if (cap === 'unsupported') {
    return { tone: 'muted', icon: 'unplug', busy: false, title: 'Contacts import isn’t available on this device.' }
  }
  if (cap === 'denied' || c.sync_status === 'access_denied') {
    return {
      tone: 'clay', icon: 'alert-triangle', busy: false, denied: true,
      title: 'Full Disk Access is off — contacts can’t refresh.',
      detail: c.last_sync_at ? `Showing the last import from ${new Date(c.last_sync_at).toLocaleString()}.` : null,
    }
  }
  if (c.sync_status === 'syncing') {
    return {
      tone: 'sky', icon: 'refresh-cw', busy: true,
      title: c.last_sync_at ? 'Refreshing contacts…' : 'Importing your contacts for the first time…',
    }
  }
  if (c.sync_status === 'stale') {
    return {
      tone: 'honey', icon: 'clock', busy: false, retry: true, title: 'Contacts may be out of date.',
      detail: c.last_sync_at ? `Last synced ${new Date(c.last_sync_at).toLocaleString()}.` : null,
    }
  }
  if (c.sync_status === 'error') {
    return {
      tone: 'clay', icon: 'alert-triangle', busy: false, retry: true,
      title: 'The last contacts sync didn’t finish.', detail: c.last_error || null,
    }
  }
  return null
}

function matches(p, q) {
  if (!q.trim()) return true
  const hay = [p.display_name, p.organization, p.job_title,
    ...(p.emails || []).map((e) => e.value),
    ...(p.phones || []).map((ph) => ph.value)].filter(Boolean).join(' ').toLowerCase()
  return hay.includes(q.trim().toLowerCase())
}

function Field({ label, required, children }) {
  return (
    <label className="kit-field">
      <span className="kit-field__label">{label}{required ? ' *' : ''}</span>
      {children}
    </label>
  )
}

function ReadOnlyRow({ label, value }) {
  return (
    <div className="kit-field">
      <span className="kit-field__label">{label}</span>
      <span className="kit-row__title" style={{ fontSize: 'var(--text-sm)' }}>{value || '—'}</span>
    </div>
  )
}

function EmptyPeople({ contacts, onAdd, onOpenConnectors }) {
  const enabled = !!contacts?.enabled
  return (
    <div className="kit-stack" style={{ alignItems: 'center', padding: 32, textAlign: 'center', gap: 10 }}>
      <Icon name="users" />
      <p className="kit-row__title">{enabled ? 'No contacts to show yet' : 'No people yet'}</p>
      <p className="kit-muted" style={{ fontSize: 'var(--text-sm)', maxWidth: 320 }}>
        {enabled
          ? 'Your macOS Contacts import is on but hasn’t returned anyone yet.'
          : 'Add someone by hand, or import your macOS Contacts from Settings › Connectors.'}
      </p>
      <div className="kit-inline" style={{ gap: 8 }}>
        <Button variant="primary" size="sm" iconLeft={<Icon name="plus" />} onClick={onAdd}>Add a person</Button>
        {!enabled && onOpenConnectors && (
          <Button variant="secondary" size="sm" iconLeft={<Icon name="settings" />} onClick={onOpenConnectors}>
            Import from Contacts
          </Button>
        )}
      </div>
    </div>
  )
}

function PersonEditor({ onCancel, onSaved }) {
  const [name, setName] = React.useState('')
  const [email, setEmail] = React.useState('')
  const [phone, setPhone] = React.useState('')
  const [relationship, setRelationship] = React.useState('')
  const [notes, setNotes] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [err, setErr] = React.useState('')

  const submit = async (e) => {
    e.preventDefault()
    if (!name.trim()) { setErr('A name is required.'); return }
    setBusy(true); setErr('')
    try {
      const created = await api.createPerson({
        display_name: name.trim(),
        emails: email.trim() ? [{ value: email.trim(), label: 'Home' }] : [],
        phones: phone.trim() ? [{ value: phone.trim(), label: 'Mobile' }] : [],
        relationship: relationship.trim() || null,
        notes: notes.trim() || null,
      })
      await onSaved(created)
    } catch (e2) {
      setErr(e2?.message || 'Couldn’t save this person.'); setBusy(false)
    }
  }

  return (
    <Card title="New person" variant="sunken">
      <form className="kit-stack" style={{ gap: 10 }} onSubmit={submit}>
        <Field label="Name" required>
          <input aria-label="Name" autoFocus value={name} style={INPUT_STYLE} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Email">
          <input aria-label="Email" type="email" value={email} style={INPUT_STYLE} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Phone">
          <input aria-label="Phone" value={phone} style={INPUT_STYLE} onChange={(e) => setPhone(e.target.value)} />
        </Field>
        <Field label="Relationship">
          <input aria-label="Relationship" value={relationship} style={INPUT_STYLE} onChange={(e) => setRelationship(e.target.value)} />
        </Field>
        <Field label="Notes">
          <textarea aria-label="Notes" rows={3} value={notes} style={{ ...INPUT_STYLE, resize: 'vertical' }} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        {err && <p role="alert" style={{ margin: 0, fontSize: 'var(--text-sm)', color: 'var(--clay-600)' }}>{err}</p>}
        <div className="kit-inline" style={{ gap: 8 }}>
          <Button type="submit" variant="primary" size="sm" disabled={busy}>{busy ? 'Saving…' : 'Save'}</Button>
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
        </div>
      </form>
    </Card>
  )
}

function PersonDetail({ person, onChanged, onDeleted }) {
  const imported = isImported(person)
  const [displayName, setDisplayName] = React.useState(person.display_name || '')
  const [relationship, setRelationship] = React.useState(person.relationship || '')
  const [notes, setNotes] = React.useState(person.notes || '')
  const [pinned, setPinned] = React.useState(!!person.pinned)
  const [busy, setBusy] = React.useState(false)
  const [msg, setMsg] = React.useState('')
  const [confirmDelete, setConfirmDelete] = React.useState(false)

  // Re-seed the form whenever a different person is selected.
  React.useEffect(() => {
    setDisplayName(person.display_name || ''); setRelationship(person.relationship || '')
    setNotes(person.notes || ''); setPinned(!!person.pinned); setMsg(''); setConfirmDelete(false)
  }, [person.id])

  const save = async () => {
    setBusy(true); setMsg('')
    // sync never writes CRM-native fields; conversely, imported identity is edited
    // in the Contacts app, so we only send display_name for manual people.
    const patch = { relationship: relationship.trim() || null, notes: notes.trim() || null, pinned }
    if (!imported) patch.display_name = displayName.trim() || person.display_name
    try { await api.updatePerson(person.id, patch); await onChanged(); setMsg('Saved.') }
    catch (e) { setMsg(e?.message || 'Couldn’t save.') }
    finally { setBusy(false) }
  }

  return (
    <Card title={person.display_name || 'Unnamed'} variant="sunken"
      eyebrow={imported ? 'From macOS Contacts' : 'Manual contact'}
      action={<Avatar name={person.display_name} tint={tintFor(person)}
        src={person.has_photo ? api.personPhotoUrl(person.id) : undefined} />}>
      <div className="kit-stack" style={{ gap: 14 }}>
        <section aria-label="Identity" className="kit-stack" style={{ gap: 10 }}>
          {imported ? (
            <>
              <p className="kit-muted" style={{ margin: 0, fontSize: 'var(--text-sm)', display: 'flex', gap: 6, alignItems: 'center' }}>
                <Icon name="apple" /> Synced from macOS Contacts — edit these in the Contacts app.
              </p>
              <ReadOnlyRow label="Name" value={person.display_name} />
              {person.organization && <ReadOnlyRow label="Organization" value={person.organization} />}
              {person.job_title && <ReadOnlyRow label="Title" value={person.job_title} />}
              {(person.emails || []).map((e, i) => <ReadOnlyRow key={`e${i}`} label={e.label || 'Email'} value={e.value} />)}
              {(person.phones || []).map((ph, i) => <ReadOnlyRow key={`p${i}`} label={ph.label || 'Phone'} value={ph.value} />)}
            </>
          ) : (
            <Field label="Name">
              <input aria-label="Name" value={displayName} style={INPUT_STYLE} onChange={(e) => setDisplayName(e.target.value)} />
            </Field>
          )}
        </section>

        <section aria-label="CRM details" className="kit-stack" style={{ gap: 10 }}>
          <Field label="Relationship">
            <input aria-label="Relationship" value={relationship} style={INPUT_STYLE} onChange={(e) => setRelationship(e.target.value)} />
          </Field>
          <Field label="Notes">
            <textarea aria-label="Notes" rows={3} value={notes} style={{ ...INPUT_STYLE, resize: 'vertical' }} onChange={(e) => setNotes(e.target.value)} />
          </Field>
          <Checkbox checked={pinned} onChange={(e) => setPinned(e.target.checked)} label="Pinned" />
        </section>

        <div aria-live="polite" style={SR_ONLY}>{msg}</div>
        {msg && <p role="status" className="kit-muted" style={{ margin: 0, fontSize: 'var(--text-sm)' }}>{msg}</p>}

        <div className="kit-inline" style={{ gap: 8 }}>
          <Button variant="primary" size="sm" disabled={busy} onClick={save}>{busy ? 'Saving…' : 'Save'}</Button>
          {!imported && (confirmDelete ? (
            <>
              <span className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>Delete this person?</span>
              <Button variant="secondary" size="sm" disabled={busy}
                onClick={async () => { setBusy(true); try { await api.deletePerson(person.id); await onDeleted() } catch (e) { setMsg(e?.message || 'Delete failed.'); setBusy(false) } }}>Delete</Button>
              <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(false)}>Cancel</Button>
            </>
          ) : (
            <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(true)}>Delete</Button>
          ))}
        </div>
      </div>
    </Card>
  )
}

export function CRMScreen({ onOpenConnectors }) {
  const [people, setPeople] = React.useState(null)
  const [contacts, setContacts] = React.useState(null)   // the macos_contacts connector card, or null
  const [error, setError] = React.useState('')
  const [q, setQ] = React.useState('')
  const [selectedId, setSelectedId] = React.useState(null)
  const [creating, setCreating] = React.useState(false)
  const [syncing, setSyncing] = React.useState(false)
  const [notice, setNotice] = React.useState('')

  const refresh = React.useCallback(async () => {
    try {
      const [page, cards] = await Promise.all([
        api.listPeople(),
        api.getConnectors().catch(() => []),
      ])
      const items = page?.items || []
      setPeople(items)
      // TODO(slice 2): store page.next_cursor + a "load more" control; slice 1
      // pages once (default limit) and does not paginate further.
      setContacts((cards || []).find((k) => k.name === 'macos_contacts') || null)
      setError('')
      return items
    } catch (e) {
      setError(e?.message || 'Couldn’t load your people.')
      throw e
    }
  }, [])

  React.useEffect(() => { refresh().catch(() => {}) }, [refresh])

  // Refetch when the user returns to the app/tab: a background startup sync or a
  // manual sync from Connectors may have changed the data while we were away.
  React.useEffect(() => {
    const onFocus = () => refresh().catch(() => {})
    const onVisible = () => { if (document.visibilityState === 'visible') refresh().catch(() => {}) }
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [refresh])

  // While a sync is in flight, poll until it settles so the list + banner update
  // the moment the (startup or manual) import completes. Self-clearing.
  const syncStatus = contacts?.sync_status
  React.useEffect(() => {
    if (syncStatus !== 'syncing') return undefined
    const id = setInterval(() => { refresh().catch(() => {}) }, 2500)
    return () => clearInterval(id)
  }, [syncStatus, refresh])

  const runSync = React.useCallback(async () => {
    setSyncing(true); setNotice('Syncing contacts…')
    try {
      await api.syncContacts()
      await refresh()
      setNotice('Contacts synced.')
    } catch (e) {
      setNotice(e?.message || 'Sync failed.')
    } finally {
      setSyncing(false)
    }
  }, [refresh])

  // ---- loading / hard-error gates ----
  if (people === null && !error) {
    return <Card variant="flat" aria-busy="true"><p className="kit-muted">Loading your people…</p></Card>
  }
  if (people === null && error) {
    return (
      <Card variant="flat" role="alert">
        <p className="kit-row__title">{error}</p>
        <div className="kit-inline" style={{ marginTop: 10 }}>
          <Button variant="primary" size="sm" iconLeft={<Icon name="refresh-cw" />}
            onClick={() => refresh().catch(() => {})}>Retry</Button>
        </div>
      </Card>
    )
  }

  const banner = syncBanner(contacts)
  const filtered = (people || []).filter((p) => matches(p, q))
  const selected = (people || []).find((p) => p.id === selectedId) || null
  const emptyAll = (people || []).length === 0
  const noMatches = !emptyAll && filtered.length === 0

  return (
    <div className="kit-grid" style={{ gridTemplateColumns: '1.5fr 1fr' }}>
      <Card
        title="People"
        eyebrow={`${(people || []).length} ${(people || []).length === 1 ? 'contact' : 'contacts'}`}
        action={
          <div className="kit-inline" style={{ gap: 8 }}>
            <div className="kit-search" style={{ width: 180 }}>
              <Icon name="search" />
              <input aria-label="Search people" placeholder="Search people"
                value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            <IconButton label="New person" onClick={() => { setCreating(true); setSelectedId(null) }}>
              <Icon name="plus" />
            </IconButton>
          </div>
        }
      >
        {/* Screen-reader status region for sync announcements. */}
        <div aria-live="polite" style={SR_ONLY}>{notice}</div>

        {banner && (
          <Card variant="flat" role="status" aria-busy={banner.busy ? 'true' : 'false'}
            style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12, background: 'var(--surface-sunken)' }}>
            <span className="kit-statline__ico" style={TONE_TINT[banner.tone]}><Icon name={banner.icon} /></span>
            <div style={{ flex: 1 }}>
              <p className="kit-row__title" style={{ fontSize: 'var(--text-sm)' }}>{banner.title}</p>
              {banner.detail && <p className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>{banner.detail}</p>}
            </div>
            {banner.denied && onOpenConnectors && (
              <Button variant="secondary" size="sm" onClick={onOpenConnectors}>Fix access</Button>
            )}
            {banner.retry && (
              <Button variant="secondary" size="sm" disabled={syncing}
                iconLeft={<Icon name="refresh-cw" />} onClick={runSync}>Sync now</Button>
            )}
          </Card>
        )}

        {emptyAll ? (
          <EmptyPeople contacts={contacts} onAdd={() => { setCreating(true); setSelectedId(null) }} onOpenConnectors={onOpenConnectors} />
        ) : noMatches ? (
          <div className="kit-stack" style={{ alignItems: 'center', padding: 24, textAlign: 'center', gap: 8 }}>
            <Icon name="search" />
            <p className="kit-row__title">No matches for “{q}”</p>
            <Button variant="ghost" size="sm" onClick={() => setQ('')}>Clear search</Button>
          </div>
        ) : (
          <ul className="kit-stack" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            {filtered.map((p) => (
              <li key={p.id}>
                <button type="button" className="kit-person" aria-pressed={p.id === selectedId}
                  style={{ width: '100%', background: 'none', border: 0, textAlign: 'left', cursor: 'pointer' }}
                  onClick={() => { setSelectedId(p.id); setCreating(false) }}>
                  <Avatar name={p.display_name} tint={tintFor(p)}
                    src={p.has_photo ? api.personPhotoUrl(p.id) : undefined} />
                  <div className="kit-person__main">
                    <p className="kit-person__name">
                      {p.display_name || 'Unnamed'}
                      {p.relationship && <Badge color="sky">{p.relationship}</Badge>}
                      {isImported(p) && <Badge color="neutral">Contacts</Badge>}
                    </p>
                    <p className="kit-person__sub">
                      {p.emails?.[0]?.value || p.phones?.[0]?.value || p.organization || '—'}
                    </p>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <div className="kit-col">
        {creating ? (
          <PersonEditor key="new" onCancel={() => setCreating(false)}
            onSaved={async (created) => { setCreating(false); await refresh(); setSelectedId(created.id) }} />
        ) : selected ? (
          <PersonDetail key={selected.id} person={selected} onChanged={refresh}
            onDeleted={async () => { setSelectedId(null); await refresh() }} />
        ) : (
          <Card title="Details" variant="sunken">
            <p className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>
              Select a person to see their details, or add someone new.
            </p>
          </Card>
        )}
      </div>
    </div>
  )
}
