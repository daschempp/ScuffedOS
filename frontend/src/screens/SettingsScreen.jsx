/* Scuffed OS — Settings shell (M9 Slice 1). Two tabs: Connectors (unified
   sign-in surface) and API keys (the M8 secrets UI, now ApiKeysPanel). The tab
   bar renders ABOVE ApiKeysPanel's vault-locked / first-run early returns so
   Connectors stays reachable even when the vault is locked or empty. */
import React from 'react'
import { ApiKeysPanel } from './ApiKeysPanel.jsx'
import { ConnectorsPanel } from './ConnectorsPanel.jsx'

const TABS = [
  { id: 'connectors', label: 'Connectors' },
  { id: 'keys', label: 'API keys' },
]

export function SettingsScreen({ tab = 'connectors', onTabChange }) {
  const active = tab === 'keys' ? 'keys' : 'connectors'
  return (
    <div className="kit-stack" style={{ gap: 'var(--gutter)' }}>
      <div role="tablist" className="kit-inline" style={{ gap: 4, borderBottom: '1px solid var(--paper-300)', paddingBottom: 0 }}>
        {TABS.map((t) => {
          const on = active === t.id
          return (
            <button
              key={t.id}
              role="tab"
              aria-selected={on}
              onClick={() => onTabChange && onTabChange(t.id)}
              style={{
                appearance: 'none', border: 'none', background: 'none', cursor: 'pointer',
                padding: '8px 14px', marginBottom: -1,
                fontFamily: 'var(--font-display)', fontSize: 'var(--text-sm)',
                color: on ? 'var(--text-strong)' : 'var(--text-muted)',
                borderBottom: on ? '2px solid var(--accent-text)' : '2px solid transparent',
              }}
            >
              {t.label}
            </button>
          )
        })}
      </div>
      {active === 'keys' ? <ApiKeysPanel /> : <ConnectorsPanel onOpenKeys={() => onTabChange && onTabChange('keys')} />}
    </div>
  )
}
