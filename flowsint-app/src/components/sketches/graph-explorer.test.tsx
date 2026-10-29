// @vitest-environment jsdom
import { beforeEach, afterEach, describe, it, expect, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { GraphExplorer } from './graph-explorer'
import { useGraphExploration } from '@/stores/graph-exploration-store'

const mocks = vi.hoisted(() => ({
  search: vi.fn(),
  catalog: vi.fn(),
  explore: vi.fn(),
  attach: vi.fn(),
  refresh: vi.fn(),
  highlight: vi.fn(),
  canEdit: true,
  canCreate: true
}))
vi.mock('@/api/sketch-service', () => ({
  sketchService: {
    searchGraphObjects: mocks.search,
    explorationCatalog: mocks.catalog,
    explore: mocks.explore,
    attachSubgraph: mocks.attach
  }
}))
vi.mock('@/hooks/use-can', () => ({
  usePermissions: () => ({ canEdit: mocks.canEdit, canCreate: mocks.canCreate })
}))
vi.mock('@tanstack/react-router', () => ({
  useParams: () => ({ id: 'friends', investigationId: 'case' })
}))
vi.mock('@/i18n', () => ({
  useTranslation: () => ({
    t: (text: string, values?: Record<string, unknown>) =>
      text.replace(/\{\{(\w+)\}\}/g, (_, key) => String(values?.[key] ?? ''))
  })
}))
vi.mock('@/stores/graph-store', () => ({
  useGraphStore: Object.assign(
    (select: (state: unknown) => unknown) => select({ selectedNodes: [], currentNodeId: 'masha' }),
    { getState: () => ({ setHighlightedNodes: mocks.highlight }) }
  )
}))
vi.mock('@/stores/graph-controls-store', () => ({
  useGraphControls: { getState: () => ({ refetchGraph: mocks.refresh }) }
}))
vi.mock('./new-sketch', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const objects = [
  { id: 'masha', nodeLabel: 'Masha', nodeType: 'individual' },
  { id: 'sergey', nodeLabel: 'Sergey', nodeType: 'individual' },
  { id: 'volodya', nodeLabel: 'Volodya', nodeType: 'individual' }
]
function result(depth = 2, path = false, truncated = false) {
  return {
    nds: objects.slice(0, depth === 1 ? 2 : 3),
    rls: [
      { id: 'friendship', source: 'masha', target: 'sergey', label: 'FRIEND_OF' },
      ...(depth > 1
        ? [{ id: 'employment', source: 'sergey', target: 'volodya', label: 'WORKS_WITH' }]
        : [])
    ],
    paths: path
      ? [{ node_ids: ['masha', 'sergey', 'volodya'], edge_ids: ['friendship', 'employment'] }]
      : [],
    distances: { masha: 0, sergey: 1, volodya: 2 },
    on_sketch: ['masha', 'sergey'],
    edge_views: { friendship: ['friends'], employment: ['work'] },
    depth,
    truncated,
    limits: { nodes: 200, edges: 500, paths: 20, scanned: 5000 }
  }
}
beforeEach(() => {
  vi.clearAllMocks()
  mocks.canEdit = true
  mocks.canCreate = true
  mocks.catalog.mockResolvedValue({
    node_types: ['individual'],
    edge_types: ['FRIEND_OF', 'WORKS_WITH'],
    sketches: [
      { id: 'friends', title: 'Friends' },
      { id: 'work', title: 'Work' }
    ],
    truncated: false
  })
  mocks.search.mockImplementation((_sketch, _query, ids: string[]) =>
    Promise.resolve({
      nodes: ids.length ? objects.filter((n) => ids.includes(n.id)) : objects,
      has_more: false
    })
  )
  mocks.explore.mockImplementation((_id, options) =>
    Promise.resolve(result(options.depth, options.mode === 'path'))
  )
  mocks.attach.mockResolvedValue({})
  useGraphExploration.setState({ request: null })
})
afterEach(cleanup)
function open(mode: 'path' | 'neighborhood' = 'neighborhood', autoRun = false) {
  useGraphExploration
    .getState()
    .open({ sketchId: 'friends', rootId: 'masha', targetId: 'volodya', mode, depth: 1, autoRun })
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <GraphExplorer />
    </QueryClientProvider>
  )
}

describe('Investigation exploration', () => {
  it('clears the old preview when filters change and submits the selected types and direction', async () => {
    open('neighborhood', true)
    await screen.findByText('Preview: 2 objects, 1 relations.')
    fireEvent.click(screen.getByText(/Search settings/))
    fireEvent.click(screen.getByText('Traversal filters'))
    fireEvent.click(screen.getByRole('checkbox', { name: 'WORKS_WITH' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Follow relation direction' }))
    expect(screen.queryByRole('button', { name: 'Add selected result to sketch' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Preview neighborhood' }))
    await waitFor(() =>
      expect(mocks.explore.mock.calls.at(-1)?.[1]).toMatchObject({
        edge_types: ['WORKS_WITH'],
        directed: true
      })
    )
  })

  it('keeps the result and selected objects after an attach error', async () => {
    mocks.attach.mockRejectedValue(new Error('offline'))
    open('neighborhood', true)
    await screen.findByText('Preview: 2 objects, 1 relations.')
    fireEvent.click(screen.getByRole('button', { name: 'Add selected result to sketch' }))
    await waitFor(() => expect(mocks.attach).toHaveBeenCalledOnce())
    await waitFor(() =>
      expect(
        screen
          .getByRole('button', { name: 'Add selected result to sketch' })
          .hasAttribute('disabled')
      ).toBe(false)
    )
    expect(screen.getByRole('checkbox', { name: 'Masha' }).getAttribute('aria-checked')).toBe(
      'true'
    )
    expect(mocks.refresh).not.toHaveBeenCalled()
  })

  it('previews one step, expands another step and attaches only selected nodes and relations', async () => {
    open('neighborhood', true)
    await screen.findByText('Preview: 2 objects, 1 relations.')
    expect(mocks.attach).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Expand one more step' }))
    await screen.findByText('Preview: 3 objects, 2 relations.')
    expect(mocks.explore.mock.calls.at(-1)?.[1].depth).toBe(2)
    fireEvent.click(screen.getByRole('checkbox', { name: 'Volodya' }))
    fireEvent.click(screen.getByRole('button', { name: 'Add selected result to sketch' }))
    await waitFor(() =>
      expect(mocks.attach).toHaveBeenCalledWith('friends', ['masha', 'sergey'], ['friendship'])
    )
  })

  it('searches across views with a configurable depth, preserving typed steps and view names', async () => {
    open('path')
    fireEvent.change(screen.getByRole('combobox', { name: 'Maximum steps' }), {
      target: { value: '5' }
    })
    fireEvent.click(screen.getAllByRole('button', { name: 'Find connections' }).at(-1)!)
    await screen.findByText('Path 1: 2 steps')
    expect(mocks.explore.mock.calls[0][1]).toMatchObject({
      root_id: 'masha',
      target_id: 'volodya',
      depth: 5,
      mode: 'path',
      directed: false
    })
    expect(screen.getByText('→ WORKS_WITH (Work)')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Add selected result to sketch' }))
    await waitFor(() =>
      expect(mocks.attach).toHaveBeenCalledWith(
        'friends',
        ['masha', 'sergey', 'volodya'],
        ['friendship', 'employment']
      )
    )
  })

  it('reports partial results, keeps viewer exploration read-only and disables a sixth step', async () => {
    mocks.canEdit = false
    mocks.canCreate = false
    mocks.explore.mockResolvedValue(result(5, false, true))
    open('neighborhood', true)
    await screen.findByRole('alert')
    expect(screen.getByText(/partial result/)).toBeTruthy()
    expect(
      screen.getByRole('button', { name: 'Expand one more step' }).hasAttribute('disabled')
    ).toBe(true)
    expect(screen.queryByRole('button', { name: 'Add selected result to sketch' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Create sketch from result' })).toBeNull()
  })

  it('does not attach anything on a failed search and retains the inputs for retry', async () => {
    mocks.explore.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(result())
    open('neighborhood', true)
    await screen.findByRole('alert')
    expect(mocks.attach).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Preview neighborhood' }))
    await screen.findByText('Preview: 3 objects, 2 relations.')
    expect(mocks.explore.mock.calls.at(-1)?.[1].root_id).toBe('masha')
  })
})
