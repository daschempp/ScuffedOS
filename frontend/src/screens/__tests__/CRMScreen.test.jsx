import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
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

beforeEach(() => {
  vi.clearAllMocks()
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
})
