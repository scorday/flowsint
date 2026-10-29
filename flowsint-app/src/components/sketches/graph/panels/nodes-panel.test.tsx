// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import NodesPanel from './nodes-panel'
import { useGraphStore } from '@/stores/graph-store'
import type { GraphNode } from '@/types'

const mocks = vi.hoisted(() => {
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: { getItem: () => null, setItem: () => {}, removeItem: () => {} }
  })
  return { canEdit: true, update: vi.fn(), error: vi.fn(), sketchId: 'view-a' }
})
vi.mock('@/api/sketch-service', () => ({ sketchService: { updateNode: mocks.update } }))
vi.mock('@tanstack/react-router', () => ({ useParams: () => ({ id: mocks.sketchId }) }))
vi.mock('@/hooks/use-can', () => ({ usePermissions: () => ({ canEdit: mocks.canEdit }) }))
vi.mock('@/i18n', () => ({ useTranslation: () => ({ t: (text: string) => text }) }))
vi.mock('sonner', () => ({ toast: { error: mocks.error } }))
vi.mock('@/components/type-badge', () => ({
  TypeBadge: ({ type }: { type: string }) => <span>{type}</span>
}))
// jsdom has no scroll measurements. Keep every row visible in component tests.
vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({
    count,
    getItemKey
  }: {
    count: number
    getItemKey: (index: number) => string
  }) => ({
    getTotalSize: () => count * 40,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index,
        key: getItemKey(index),
        size: 40,
        start: index * 40
      }))
  })
}))

function node(id: string, role?: GraphNode['nodeRole'], nodeType = 'domain'): GraphNode {
  return {
    id,
    nodeLabel: id,
    nodeType,
    nodeRole: role,
    nodeProperties: {},
    nodeMetadata: {},
    nodeSize: 4,
    nodeColor: null,
    nodeIcon: null,
    nodeImage: null,
    nodeFlag: null,
    nodeShape: null,
    x: 0,
    y: 0
  }
}
const nodes = [node('Manual', 'primary'), node('Legacy'), node('Enriched', 'secondary', 'email')]

function Panel() {
  const nodes = useGraphStore((state) => state.nodes)
  return <NodesPanel nodes={nodes} />
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.canEdit = true
  mocks.sketchId = 'view-a'
  mocks.update.mockResolvedValue({ status: 'node updated' })
  useGraphStore.setState({ nodes, selectedNodes: [], currentNodeId: null })
})
afterEach(cleanup)

describe('sketch object roles', () => {
  it('groups legacy and manual objects as primary, and collapses groups independently', () => {
    render(<Panel />)
    const primary = screen.getByRole('button', { name: 'Primary objects 2' })
    expect(screen.getByRole('button', { name: 'Secondary objects 1' })).toBeTruthy()
    fireEvent.click(primary)
    expect(primary.getAttribute('aria-expanded')).toBe('false')
    expect(screen.queryByText('Manual')).toBeNull()
    expect(screen.queryByText('Legacy')).toBeNull()
    expect(screen.getByText('Enriched')).toBeTruthy()
    fireEvent.click(primary)
    expect(screen.getByText('Manual')).toBeTruthy()
    expect(screen.getByText('Legacy')).toBeTruthy()
  })

  it('searches both sections and keeps filtered counts', () => {
    render(<Panel />)
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'Enriched' } })
    expect(screen.getByRole('button', { name: 'Primary objects 0 / 2' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Secondary objects 1' })).toBeTruthy()
    expect(screen.queryByText('Manual')).toBeNull()
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'Legacy' } })
    expect(screen.getByRole('button', { name: 'Primary objects 1 / 2' })).toBeTruthy()
    expect(screen.queryByText('Enriched')).toBeNull()
  })

  it('applies a type filter to both sections and keeps it while searching', async () => {
    render(<Panel />)
    fireEvent.keyDown(screen.getByRole('button', { name: 'Filter by type' }), { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('menuitem', { name: 'email' }))
    expect(screen.queryByText('Manual')).toBeNull()
    expect(screen.queryByText('Legacy')).toBeNull()
    expect(screen.getByText('Enriched')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Primary objects 0 / 2' })).toBeTruthy()
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'Manual' } })
    expect(screen.queryByText('Manual')).toBeNull()
    expect(screen.queryByText('Enriched')).toBeNull()
    expect(screen.getByRole('button', { name: 'Secondary objects 0 / 1' })).toBeTruthy()
  })

  it('moves a secondary object only after the server accepts the role change', async () => {
    let accept: (value: unknown) => void = () => {}
    mocks.update.mockReturnValue(
      new Promise((resolve) => {
        accept = resolve
      })
    )
    render(<Panel />)
    fireEvent.click(screen.getByRole('button', { name: 'Make primary' }))
    expect(mocks.update).toHaveBeenCalledWith(
      'view-a',
      JSON.stringify({ nodeId: 'Enriched', updates: { nodeRole: 'primary' } })
    )
    expect(useGraphStore.getState().nodes[2].nodeRole).toBe('secondary')
    await act(async () => {
      accept({})
    })
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Primary objects 3' })).toBeTruthy()
    )
    expect(screen.queryByRole('button', { name: 'Make primary' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Secondary objects 0' })).toBeTruthy()
  })

  it('preserves a secondary role and reports a failed write', async () => {
    mocks.update.mockRejectedValue(new Error('offline'))
    render(<Panel />)
    fireEvent.click(screen.getByRole('button', { name: 'Make primary' }))
    await waitFor(() => expect(mocks.error).toHaveBeenCalled())
    expect(useGraphStore.getState().nodes[2].nodeRole).toBe('secondary')
  })

  it('does not offer role changes to a viewer', () => {
    mocks.canEdit = false
    render(<Panel />)
    expect(screen.queryByRole('button', { name: 'Make primary' })).toBeNull()
    expect(screen.getByText('Enriched')).toBeTruthy()
  })

  it('does not update a different sketch when a request finishes after navigation', async () => {
    let accept: (value: unknown) => void = () => {}
    mocks.update.mockReturnValue(
      new Promise((resolve) => {
        accept = resolve
      })
    )
    const { rerender } = render(<Panel />)
    fireEvent.click(screen.getByRole('button', { name: 'Make primary' }))
    mocks.sketchId = 'view-b'
    act(() => useGraphStore.setState({ nodes: nodes.map((node) => ({ ...node })) }))
    rerender(<Panel />)
    await act(async () => {
      accept({})
    })
    expect(useGraphStore.getState().nodes[2].nodeRole).toBe('secondary')
  })
})
