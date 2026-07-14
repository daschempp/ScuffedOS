import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { ConnectorsPanel } from '../ConnectorsPanel.jsx'
import { api } from '../../lib/api.js'

vi.mock('@tauri-apps/api/core', () => ({ isTauri: () => false }))
vi.mock('../../lib/api.js', () => ({
  api: {
    getConnectors: vi.fn(),
    settingsGetSecrets: vi.fn(),
    enableContacts: vi.fn(),
    disconnectContacts: vi.fn(),
    forgetContacts: vi.fn(),
    syncContacts: vi.fn(),
  },
}))

const localCard = (over = {}) => ({
  name: 'macos_contacts', label: 'Apple Contacts', auth_kind: 'local', configured: true,
  status: 'not_connected', access: 'denied', enabled: false, sync_status: 'disabled',
  last_sync_at: null, last_error: null, count: 0, items: [], connected_at: null,
  provider_user_id: null, can_write_email: null, ...over,
})

beforeEach(() => {
  vi.clearAllMocks()
  api.settingsGetSecrets.mockResolvedValue({ vault_ok: true })
})

describe('ConnectorsPanel — macOS Contacts (local)', () => {
  it('offers Grant Full Disk Access when denied, exempt from the vault gate', async () => {
    api.settingsGetSecrets.mockResolvedValue({ vault_ok: false })   // OAuth connects gated…
    api.getConnectors.mockResolvedValue([localCard({ access: 'denied' })])
    render(<ConnectorsPanel onOpenKeys={() => {}} />)
    // …but the local card still exposes Grant FDA regardless of the vault state
    expect(await screen.findByRole('button', { name: /grant full disk access/i })).toBeInTheDocument()
  })

  it('gates Enable on acknowledging the PostgreSQL storage disclosure', async () => {
    api.getConnectors.mockResolvedValue([localCard()])
    api.enableContacts.mockResolvedValue({})
    render(<ConnectorsPanel onOpenKeys={() => {}} />)

    const enable = await screen.findByRole('button', { name: /enable contacts import/i })
    expect(enable).toBeDisabled()                                    // no acknowledgement yet
    expect(screen.getByText(/postgresql database/i)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('checkbox', { name: /acknowledge/i }))
    expect(enable).toBeEnabled()

    fireEvent.click(enable)
    await waitFor(() => expect(api.enableContacts).toHaveBeenCalledTimes(1))
  })
})
