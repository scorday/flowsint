// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  type AdminEnricher,
  enricherAdministrationKeys,
  enricherAdministrationService
} from '@/api/enricher-administration-service'
import { EnricherAdministration } from './enricher-administration'

vi.mock('@/api/enricher-administration-service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/enricher-administration-service')>()),
  enricherAdministrationService: { access: vi.fn(), list: vi.fn(), setVisibility: vi.fn() }
}))
vi.mock('@/platform/runtime-config', () => ({ isAvl4: true }))

const rows: AdminEnricher[] = [
  {
    id: 'dns',
    kind: 'builtin',
    name: 'DNS lookup',
    description: 'Resolve a hostname',
    providers: ['DNS resolver'],
    api_key_requirement: 'not_required',
    api_key_notes: null,
    category: 'network',
    input_type: 'domain',
    output_type: 'ip',
    is_visible: true
  },
  {
    id: 'template-1',
    kind: 'template',
    name: 'Email search',
    description: 'Find associated accounts',
    providers: ['Accounts API', 'Directory API'],
    api_key_requirement: 'conditional',
    api_key_notes: 'ACCOUNTS_API_KEY is needed only for the private lookup method.',
    category: 'social',
    input_type: 'email',
    output_type: 'account',
    is_visible: false
  }
]
let client: QueryClient
beforeEach(() => {
  vi.clearAllMocks()
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } }
  })
  vi.mocked(enricherAdministrationService.access).mockResolvedValue({ can_manage: true })
  vi.mocked(enricherAdministrationService.list).mockResolvedValue(rows)
  Element.prototype.scrollIntoView = vi.fn()
  Element.prototype.hasPointerCapture = vi.fn(() => false)
  Element.prototype.setPointerCapture = vi.fn()
  Element.prototype.releasePointerCapture = vi.fn()
})
afterEach(() => {
  cleanup()
  client.clear()
})
function mount() {
  return render(
    <QueryClientProvider client={client}>
      <EnricherAdministration />
    </QueryClientProvider>
  )
}
async function inventory() {
  return screen.findByRole('table', { name: 'All enrichers' })
}
async function chooseFilter(name: string, option: string) {
  fireEvent.keyDown(screen.getByRole('combobox', { name }), { key: 'ArrowDown' })
  fireEvent.click(await screen.findByRole('option', { name: option }))
}

describe('Enricher administration', () => {
  it('waits for server capability before requesting the full catalog', async () => {
    vi.mocked(enricherAdministrationService.access).mockReturnValue(new Promise(() => {}))
    mount()
    expect(screen.getByRole('status').textContent).toContain('Loading')
    expect(enricherAdministrationService.list).not.toHaveBeenCalled()
  })

  it('shows all categories together in one flat table in API order with counts and visibility controls', async () => {
    mount()
    const table = await inventory()
    expect(screen.getAllByRole('table')).toHaveLength(1)
    const dataRows = within(table).getAllByRole('row').slice(1)
    expect(dataRows.map((row) => within(row).getByRole('button').textContent)).toEqual([
      'DNS lookup',
      'Email search'
    ])
    expect(within(dataRows[0]).getByText('network')).toBeTruthy()
    expect(within(dataRows[1]).getByText('social')).toBeTruthy()
    expect(within(table).getByRole('columnheader', { name: 'Category' })).toBeTruthy()
    expect(within(table).getAllByRole('switch')).toHaveLength(2)
    expect(
      within(table)
        .getByRole('switch', { name: /Email search/ })
        .getAttribute('aria-checked')
    ).toBe('false')
    expect(screen.getByText(/current AVL4 project/)).toBeTruthy()
    expect(screen.getByText('Showing 2 of 2 enrichers')).toBeTruthy()
    const counts = screen.getByRole('group', { name: 'Enricher counts' })
    expect(within(counts).getByText('All').textContent).toBe('All 2')
    expect(within(counts).getByText('Visible').textContent).toBe('Visible 1')
    expect(within(counts).getByText('Hidden').textContent).toBe('Hidden 1')
  })

  it('searches both original category names and their friendly labels', async () => {
    vi.mocked(enricherAdministrationService.list).mockResolvedValue([
      { ...rows[0], category: 'account_lookup' }
    ])
    mount()
    await inventory()
    const search = screen.getByRole('textbox', { name: 'Search enrichers' })
    for (const value of ['account lookup', 'account_lookup']) {
      fireEvent.change(search, { target: { value } })
      expect(screen.getByRole('table', { name: 'All enrichers' })).toBeTruthy()
      expect(screen.getByRole('switch', { name: /DNS lookup/ })).toBeTruthy()
    }
  })

  it.each(['hostname', 'network', 'domain', 'ip'])(
    'searches description, category and IO in the flat table (%s)',
    async (term) => {
      mount()
      await inventory()
      fireEvent.change(screen.getByRole('textbox', { name: 'Search enrichers' }), {
        target: { value: term }
      })
      expect(screen.queryByText('Email search')).toBeNull()
      expect(screen.getByRole('table', { name: 'All enrichers' })).toBeTruthy()
    }
  )

  it('combines kind and visibility filters and restores the full table from empty results', async () => {
    mount()
    await inventory()
    await chooseFilter('Enricher kind', 'Template')
    expect(screen.queryByRole('button', { name: 'View details for DNS lookup' })).toBeNull()
    expect(screen.getByRole('switch', { name: /Email search/ })).toBeTruthy()
    await chooseFilter('Visibility filter', 'Visible')
    expect(screen.getByText('No matching enrichers')).toBeTruthy()
    expect(screen.queryByRole('table')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(screen.getAllByRole('switch')).toHaveLength(2)
    await chooseFilter('Visibility filter', 'Hidden')
    expect(screen.getByRole('switch', { name: /Email search/ })).toBeTruthy()
    expect(screen.queryByRole('switch', { name: /DNS lookup/ })).toBeNull()
  })

  it.each([
    ['required', 'Required'],
    ['optional', 'Optional'],
    ['conditional', 'Conditional'],
    ['not_required', 'Not required'],
    ['unknown', 'Unknown']
  ] as const)(
    'renders provider metadata and API key status %s independently of visibility',
    async (requirement, label) => {
      vi.mocked(enricherAdministrationService.list).mockResolvedValue([
        { ...rows[1], api_key_requirement: requirement }
      ])
      mount()
      await inventory()
      const table = screen.getByRole('table', { name: 'All enrichers' })
      expect(within(table).getByRole('columnheader', { name: 'Provider' })).toBeTruthy()
      expect(within(table).getByRole('columnheader', { name: 'API key' })).toBeTruthy()
      expect(within(table).getByText('Accounts API')).toBeTruthy()
      expect(within(table).getByText('Directory API')).toBeTruthy()
      expect(within(table).getByText(label)).toBeTruthy()
      expect(within(table).getByRole('switch').getAttribute('aria-checked')).toBe('false')
    }
  )

  it('searches named providers across all rows', async () => {
    mount()
    await inventory()
    fireEvent.change(screen.getByRole('textbox', { name: 'Search enrichers' }), {
      target: { value: 'directory api' }
    })
    expect(screen.queryByRole('button', { name: 'View details for DNS lookup' })).toBeNull()
    expect(screen.getByRole('table', { name: 'All enrichers' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'View details for Email search' })).toBeTruthy()
  })

  it('shows full description and metadata in a closeable details dialog', async () => {
    const description =
      'Find accounts associated with the supplied email.\n\nThe private lookup method uses the configured API key.'
    vi.mocked(enricherAdministrationService.list).mockResolvedValue([{ ...rows[1], description }])
    mount()
    await inventory()
    expect(screen.queryByText(/Find accounts associated with/)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'View details for Email search' }))
    const dialog = screen.getByRole('dialog', { name: 'Email search' })
    expect(within(dialog).getByText(/Find accounts associated with/).textContent).toBe(description)
    expect(within(dialog).getByText('Accounts API, Directory API')).toBeTruthy()
    expect(within(dialog).getByText('Conditional')).toBeTruthy()
    expect(within(dialog).getByText(rows[1].api_key_notes!)).toBeTruthy()
    for (const label of ['Kind', 'Category', 'Input', 'Output'])
      expect(within(dialog).getByText(label)).toBeTruthy()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'View details for Email search' }))
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(enricherAdministrationService.setVisibility).not.toHaveBeenCalled()
  })

  it('explains missing description and provider neutrally in details', async () => {
    vi.mocked(enricherAdministrationService.list).mockResolvedValue([
      { ...rows[0], description: null, providers: [], api_key_requirement: 'unknown' }
    ])
    mount()
    await inventory()
    expect(screen.getByLabelText('No named provider').textContent).toBe('—')
    fireEvent.click(screen.getByRole('button', { name: 'View details for DNS lookup' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('No description available.')).toBeTruthy()
    expect(within(dialog).getByText('No named external provider specified.')).toBeTruthy()
    expect(within(dialog).getByText('Unknown')).toBeTruthy()
  })

  it('uses the saved response, retains hidden rows and invalidates every catalog cache', async () => {
    let finish!: (row: AdminEnricher) => void
    vi.mocked(enricherAdministrationService.setVisibility).mockReturnValue(
      new Promise((resolve) => {
        finish = resolve
      })
    )
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    mount()
    await inventory()
    const toggle = screen.getByRole('switch', { name: /DNS lookup/ })
    fireEvent.click(toggle)
    expect(screen.queryByRole('dialog')).toBeNull()
    await waitFor(() => expect(toggle.hasAttribute('disabled')).toBe(true))
    expect(toggle.getAttribute('aria-checked')).toBe('true')
    expect(screen.getByRole('switch', { name: /Email search/ }).hasAttribute('disabled')).toBe(
      false
    )
    finish({
      ...rows[0],
      is_visible: false,
      providers: ['Updated provider'],
      api_key_requirement: 'required',
      api_key_notes: 'UPDATED_PROVIDER_API_KEY must be configured.'
    })
    await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('false'))
    expect(screen.getByText('DNS lookup')).toBeTruthy()
    expect(screen.getByText('Updated provider')).toBeTruthy()
    expect(screen.getByText('Required')).toBeTruthy()
    expect(enricherAdministrationService.setVisibility).toHaveBeenCalledWith(rows[0], false)
    for (const queryKey of [
      ['enrichers'],
      ['raw_material'],
      ['actionItems'],
      ['template', 'enrichers']
    ])
      expect(invalidate).toHaveBeenCalledWith({ queryKey })
    expect(
      client.getQueryData<AdminEnricher[]>(enricherAdministrationKeys.list)?.[0].is_visible
    ).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'View details for DNS lookup' }))
    expect(
      within(screen.getByRole('dialog')).getByText('UPDATED_PROVIDER_API_KEY must be configured.')
    ).toBeTruthy()
  })

  it('shows a row error on failure, preserves its value and allows retry', async () => {
    let reject!: (error: Error) => void
    vi.mocked(enricherAdministrationService.setVisibility).mockReturnValue(
      new Promise((_, rejectUpdate) => {
        reject = rejectUpdate
      })
    )
    mount()
    await inventory()
    const toggle = screen.getByRole('switch', { name: /DNS lookup/ })
    fireEvent.click(toggle)
    await waitFor(() => expect(toggle.hasAttribute('disabled')).toBe(true))
    expect(screen.getByRole('switch', { name: /Email search/ }).hasAttribute('disabled')).toBe(
      false
    )
    reject(new Error('offline'))
    await screen.findByText(/Couldn't save visibility/)
    expect(toggle.getAttribute('aria-checked')).toBe('true')
    expect(toggle.hasAttribute('disabled')).toBe(false)
    vi.mocked(enricherAdministrationService.setVisibility).mockResolvedValue({
      ...rows[0],
      is_visible: false
    })
    fireEvent.click(toggle)
    await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('false'))
    expect(screen.queryByText(/Couldn't save visibility/)).toBeNull()
  })

  it('denies access without fetching or showing managed rows', async () => {
    vi.mocked(enricherAdministrationService.access).mockResolvedValue({ can_manage: false })
    mount()
    await screen.findByText('Administrator access required')
    expect(enricherAdministrationService.list).not.toHaveBeenCalled()
    expect(screen.queryByRole('table', { hidden: true })).toBeNull()
  })

  it('shows a forbidden state when the server revokes administrator access', async () => {
    vi.mocked(enricherAdministrationService.list).mockRejectedValue({ status: 403 })
    mount()
    await screen.findByText('Administrator access required')
    expect(screen.queryByRole('table', { hidden: true })).toBeNull()
  })

  it('retries a failed catalog request and supports an empty catalog', async () => {
    vi.mocked(enricherAdministrationService.list)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce([])
    mount()
    await screen.findByText("Couldn't load enricher administration")
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await screen.findByText('No enrichers available')
    expect(screen.queryByRole('table', { hidden: true })).toBeNull()
    expect(screen.getByText('Showing 0 of 0 enrichers')).toBeTruthy()
  })
})
