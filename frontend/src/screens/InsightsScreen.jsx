/* Scuffed OS — Insights: derived WHOOP-style coaching cards.
   Owns its own state (App.jsx renders <InsightsScreen /> with the connectors
   callback only), mirroring FitnessScreen. /status gates the connection UI;
   /api/insights feeds the card feed. Reads are pure cache server-side, so the
   feed shows whatever the last sync generated. */
import React from 'react'
import { Card, Badge, IconButton, Button } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'
import { api } from '../lib/api.js'
import { NotConnectedCard, NeedsReauthBanner } from '../components/ConnectorEmptyState.jsx'

/* tone -> badge color + accent tint (warm palette) */
const TONE = {
  positive: { color: 'green', label: 'Good' },
  neutral: { color: 'honey', label: 'Steady' },
  caution: { color: 'clay', label: 'Heads up' },
}

/* signals_json -> compact metric chips, best-effort and label-mapped. */
const CHIP_LABEL = {
  recovery_pct: (v) => `Recovery ${v}%`,
  day_strain: (v) => `Strain ${v}`,
  sleep_quality_pct: (v) => `Sleep ${v}%`,
  sleep_hours: (v) => `${v} h`,
  hrv_ms: (v) => `HRV ${v} ms`,
  resting_hr: (v) => `RHR ${v} bpm`,
  baseline: (v) => `base ~${v}`,
}
function chips(signals) {
  return Object.entries(signals || {})
    .filter(([k, v]) => CHIP_LABEL[k] && v != null)
    .map(([k, v]) => CHIP_LABEL[k](v))
}

export function InsightsScreen({ onOpenConnectors }) {
  const [status, setStatus] = React.useState(null)
  const [day, setDay] = React.useState(null)
  const [busy, setBusy] = React.useState(false)

  const refresh = React.useCallback(() => {
    api.oauthStatus().then((s) => { if (s) setStatus(s) }).catch(() => {})
    api.insights().then((d) => { if (d) setDay(d) }).catch(() => {})
  }, [])
  React.useEffect(() => { refresh() }, [refresh])

  const whoop = (status?.providers || []).find((p) => p.provider === 'whoop') || null
  const connected = !!whoop
  const needsReauth = whoop?.status === 'needs_reauth'

  const regenerate = () => {
    setBusy(true)
    api.insightsRefresh()
      .then((d) => { if (d) setDay(d) })
      .catch(() => {})
      .finally(() => setBusy(false))
  }

  if (status && !connected && !needsReauth) {
    return (
      <NotConnectedCard title="Insights aren’t ready"
        blurb="Connect WHOOP to get daily recovery, sleep and strain coaching."
        onOpenConnectors={onOpenConnectors} icon="sparkles" />
    )
  }

  const cards = day?.cards || []
  return (
    <div className="kit-stack" style={{ gap: 'var(--gutter)' }}>
      {needsReauth && <NeedsReauthBanner onOpenConnectors={onOpenConnectors} />}

      <Card eyebrow="Your read on today" title="Insights"
        action={<IconButton label="Refresh" size="sm" onClick={regenerate} disabled={busy}>
          <Icon name="refresh-cw" /></IconButton>}>
        {cards.length === 0 && (
          <p className="kit-muted" style={{ marginTop: 6 }}>
            No read yet — it’ll appear after your next sync.
          </p>
        )}
        <div className="kit-stack" style={{ gap: 12, marginTop: cards.length ? 8 : 0 }}>
          {cards.map((c) => {
            const tone = TONE[c.tone] || TONE.neutral
            return (
              <div key={c.id} className="kit-insight" style={{ alignItems: 'flex-start' }}>
                <div className="kit-insight__icon"><Icon name="sparkles" /></div>
                <div style={{ flex: 1 }}>
                  <div className="kit-inline" style={{ gap: 8, marginBottom: 4 }}>
                    <strong style={{ color: 'var(--text-strong)' }}>{c.headline}</strong>
                    <Badge color={tone.color} dot>{tone.label}</Badge>
                  </div>
                  <p style={{ margin: 0 }}>{c.body}</p>
                  {chips(c.signals).length > 0 && (
                    <div className="kit-inline" style={{ gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
                      {chips(c.signals).map((t, i) => (
                        <span key={i} className="kit-navitem__badge" style={{ position: 'static' }}>{t}</span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </Card>
    </div>
  )
}
