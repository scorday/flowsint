// @vitest-environment jsdom
import { beforeEach, afterEach, describe, it, expect, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { GraphExplorer } from './graph-explorer'
import { useGraphExploration } from '@/stores/graph-exploration-store'
import type { ExplorationJob, ExplorationNode } from '@/api/sketch-service'

const mocks = vi.hoisted(() => ({
  search: vi.fn(),
  catalog: vi.fn(),
  start: vi.fn(),
  status: vi.fn(),
  page: vi.fn(),
  select: vi.fn(),
  apply: vi.fn(),
  cancel: vi.fn(),
  refresh: vi.fn(),
  navigate: vi.fn(),
  canEdit: true,
  canCreate: true
}))
vi.mock('@/api/sketch-service', () => ({
  sketchService: {
    searchGraphObjects: mocks.search,
    explorationCatalog: mocks.catalog,
    startExploration: mocks.start,
    explorationStatus: mocks.status,
    explorationPage: mocks.page,
    selectExploration: mocks.select,
    applyExploration: mocks.apply,
    cancelExploration: mocks.cancel
  }
}))
vi.mock('@/hooks/use-can', () => ({
  usePermissions: () => ({ canEdit: mocks.canEdit, canCreate: mocks.canCreate })
}))
vi.mock('@tanstack/react-router', () => ({
  useParams: () => ({ id: 'friends', investigationId: 'case' }),
  useRouter: () => ({ navigate: mocks.navigate })
}))
vi.mock('@/i18n', () => ({
  useTranslation: () => ({
    t: (text: string, values?: Record<string, unknown>) =>
      text.replace(/\{\{(\w+)\}\}/g, (_, key) => String(values?.[key] ?? ''))
  })
}))
vi.mock('@/stores/graph-store', () => ({
  useGraphStore: (select: (s: unknown) => unknown) =>
    select({ selectedNodes: [], currentNodeId: 'n0' })
}))
vi.mock('@/stores/graph-controls-store', () => ({
  useGraphControls: { getState: () => ({ refetchGraph: mocks.refresh }) }
}))
vi.mock('./new-sketch', () => ({
  default: ({
    children,
    onCreate
  }: {
    children: React.ReactNode
    onCreate: (data: { title: string }) => Promise<void>
  }) => <div onClick={() => onCreate({ title: 'Entire selection' })}>{children}</div>
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
let job: ExplorationJob
let rows: ExplorationNode[]
beforeEach(() => {
  vi.clearAllMocks()
  mocks.canEdit = true
  mocks.canCreate = true
  rows = Array.from({ length: 12051 }, (_, i) => ({
    id: `n${i}`,
    nodeLabel: `Person ${i}`,
    nodeType: 'individual',
    distance: i ? 1 : 0,
    on_sketch: i === 0,
    selected: true
  }))
  job = {
    id: 'server-snapshot',
    status: 'completed',
    revision: 0,
    totals: { nodes: 12051, edges: 12050, paths: 0 },
    selected: { nodes: 12051, edges: 12050, paths: 0 },
    options: {
      mode: 'neighborhood',
      root_id: 'n0',
      depth: 1,
      node_types: [],
      edge_types: [],
      directed: false
    },
    updated_at: 0
  }
  mocks.catalog.mockResolvedValue({
    node_types: ['individual'],
    edge_types: ['FRIEND_OF'],
    sketches: [],
    truncated: false
  })
  mocks.search.mockImplementation((_sketch, _query, ids: string[]) =>
    Promise.resolve({
      nodes: ids.map((id) => ({ id, nodeLabel: id, nodeType: 'individual', on_sketch: false })),
      has_more: false
    })
  )
  mocks.start.mockImplementation((_sketch, options) => {
    job = { ...job, options }
    return Promise.resolve({ ...job })
  })
  mocks.status.mockImplementation(() => Promise.resolve({ ...job }))
  mocks.page.mockImplementation((_sketch, _id, kind, page) =>
    Promise.resolve({
      ...job,
      items: kind === 'nodes' ? rows.slice(page * 50, (page + 1) * 50) : [],
      page,
      size: 50
    })
  )
  mocks.select.mockImplementation((_sketch, _id, data) => {
    rows = rows.map((row) =>
      data.kind === 'all' ||
      (data.kind === 'nodes' && (data.ids === null || data.ids.includes(row.id)))
        ? { ...row, selected: data.checked }
        : row
    )
    job = {
      ...job,
      revision: job.revision + 1,
      selected: { ...job.selected, nodes: rows.filter((r) => r.selected).length }
    }
    return Promise.resolve({ ...job })
  })
  mocks.apply.mockImplementation(() => {
    job = { ...job, status: 'applying' }
    return Promise.resolve({ ...job })
  })
  mocks.cancel.mockImplementation(() => {
    job = { ...job, status: 'cancelled' }
    return Promise.resolve({ ...job })
  })
  useGraphExploration.setState({ request: null })
})
afterEach(cleanup)
function open() {
  useGraphExploration
    .getState()
    .open({ sketchId: 'friends', rootId: 'n0', mode: 'neighborhood', depth: 1, autoRun: true })
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <GraphExplorer />
    </QueryClientProvider>
  )
}
function nodes() {
  return within(screen.getByRole('region', { name: 'Objects to show' }))
}

describe('Complete, paged investigation search', () => {
  it('renders one page and keeps selection across pages', async () => {
    open()
    await screen.findByText('Found: 12051 objects, 12050 relations, 0 paths.')
    await nodes().findByRole('checkbox', { name: 'Person 0' })
    expect(nodes().getAllByRole('checkbox')).toHaveLength(50)
    expect(screen.queryByRole('checkbox', { name: 'Person 50' })).toBeNull()
    fireEvent.click(nodes().getByRole('checkbox', { name: 'Person 0' }))
    await waitFor(() =>
      expect(nodes().getByRole('checkbox', { name: 'Person 0' }).getAttribute('aria-checked')).toBe(
        'false'
      )
    )
    fireEvent.click(nodes().getByRole('button', { name: 'Next page' }))
    await nodes().findByRole('checkbox', { name: 'Person 50' })
    fireEvent.click(nodes().getByRole('button', { name: 'Previous page' }))
    await waitFor(() =>
      expect(nodes().getByRole('checkbox', { name: 'Person 0' }).getAttribute('aria-checked')).toBe(
        'false'
      )
    )
    expect(mocks.start).toHaveBeenCalledOnce()
  })
  it('creates using the server selection, never visible-page IDs', async () => {
    open()
    await screen.findByRole('checkbox', { name: 'Person 0' })
    fireEvent.click(nodes().getByRole('button', { name: 'Next page' }))
    await nodes().findByRole('checkbox', { name: 'Person 50' })
    fireEvent.click(nodes().getByRole('checkbox', { name: 'Person 50' }))
    await waitFor(() => expect(job.revision).toBe(1))
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Create sketch from result' }).hasAttribute('disabled')
      ).toBe(false)
    )
    fireEvent.click(screen.getByRole('button', { name: 'Create sketch from result' }))
    await waitFor(() =>
      expect(mocks.apply).toHaveBeenCalledWith('friends', 'server-snapshot', {
        action: 'create',
        title: 'Entire selection',
        revision: 1
      })
    )
    expect(screen.getByText(/Creating the sketch with all selected/)).toBeTruthy()
  })
  it('offers separate page and whole-result group operations', async () => {
    open()
    await screen.findByRole('checkbox', { name: 'Person 0' })
    fireEvent.click(nodes().getByRole('button', { name: 'Clear page' }))
    await waitFor(() => expect(job.selected.nodes).toBe(12001))
    await waitFor(() =>
      expect(nodes().getByRole('button', { name: 'Select page' }).hasAttribute('disabled')).toBe(
        false
      )
    )
    fireEvent.click(screen.getByRole('button', { name: 'Select all results' }))
    await waitFor(() =>
      expect(mocks.select).toHaveBeenLastCalledWith('friends', 'server-snapshot', {
        kind: 'all',
        checked: true,
        ids: null,
        revision: 1
      })
    )
    expect(job.selected.nodes).toBe(12051)
  })
  it('attaches without serializing a large ID list', async () => {
    open()
    await screen.findByRole('checkbox', { name: 'Person 0' })
    fireEvent.click(screen.getByRole('button', { name: 'Add selected result to sketch' }))
    await waitFor(() =>
      expect(mocks.apply).toHaveBeenCalledWith('friends', 'server-snapshot', {
        action: 'attach',
        revision: 0
      })
    )
  })
  it('keeps viewer exploration read-only', async () => {
    mocks.canEdit = false
    mocks.canCreate = false
    open()
    await screen.findByRole('checkbox', { name: 'Person 0' })
    expect(screen.queryByRole('button', { name: 'Create sketch from result' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Add selected result to sketch' })).toBeNull()
  })
  it('cannot apply partial running results and can cancel', async () => {
    job.status = 'running'
    open()
    await screen.findByRole('button', { name: 'Cancel search' })
    expect(screen.queryByRole('button', { name: 'Create sketch from result' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel search' }))
    await screen.findByText('Search cancelled. Partial results cannot be added to a sketch.')
    expect(mocks.apply).not.toHaveBeenCalled()
  })
  it('retries a failed start with the same inputs', async () => {
    mocks.start.mockRejectedValueOnce(new Error('offline'))
    open()
    await screen.findByRole('alert')
    fireEvent.click(screen.getByRole('button', { name: 'Preview neighborhood' }))
    await screen.findByRole('checkbox', { name: 'Person 0' })
    expect(mocks.start.mock.calls.at(-1)?.[1].root_id).toBe('n0')
  })
})
