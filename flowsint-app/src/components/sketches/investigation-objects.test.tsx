// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { InvestigationObjects } from './investigation-objects'

const { getGraph, attach, refresh } = vi.hoisted(() => ({
  getGraph: vi.fn(),
  attach: vi.fn(),
  refresh: vi.fn()
}))
vi.mock('@/api/sketch-service', () => ({
  sketchService: {
    getInvestigationGraph: getGraph,
    attachSubgraph: attach
  }
}))
vi.mock('@tanstack/react-router', () => ({
  useParams: () => ({ id: 'view-b', investigationId: 'investigation' })
}))
vi.mock('@/i18n', () => ({ useTranslation: () => ({ t: (text: string) => text }) }))
vi.mock('@/stores/graph-controls-store', () => ({
  useGraphControls: (selector: (state: { refetchGraph: typeof refresh }) => unknown) =>
    selector({ refetchGraph: refresh })
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

beforeEach(() => {
  vi.clearAllMocks()
  getGraph.mockResolvedValue({
    nds: [
      { id: 'alice', nodeLabel: 'Alice', nodeType: 'socialaccount' },
      { id: 'bob', nodeLabel: 'Bob', nodeType: 'socialaccount' }
    ],
    rls: [{ id: 'friendship', source: 'alice', target: 'bob', label: 'FRIEND_OF' }]
  })
  attach.mockResolvedValue({})
})
afterEach(cleanup)

async function open() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <InvestigationObjects />
    </QueryClientProvider>
  )
  fireEvent.click(screen.getByRole('button', { name: 'Investigation objects' }))
  await screen.findByText('Alice')
}

describe('Investigation objects', () => {
  it('reuses entity IDs and adds only explicitly selected relations', async () => {
    await open()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Alice socialaccount' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Bob socialaccount' }))
    expect(
      screen.getByRole('checkbox', { name: 'Alice → FRIEND_OF → Bob' }).getAttribute('aria-checked')
    ).toBe('false')
    fireEvent.click(screen.getByRole('button', { name: 'Add to sketch' }))
    await waitFor(() => expect(attach).toHaveBeenCalledWith('view-b', ['alice', 'bob'], []))
    await waitFor(() => expect(refresh).toHaveBeenCalled())
  })

  it('can include a shared relation without creating a new one', async () => {
    await open()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Alice socialaccount' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Bob socialaccount' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Alice → FRIEND_OF → Bob' }))
    fireEvent.click(screen.getByRole('button', { name: 'Add to sketch' }))
    await waitFor(() =>
      expect(attach).toHaveBeenCalledWith('view-b', ['alice', 'bob'], ['friendship'])
    )
  })

  it('keeps the dialog and selection on a failed request', async () => {
    attach.mockRejectedValue(new Error('unavailable'))
    await open()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Alice socialaccount' }))
    fireEvent.click(screen.getByRole('button', { name: 'Add to sketch' }))
    await waitFor(() => expect(attach).toHaveBeenCalledOnce())
    expect(refresh).not.toHaveBeenCalled()
    expect(
      screen.getByRole('checkbox', { name: 'Alice socialaccount' }).getAttribute('aria-checked')
    ).toBe('true')
  })
})
