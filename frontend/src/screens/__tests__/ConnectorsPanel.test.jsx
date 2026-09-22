import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
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
    oauthConnect: vi.fn(),
    moodleConnect: vi.fn(),
  },
}))

const localCard = (over = {}) => ({
  name: 'macos_contacts', label: 'Apple Contacts', auth_kind: 'local', configured: true,
  status: 'not_connected', access: 'denied', enabled: false, sync_status: 'disabled',
  last_sync_at: null, last_error: null, count: 0, items: [], connected_at: null,
  provider_user_id: null, can_write_email: null, ...over,
})

const tokenCard = (over = {}) => ({
  name: 'moodle', label: 'Moodle', auth_kind: 'token', configured: true,
  status: 'not_connected', connected_at: null, provider_user_id: null,
  can_write_email: null, items: [], ...over,
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

  // The disclosure is the text the user ticks before the FIRST sync, so it has to
  // match what the backend actually does. backend/app/tools.py ships five People
  // tools (list_people/get_person/create_person/update_person/log_contact) whose
  // payloads carry contact fields to Anthropic on any assistant turn about people,
  // and capture() feeds the turn to Mem0 (OpenAI embedder). There is deliberately
  // no second consent gate on that — enabling the import IS the opt-in.
  it('discloses that contact fields reach the AI provider, with no separate opt-in', async () => {
    api.getConnectors.mockResolvedValue([localCard()])
    render(<ConnectorsPanel onOpenKeys={() => {}} />)

    const disclosure = await screen.findByText(/read locally and read-only from the macOS Contacts app/i)
    expect(disclosure).toHaveTextContent(/Anthropic/)
    expect(disclosure).toHaveTextContent(/phone numbers/i)
    expect(disclosure).toHaveTextContent(/OpenAI/)
    // No gate may be implied: enabling the import is the whole consent.
    expect(disclosure).toHaveTextContent(/only opt-in/i)
    expect(disclosure).toHaveTextContent(/no separate AI switch/i)
  })

  it('never claims contacts are withheld from AI providers or third parties', async () => {
    api.getConnectors.mockResolvedValue([localCard()])
    render(<ConnectorsPanel onOpenKeys={() => {}} />)

    const text = (await screen.findByText(/read locally and read-only from the macOS Contacts app/i)).textContent
    // Fails if the pre-People-tools wording ("Contacts are never sent to any AI
    // provider or third-party service.") is ever reinstated in any form.
    expect(text).not.toMatch(/never sent to any/i)
    expect(text).not.toMatch(/never (sent|shared|leave|leaves|transmitted|uploaded)/i)
  })

  it('names the AI sharing in the acknowledgement the user actually ticks', async () => {
    api.getConnectors.mockResolvedValue([localCard()])
    render(<ConnectorsPanel onOpenKeys={() => {}} />)

    const ack = await screen.findByRole('checkbox', { name: /acknowledge/i })
    expect(ack.getAttribute('aria-label')).toMatch(/AI provider/i)
    expect(screen.getByText(/I understand where my contact data is stored/i))
      .toHaveTextContent(/AI provider/i)
  })

  it('shows the Full Disk Access denied state (not "unsupported") when access is denied but sync_status is unsupported', async () => {
    api.getConnectors.mockResolvedValue([localCard({
      enabled: true, access: 'denied', sync_status: 'unsupported',
    })])
    render(<ConnectorsPanel onOpenKeys={() => {}} />)

    expect(await screen.findByText(/full disk access is off/i)).toBeInTheDocument()
    expect(screen.queryByText(/contacts import isn.t available on this device/i)).toBeNull()
  })

  it('still renders the unavailable copy when configured is false, regardless of sync_status', async () => {
    api.getConnectors.mockResolvedValue([localCard({
      configured: false, access: 'denied', sync_status: 'unsupported',
    })])
    render(<ConnectorsPanel onOpenKeys={() => {}} />)

    expect(await screen.findByText(/contacts import isn.t available on this device/i)).toBeInTheDocument()
  })

  it('is exempt from the not-configured API-keys gate when unsupported on this device', async () => {
    api.getConnectors.mockResolvedValue([localCard({
      configured: false, access: 'unknown', sync_status: 'disabled',
    })])
    render(<ConnectorsPanel onOpenKeys={() => {}} />)

    // Local card renders its own "not available on this device" message…
    expect(await screen.findByText(/contacts import isn.t available on this device/i)).toBeInTheDocument()
    // …and must NOT also show the OAuth/Plaid "not configured" gate.
    expect(screen.queryByText(/API keys required/i)).toBeNull()
    expect(screen.queryByText(/Add API keys first/i)).toBeNull()
  })
})

describe('ConnectorsPanel — Moodle (token)', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders Sign in to Moodle and hides the paste input until toggled', async () => {
    api.getConnectors.mockResolvedValue([tokenCard()])
    render(<ConnectorsPanel onOpenKeys={() => {}} />)

    expect(await screen.findByRole('button', { name: /sign in to moodle/i })).toBeInTheDocument()
    expect(screen.queryByPlaceholderText('Paste wstoken')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: /paste a key instead/i }))
    expect(await screen.findByPlaceholderText('Paste wstoken')).toBeInTheDocument()
  })

  it('signs in via oauthConnect and opens the authorize URL, unblocked by a bad vault', async () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
    api.settingsGetSecrets.mockResolvedValue({ vault_ok: false })
    api.getConnectors.mockResolvedValue([tokenCard()])
    api.oauthConnect.mockResolvedValue({ authorize_url: 'https://moodle.example/launch' })
    render(<ConnectorsPanel onOpenKeys={() => {}} />)

    const signIn = await screen.findByRole('button', { name: /sign in to moodle/i })
    expect(signIn).toBeEnabled()
    fireEvent.click(signIn)

    await waitFor(() => expect(api.oauthConnect).toHaveBeenCalledTimes(1))
    expect(api.oauthConnect).toHaveBeenCalledWith('moodle')
    await waitFor(() => expect(openSpy).toHaveBeenCalledWith('https://moodle.example/launch', '_blank', 'noopener'))
  })

  it('shows the expired copy and the same sign-in button on needs_reauth', async () => {
    api.getConnectors.mockResolvedValue([tokenCard({ status: 'needs_reauth' })])
    render(<ConnectorsPanel onOpenKeys={() => {}} />)

    expect(await screen.findByText(/your moodle key expired — sign in again to get a fresh one\./i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign in to moodle/i })).toBeInTheDocument()
  })

  it('still supports the paste fallback behind the toggle', async () => {
    api.getConnectors.mockResolvedValue([tokenCard()])
    api.moodleConnect.mockResolvedValue({})
    render(<ConnectorsPanel onOpenKeys={() => {}} />)

    fireEvent.click(await screen.findByRole('button', { name: /paste a key instead/i }))
    const input = await screen.findByPlaceholderText('Paste wstoken')
    fireEvent.change(input, { target: { value: 'abc123' } })
    fireEvent.click(screen.getByRole('button', { name: /^connect$/i }))

    await waitFor(() => expect(api.moodleConnect).toHaveBeenCalledWith({ token: 'abc123' }))
  })
})
