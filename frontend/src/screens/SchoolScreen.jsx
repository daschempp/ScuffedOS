/* Scuffed OS — School (live, synced with NC State WolfWare Moodle).
   Owns its own state (App.jsx renders <SchoolScreen /> with no props),
   mirroring EmailScreen's in-component fetch convention. /api/oauth/status
   drives which connection state renders; the /api/moodle/* reads feed the
   course list, deadline timeline, grades, announcements and notifications.
   Every read comes straight from the moodle_* tables server-side (never a
   live Moodle call), so it works while a sync is mid-flight or Moodle is
   down — it shows what's landed. Read-only this slice: no submit, post, or
   message send. The wstoken is pasted once and stays server-side; it never
   reaches the client again. NOTE: this is the Task-16 wiring stub — Task 17
   replaces the body with the full connect/timeline/grades ladder. */
import React from 'react'
import { Card, Button } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'
import { api } from '../lib/api.js'

export function SchoolScreen() {
  const connect = () => {
    // Placeholder — the real paste-field connect flow lands in Task 17.
    // Referencing api here keeps the import used so the stub builds cleanly.
    if (api.moodleConnect) return
  }
  return (
    <Card variant="flat" style={{ textAlign: 'center', padding: '56px 24px' }}>
      <div style={{ display: 'inline-flex', width: 56, height: 56, borderRadius: 'var(--radius-lg)', background: 'var(--accent-soft)', color: 'var(--accent-text)', alignItems: 'center', justifyContent: 'center', marginBottom: 14 }}>
        <Icon name="graduation-cap" />
      </div>
      <h3 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-xl)', color: 'var(--text-strong)', margin: '0 0 6px' }}>Connect Moodle</h3>
      <p className="kit-muted" style={{ maxWidth: 380, margin: '0 auto 18px' }}>Sync your WolfWare courses, deadlines and grades into Scuffed OS. Read-only — your token stays server-side and message bodies are never stored.</p>
      <Button variant="primary" iconLeft={<Icon name="graduation-cap" />} onClick={connect}>Connect Moodle</Button>
    </Card>
  )
}
