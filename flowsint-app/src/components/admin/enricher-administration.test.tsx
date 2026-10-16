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
  // Radix Select uses these browser APIs when keyboard interaction scrolls an option.
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

  it('shows built-in and hidden template rows, project scope and counts', async () => {
    mount()
    await screen.findByText('DNS lookup')
    const table = screen.getByRole('table', { name: 'All enrichers' })
    expect(within(table).getByText('Email search')).toBeTruthy()
    expect(within(table).getByText('Hidden')).toBeTruthy()
    expect(screen.getByText(/current AVL4 project/)).toBeTruthy()
    expect(screen.getByText('Showing 2 of 2 enrichers')).toBeTruthy()
    expect(screen.getByRole('switch', { name: /Email search/ }).getAttribute('aria-checked')).toBe(
      'false'
    )
  })

  it.each(['hostname', 'network', 'domain', 'ip'])(
    'searches description, category and IO (%s)',
    async (term) => {
      mount()
      await screen.findByText('DNS lookup')
      fireEvent.change(screen.getByRole('textbox', { name: 'Search enrichers' }), {
        target: { value: term }
      })
      expect(screen.queryByText('Email search')).toBeNull()
      expect(screen.getByText('DNS lookup')).toBeTruthy()
    }
  )

  it('filters by kind and visibility and resets an empty result', async () => {
    mount()
    await screen.findByText('DNS lookup')
    await chooseFilter('Enricher kind', 'Template')
    expect(screen.queryByText('DNS lookup')).toBeNull()
    expect(screen.getByText('Email search')).toBeTruthy()
    await chooseFilter('Visibility filter', 'Visible')
    expect(screen.getByText('No matching enrichers')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(screen.getByText('DNS lookup')).toBeTruthy()
    expect(screen.getByText('Email search')).toBeTruthy()
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
    const toggle = await screen.findByRole('switch', { name: /DNS lookup/ })
    fireEvent.click(toggle)
    await waitFor(() => expect(toggle.hasAttribute('disabled')).toBe(true))
    expect(toggle.getAttribute('aria-checked')).toBe('true')
    // Other rows can still be edited while this row is saving.
    expect(screen.getByRole('switch', { name: /Email search/ }).hasAttribute('disabled')).toBe(
      false
    )
    finish({ ...rows[0], is_visible: false })
    await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('false'))
    expect(screen.getByText('DNS lookup')).toBeTruthy()
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
  })

  it('preserves previous visibility and offers retry after a mutation fails', async () => {
    vi.mocked(enricherAdministrationService.setVisibility).mockRejectedValue(new Error('offline'))
    mount()
    const toggle = await screen.findByRole('switch', { name: /DNS lookup/ })
    fireEvent.click(toggle)
    await screen.findByText(/Couldn't save visibility/)
    expect(toggle.getAttribute('aria-checked')).toBe('true')
    expect(toggle.hasAttribute('disabled')).toBe(false)
    expect(screen.getByText('DNS lookup')).toBeTruthy()
  })

  it('denies access without fetching or showing managed rows', async () => {
    vi.mocked(enricherAdministrationService.access).mockResolvedValue({ can_manage: false })
    mount()
    await screen.findByText('Administrator access required')
    expect(enricherAdministrationService.list).not.toHaveBeenCalled()
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('shows a forbidden state when the server revokes administrator access', async () => {
    vi.mocked(enricherAdministrationService.list).mockRejectedValue({ status: 403 })
    mount()
    await screen.findByText('Administrator access required')
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('retries a failed catalog request and supports an empty catalog', async () => {
    vi.mocked(enricherAdministrationService.list)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce([])
    mount()
    await screen.findByText("Couldn't load enricher administration")
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await screen.findByText('No enrichers available')
    expect(screen.getByText('Showing 0 of 0 enrichers')).toBeTruthy()
  })
})
