/* Scuffed OS — shared connector empty/needs-reauth states (M9 Slice 1). Data
   screens render these in place of their old inline connect UI; both deep-link
   to Settings › Connectors via onOpenConnectors. */
import React from 'react'
import { Card, Button } from './ui.jsx'
import { Icon } from '../lib/Icon.jsx'

export function NotConnectedCard({ icon = 'unplug', title, blurb, onOpenConnectors }) {
  return (
    <Card variant="flat" style={{ textAlign: 'center', padding: '48px 24px' }}>
      <div style={{ display: 'inline-flex', width: 56, height: 56, borderRadius: 'var(--radius-lg)', background: 'var(--accent-soft)', color: 'var(--accent-text)', alignItems: 'center', justifyContent: 'center', marginBottom: 14 }}>
        <Icon name={icon} />
      </div>
      <h3 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-xl)', color: 'var(--text-strong)', margin: '0 0 6px' }}>{title}</h3>
      <p className="kit-muted" style={{ maxWidth: 380, margin: '0 auto 18px' }}>{blurb}</p>
      <Button variant="primary" iconLeft={<Icon name="settings" />} onClick={onOpenConnectors}>
        Set up in Settings › Connectors
      </Button>
    </Card>
  )
}

export function NeedsReauthBanner({ onOpenConnectors }) {
  return (
    <Card variant="flat" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
      <span className="kit-statline__ico" style={{ background: 'var(--clay-100)', color: 'var(--clay-600)' }}>
        <Icon name="alert-triangle" />
      </span>
      <p className="kit-muted" style={{ flex: 1 }}>Connection needs re-authorizing — fix it in Settings › Connectors.</p>
      <Button variant="secondary" size="sm" onClick={onOpenConnectors}>Open Connectors</Button>
    </Card>
  )
}
