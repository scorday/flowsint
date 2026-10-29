// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { GraphEdge, GraphNode } from '@/types'
import { setLanguage } from '@/i18n'
import Relationships from './relationships'

const mocks = vi.hoisted(() => ({ load: vi.fn(), select: vi.fn() }))
vi.mock('@/api/sketch-service', () => ({ sketchService: { getNodeNeighbors: mocks.load } }))
vi.mock('@/stores/graph-store', () => ({
  useGraphStore: (selector: (state: { setCurrentNodeId: typeof mocks.select }) => unknown) =>
    selector({ setCurrentNodeId: mocks.select })
}))
vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({
    count,
    getItemKey
  }: {
    count: number
    getItemKey: (i: number) => string
  }) => ({
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index,
        key: getItemKey(index),
        size: 36,
        start: index * 36
      })),
    getTotalSize: () => count * 36
  })
}))

const nodes = [
  ['root', 'Current profile'],
  ['out', 'Outgoing neighbor with a long readable name'],
  ['in', 'Incoming neighbor'],
  ['other', 'Unrelated neighbor']
].map(([id, nodeLabel]) => ({ id, nodeLabel, nodeType: 'socialaccount' }) as GraphNode)
const edge = (id: string, source: string, target: string, label: string): GraphEdge => ({
  id,
  source,
  target,
  label
})
const edges = [
  edge('outgoing', 'root', 'out', 'FRIEND_OF'),
  { ...edge('incoming', 'in', 'root', 'FOLLOWS'), caption: 'Subscribed to' },
  edge('parallel', 'root', 'out', 'WORKS_WITH'),
  edge('other', 'out', 'other', 'UNRELATED'),
  edge('missing', 'root', 'missing', 'MISSING')
]

const clients: QueryClient[] = []
function renderRelationships(rls = edges, nodeId = 'root') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  clients.push(client)
  client.setQueryData(['neighbors', 'sketch', nodeId, nodes.length], { nds: nodes, rls })
  return render(
    <QueryClientProvider client={client}>
      <Relationships sketchId="sketch" nodeId={nodeId} nodeLength={nodes.length} />
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  setLanguage('en')
  mocks.load.mockImplementation(() => new Promise(() => {}))
})
afterEach(() => {
  cleanup()
  clients.splice(0).forEach((client) => client.clear())
})

it.each(['en', 'ru'] as const)(
  'shows the other endpoint once per edge, with direction and actual type in %s',
  (language) => {
    setLanguage(language)
    renderRelationships()
    const rows = screen.getAllByRole('listitem')
    expect(rows).toHaveLength(3)
    expect(screen.queryByText('Current profile')).toBeNull()
    expect(
      within(rows[0]).getByRole('img', {
        name: language === 'ru' ? 'Исходящая связь' : 'Outgoing relationship'
      })
    ).toBeTruthy()
    expect(within(rows[0]).getByText('FRIEND_OF')).toBeTruthy()
    expect(
      within(rows[1]).getByRole('img', {
        name: language === 'ru' ? 'Входящая связь' : 'Incoming relationship'
      })
    ).toBeTruthy()
    expect(within(rows[1]).getByText('Subscribed to')).toBeTruthy()
    expect(within(rows[2]).getByText('WORKS_WITH')).toBeTruthy()
    expect(screen.queryByText('RELATED_TO')).toBeNull()
    fireEvent.click(within(rows[0]).getByRole('button', { name: nodes[1].nodeLabel }))
    expect(mocks.select).toHaveBeenLastCalledWith('out')
    fireEvent.click(within(rows[1]).getByRole('button', { name: 'Incoming neighbor' }))
    expect(mocks.select).toHaveBeenLastCalledWith('in')
  }
)

it('distinguishes self relationships without repeating the current name', () => {
  renderRelationships([edge('self', 'root', 'root', 'RELATED_TO')])
  expect(screen.getByRole('img', { name: 'Self relationship' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'This node' }))
  expect(mocks.select).toHaveBeenCalledWith('root')
  expect(screen.queryByText('Current profile')).toBeNull()
})

it('shows an empty state when there are no valid incident edges', () => {
  renderRelationships([edge('other', 'in', 'out', 'OTHER')])
  expect(screen.getByText('No relationships found')).toBeTruthy()
})

it('resolves object endpoints populated by the graph renderer', () => {
  renderRelationships([
    { ...edges[0], source: { id: 'root' }, target: { id: 'out' } } as unknown as GraphEdge
  ])
  expect(screen.getByRole('button', { name: nodes[1].nodeLabel })).toBeTruthy()
})

it('rebuilds the list relative to the newly inspected node', () => {
  const view = renderRelationships()
  const client = clients[0]
  client.setQueryData(['neighbors', 'sketch', 'out', nodes.length], { nds: nodes, rls: edges })
  act(() =>
    view.rerender(
      <QueryClientProvider client={client}>
        <Relationships sketchId="sketch" nodeId="out" nodeLength={nodes.length} />
      </QueryClientProvider>
    )
  )
  expect(screen.queryByRole('button', { name: nodes[1].nodeLabel })).toBeNull()
  expect(screen.getAllByRole('button', { name: 'Current profile' })).toHaveLength(2)
  expect(screen.getAllByRole('img', { name: 'Incoming relationship' })).toHaveLength(2)
  expect(screen.getByRole('img', { name: 'Outgoing relationship' })).toBeTruthy()
})
