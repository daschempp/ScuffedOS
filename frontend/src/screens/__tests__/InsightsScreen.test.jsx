import React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { InsightsScreen } from '../InsightsScreen.jsx'
import { api } from '../../lib/api.js'

vi.mock('../../lib/api.js', () => ({
  api: {
    oauthStatus: vi.fn(),
    insights: vi.fn(),
    insightsRefresh: vi.fn(),
  },
}))

const connectedStatus = {
  providers: [{ provider: 'whoop', status: 'connected', last_sync_at: '2026-07-21T12:00:00Z' }],
}

const card = (overrides = {}) => ({
  id: 1,
  code: 'recovery_band',
  tone: 'positive',
  headline: 'Recovery is green',
  body: 'You are primed for a strong day.',
  signals: { recovery_pct: 75, hrv_ms: 64 },
  source: 'rules',
  ...overrides,
})

beforeEach(() => {
  vi.clearAllMocks()
  api.oauthStatus.mockResolvedValue(connectedStatus)
  api.insights.mockResolvedValue({ date: '2026-07-21', cards: [] })
})

describe('InsightsScreen', () => {
  it('sends disconnected users to connector setup', async () => {
    api.oauthStatus.mockResolvedValue({ providers: [] })
    const onOpenConnectors = vi.fn()

    render(<InsightsScreen onOpenConnectors={onOpenConnectors} />)

    expect(await screen.findByText(/insights aren.t ready/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /set up in settings/i }))
    expect(onOpenConnectors).toHaveBeenCalledTimes(1)
  })

  it('renders cached cards with tone and metric chips', async () => {
    api.insights.mockResolvedValue({ date: '2026-07-21', cards: [card()] })

    render(<InsightsScreen />)

    expect(await screen.findByText('Recovery is green')).toBeInTheDocument()
    expect(screen.getByText('Good')).toBeInTheDocument()
    expect(screen.getByText('Recovery 75%')).toBeInTheDocument()
    expect(screen.getByText('HRV 64 ms')).toBeInTheDocument()
  })

  it('disables refresh while regenerating and replaces the cached cards', async () => {
    api.insights.mockResolvedValue({ date: '2026-07-21', cards: [card()] })
    let finishRefresh
    api.insightsRefresh.mockReturnValue(new Promise((resolve) => { finishRefresh = resolve }))

    render(<InsightsScreen />)
    await screen.findByText('Recovery is green')

    const refresh = screen.getByRole('button', { name: 'Refresh' })
    fireEvent.click(refresh)
    expect(refresh).toBeDisabled()
    expect(api.insightsRefresh).toHaveBeenCalledTimes(1)

    finishRefresh({
      date: '2026-07-21',
      cards: [card({ id: 2, tone: 'caution', headline: 'Recovery needs care' })],
    })
    expect(await screen.findByText('Recovery needs care')).toBeInTheDocument()
    expect(screen.queryByText('Recovery is green')).not.toBeInTheDocument()
    await waitFor(() => expect(refresh).toBeEnabled())
  })

  it('re-enables refresh and preserves cached cards after a failed regeneration', async () => {
    api.insights.mockResolvedValue({ date: '2026-07-21', cards: [card()] })
    api.insightsRefresh.mockRejectedValue(new Error('refresh failed'))

    render(<InsightsScreen />)
    await screen.findByText('Recovery is green')

    const refresh = screen.getByRole('button', { name: 'Refresh' })
    fireEvent.click(refresh)
    expect(refresh).toBeDisabled()

    await waitFor(() => expect(refresh).toBeEnabled())
    expect(screen.getByText('Recovery is green')).toBeInTheDocument()
  })
})
