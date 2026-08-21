import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { CRMScreen } from '../CRMScreen.jsx'
import { api } from '../../lib/api.js'

vi.mock('../../lib/api.js', () => ({
  api: {
    listPeople: vi.fn(),
    getConnectors: vi.fn(),
    personPhotoUrl: (id) => `/api/people/${id}/photo`,
    syncContacts: vi.fn(),
    createPerson: vi.fn(),
    updatePerson: vi.fn(),
    deletePerson: vi.fn(),
  },
}))

const importedPerson = {
  id: 7, source: 'macos_contacts', source_id: 'UID-7', display_name: 'Jane Doe',
  first_name: 'Jane', last_name: 'Doe', nickname: '', organization: 'Acme', job_title: '',
  phones: [{ value: '+15551234567', label: 'Mobile', normalized: '+15551234567' }],
  emails: [{ value: 'jane@icloud.com', label: 'Home', normalized: 'jane@icloud.com' }],
  has_photo: false, relationship: null, relationship_strength: null, notes: null,
  pinned: false, last_contacted_at: null, removed_from_source_at: null,
  created_at: '2026-07-13T00:00:00Z', updated_at: '2026-07-13T00:00:00Z',
}

// Sorts after Jane, so a 50-row first page would never contain them: this person
// only ever arrives via a later cursor page or a server-side search.
const pageTwoPerson = {
  id: 11, source: 'manual', source_id: null, display_name: 'Zeb Zephyr',
  first_name: 'Zeb', last_name: 'Zephyr', nickname: '', organization: '', job_title: '',
  phones: [], emails: [], has_photo: false, relationship: null, relationship_strength: null,
  notes: null, pinned: false, last_contacted_at: null, removed_from_source_at: null,
  created_at: '2026-07-13T00:00:00Z', updated_at: '2026-07-13T00:00:00Z',
}

const searchBox = () => screen.getByLabelText('Search people')

beforeEach(() => {
  // reset, not clear: several tests queue mockResolvedValueOnce values, and a
  // leftover queued page would otherwise pre-empt the next test's implementation.
  vi.resetAllMocks()
  api.getConnectors.mockResolvedValue([])   // no contacts card by default
})

describe('CRMScreen', () => {
  it('shows a loading state, then the empty onboarding when there are no people', async () => {
    let resolve
    api.listPeople.mockReturnValue(new Promise((r) => { resolve = r }))
    render(<CRMScreen />)
    expect(screen.getByText(/loading your people/i)).toBeInTheDocument()

    resolve({ items: [], next_cursor: null })
    expect(await screen.findByText(/no people yet/i)).toBeInTheDocument()
    // the empty CTA offers a manual add (distinct label from the header's "New person")
    expect(screen.getByRole('button', { name: /add a person/i })).toBeInTheDocument()
  })

  it('renders imported identity read-only with a macOS Contacts note; CRM fields stay editable', async () => {
    api.listPeople.mockResolvedValue({ items: [importedPerson], next_cursor: null })
    render(<CRMScreen />)

    const row = await screen.findByRole('button', { name: /jane doe/i })
    fireEvent.click(row)

    // read-only identity: the "from macOS Contacts" note + the email shown as text (no input).
    // Scoped to the identity section: the same email also previews in the list row's
    // subtitle while that row stays visible next to the open detail panel, so an
    // unscoped screen.getByText('jane@icloud.com') would match two nodes at once.
    const syncNote = await screen.findByText(/synced from macos contacts/i)
    const identitySection = syncNote.closest('section')
    expect(within(identitySection).getByText('jane@icloud.com')).toBeInTheDocument()
    expect(screen.queryByLabelText('Email')).toBeNull()      // imported email is NOT an editable field
    expect(screen.queryByLabelText('Name')).toBeNull()       // imported identity name is read-only

    // CRM-native field IS editable
    expect(screen.getByLabelText(/relationship/i)).toBeInTheDocument()
  })

  it('searches on the server, coalescing keystrokes, so matches past the first page are found', async () => {
    api.listPeople.mockResolvedValueOnce({ items: [importedPerson], next_cursor: 'page-2' })
    render(<CRMScreen />)
    await screen.findByRole('button', { name: /jane doe/i })
    expect(api.listPeople).toHaveBeenCalledTimes(1)

    api.listPeople.mockResolvedValueOnce({ items: [pageTwoPerson], next_cursor: null })
    fireEvent.change(searchBox(), { target: { value: 'z' } })
    fireEvent.change(searchBox(), { target: { value: 'ze' } })
    fireEvent.change(searchBox(), { target: { value: 'zeb' } })

    // Zeb is not in the page we already hold — only a server-side q can surface them.
    expect(await screen.findByRole('button', { name: /zeb zephyr/i })).toBeInTheDocument()
    expect(api.listPeople).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'zeb' }))
    expect(api.listPeople).toHaveBeenCalledTimes(2)   // three keystrokes, one request
    expect(screen.queryByRole('button', { name: /jane doe/i })).toBeNull()
  })

  it('holds a request until the typing settles, then asks once for the settled text', async () => {
    // Fake timers here (and only here) so the debounce window is observable
    // without pinning the exact delay: nothing goes out mid-word, one request
    // goes out once the box stops changing.
    vi.useFakeTimers()
    try {
      api.listPeople.mockResolvedValue({ items: [importedPerson], next_cursor: null })
      render(<CRMScreen />)
      await act(async () => { await vi.advanceTimersByTimeAsync(0) })
      expect(api.listPeople).toHaveBeenCalledTimes(1)

      fireEvent.change(searchBox(), { target: { value: 'ze' } })
      await act(async () => { await vi.advanceTimersByTimeAsync(120) })
      expect(api.listPeople).toHaveBeenCalledTimes(1)   // mid-word: still holding

      fireEvent.change(searchBox(), { target: { value: 'zeb' } })
      await act(async () => { await vi.advanceTimersByTimeAsync(500) })
      expect(api.listPeople).toHaveBeenCalledTimes(2)
      expect(api.listPeople).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'zeb' }))
    } finally {
      vi.useRealTimers()
    }
  })

  it('keeps "no matches" distinct from the empty-onboarding state when a search finds nobody', async () => {
    api.listPeople.mockResolvedValueOnce({ items: [importedPerson], next_cursor: null })
    render(<CRMScreen />)
    await screen.findByRole('button', { name: /jane doe/i })

    api.listPeople.mockResolvedValueOnce({ items: [], next_cursor: null })
    fireEvent.change(searchBox(), { target: { value: 'nobody' } })

    expect(await screen.findByText(/no matches for/i)).toBeInTheDocument()
    expect(screen.queryByText(/no people yet/i)).toBeNull()

    // clearing the search goes back to the server for the unfiltered first page
    api.listPeople.mockResolvedValueOnce({ items: [importedPerson], next_cursor: null })
    fireEvent.click(screen.getByRole('button', { name: /clear search/i }))
    expect(await screen.findByRole('button', { name: /jane doe/i })).toBeInTheDocument()
  })

  it('appends the next cursor page and drops the control once next_cursor is null', async () => {
    api.listPeople
      .mockResolvedValueOnce({ items: [importedPerson], next_cursor: 'cursor-1' })
      .mockResolvedValueOnce({ items: [pageTwoPerson], next_cursor: null })
    render(<CRMScreen />)

    fireEvent.click(await screen.findByRole('button', { name: /load more/i }))

    expect(await screen.findByRole('button', { name: /zeb zephyr/i })).toBeInTheDocument()
    expect(api.listPeople).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: 'cursor-1' }))
    expect(screen.getByRole('button', { name: /jane doe/i })).toBeInTheDocument()   // appended, not replaced
    await waitFor(() => expect(screen.queryByRole('button', { name: /load more/i })).toBeNull())
  })

  it('surfaces a failed search instead of letting the previous list read as the answer', async () => {
    api.listPeople.mockResolvedValueOnce({ items: [importedPerson], next_cursor: null })
    render(<CRMScreen />)
    await screen.findByRole('button', { name: /jane doe/i })

    api.listPeople.mockRejectedValueOnce(new Error('Search is down.'))
    fireEvent.change(searchBox(), { target: { value: 'zzz' } })

    // The rows we still hold answer the *old* query, so the failure has to be on
    // screen — otherwise Jane silently reads as the result for "zzz".
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/search is down/i)
    expect(screen.getByRole('button', { name: /jane doe/i })).toBeInTheDocument()

    api.listPeople.mockResolvedValueOnce({ items: [pageTwoPerson], next_cursor: null })
    fireEvent.click(within(alert).getByRole('button', { name: /retry/i }))
    expect(await screen.findByRole('button', { name: /zeb zephyr/i })).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText(/search is down/i)).toBeNull())
  })

  it('never lets a slow response for an abandoned query overwrite the newer one', async () => {
    const pending = {}
    api.listPeople.mockImplementation((params = {}) => new Promise((resolve) => {
      pending[params.q || ''] = resolve
    }))
    render(<CRMScreen />)
    await waitFor(() => expect(pending['']).toBeDefined())
    await act(async () => { pending['']({ items: [importedPerson], next_cursor: null }) })

    fireEvent.change(searchBox(), { target: { value: 'jan' } })
    await waitFor(() => expect(pending.jan).toBeDefined())
    fireEvent.change(searchBox(), { target: { value: 'zeb' } })
    await waitFor(() => expect(pending.zeb).toBeDefined())

    // newest query answers first...
    await act(async () => { pending.zeb({ items: [pageTwoPerson], next_cursor: null }) })
    expect(screen.getByRole('button', { name: /zeb zephyr/i })).toBeInTheDocument()

    // ...and the abandoned one straggles in afterwards; it must be dropped.
    await act(async () => { pending.jan({ items: [importedPerson], next_cursor: 'stale' }) })
    expect(screen.getByRole('button', { name: /zeb zephyr/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /jane doe/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /load more/i })).toBeNull()
  })
})
