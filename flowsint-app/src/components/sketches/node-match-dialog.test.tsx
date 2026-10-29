// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor
} from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { GraphNode } from '@/types'
import { NodeMatchDialog } from './node-match-dialog'
import { useManualNodeAdd } from './use-manual-node-add'

const mocks = vi.hoisted(() => ({
  find: vi.fn(),
  add: vi.fn(),
  attach: vi.fn(),
  edge: vi.fn(),
  update: vi.fn(),
  select: vi.fn(),
  refresh: vi.fn(),
  added: vi.fn(),
  cancel: vi.fn()
}))
vi.mock('@/api/sketch-service', () => ({
  sketchService: {
    findNodeMatches: mocks.find,
    addNode: mocks.add,
    attachSubgraph: mocks.attach,
    addEdge: mocks.edge,
    updateNode: mocks.update
  }
}))
vi.mock('@tanstack/react-router', () => ({ useParams: () => ({ investigationId: 'case' }) }))
vi.mock('@/i18n', () => ({ useTranslation: () => ({ t: (value: string) => value }) }))
vi.mock('@/stores/graph-store', () => ({
  useGraphStore: { getState: () => ({ setCurrentNodeId: mocks.select }) }
}))
vi.mock('@/stores/graph-controls-store', () => ({
  useGraphControls: { getState: () => ({ refetchGraph: mocks.refresh }) }
}))
vi.mock('sonner', () => ({ toast: { error: vi.fn() } }))

const candidate: GraphNode = {
  id: 'temporary',
  nodeType: 'person',
  nodeLabel: 'Alice',
  nodeProperties: { full_name: 'Alice' },
  nodeMetadata: {},
  x: 12,
  y: 34,
  nodeSize: 4,
  nodeColor: null,
  nodeIcon: null,
  nodeImage: null,
  nodeFlag: null,
  nodeShape: 'circle'
}
const existing = { ...candidate, id: 'canonical', nodeLabel: 'Alice Smith' }
function Harness() {
  const controller = useManualNodeAdd('view-b')
  return (
    <>
      <button
        onClick={() => controller.add(candidate, { onAdded: mocks.added, onCancel: mocks.cancel })}
      >
        Submit form
      </button>
      <NodeMatchDialog controller={controller} />
    </>
  )
}
function open() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Harness />
    </QueryClientProvider>
  )
  fireEvent.click(screen.getByRole('button', { name: 'Submit form' }))
}
beforeEach(() => {
  vi.clearAllMocks()
  mocks.add.mockResolvedValue({ node: { ...candidate, id: 'server-id' } })
  mocks.attach.mockResolvedValue({})
  mocks.refresh.mockImplementation((done?: () => void) => done?.())
})
afterEach(cleanup)

describe('Manual object matching', () => {
  it('does not create on another sketch after navigation during the check', async () => {
    let resolve!: (matches: []) => void
    mocks.find.mockImplementation(
      () =>
        new Promise<[]>((done) => {
          resolve = done
        })
    )
    const client = new QueryClient()
    const { result, rerender } = renderHook(({ id }) => useManualNodeAdd(id), {
      initialProps: { id: 'view-b' },
      wrapper: ({ children }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      )
    })
    let operation: ReturnType<typeof result.current.add>
    act(() => {
      operation = result.current.add(candidate)
    })
    rerender({ id: 'other-view' })
    await act(async () => {
      resolve([])
      await operation
    })
    expect(mocks.add).not.toHaveBeenCalled()
    expect(result.current.pending).toBeNull()
  })
  it('adds a hidden exact match without overwriting its data or creating another object', async () => {
    mocks.find.mockResolvedValue([{ node: existing, match: 'exact', on_sketch: false }])
    open()
    await screen.findByText('Object already exists')
    expect(screen.queryByRole('button', { name: 'Create separate object' })).toBeNull()
    expect(mocks.add).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Use existing object: Alice Smith' }))
    await waitFor(() => expect(mocks.added).toHaveBeenCalledWith('canonical'))
    expect(mocks.attach).toHaveBeenCalledWith('view-b', ['canonical'], [])
    expect(mocks.add).not.toHaveBeenCalled()
    expect(mocks.refresh).toHaveBeenCalled()
  })

  it('selects an object already on this sketch without moving or rewriting it', async () => {
    mocks.find.mockResolvedValue([{ node: existing, match: 'exact', on_sketch: true }])
    open()
    fireEvent.click(await screen.findByRole('button', { name: 'Use existing object: Alice Smith' }))
    await waitFor(() => expect(mocks.select).toHaveBeenCalledWith('canonical'))
    expect(mocks.attach).not.toHaveBeenCalled()
    expect(mocks.add).not.toHaveBeenCalled()
  })

  it('promotes a secondary match explicitly reused on the current sketch', async () => {
    mocks.find.mockResolvedValue([
      { node: { ...existing, nodeRole: 'secondary' }, match: 'exact', on_sketch: true }
    ])
    open()
    fireEvent.click(await screen.findByRole('button', { name: 'Use existing object: Alice Smith' }))
    await waitFor(() => expect(mocks.select).toHaveBeenCalledWith('canonical'))
    expect(mocks.update).toHaveBeenCalledWith(
      'view-b',
      JSON.stringify({ nodeId: 'canonical', updates: { nodeRole: 'primary' } })
    )
    expect(mocks.attach).not.toHaveBeenCalled()
    expect(mocks.add).not.toHaveBeenCalled()
  })

  it('allows a separate object for similar names, only after explicit choice', async () => {
    mocks.find.mockResolvedValue([{ node: existing, match: 'possible', on_sketch: false }])
    open()
    const create = await screen.findByRole('button', { name: 'Create separate object' })
    expect(mocks.add).not.toHaveBeenCalled()
    fireEvent.click(create)
    await waitFor(() => expect(mocks.add).toHaveBeenCalledWith('view-b', JSON.stringify(candidate)))
    expect(mocks.attach).not.toHaveBeenCalled()
  })

  it('does not create on a failed check and can retry the check', async () => {
    mocks.find.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce([])
    open()
    await screen.findByRole('alert')
    expect(mocks.add).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(mocks.added).toHaveBeenCalledWith('server-id'))
    expect(mocks.find).toHaveBeenCalledTimes(2)
  })

  it('retains candidates on a failed reuse and returns to editing on cancel', async () => {
    mocks.find.mockResolvedValue([{ node: existing, match: 'exact', on_sketch: false }])
    mocks.attach.mockRejectedValue(new Error('offline'))
    open()
    fireEvent.click(await screen.findByRole('button', { name: 'Use existing object: Alice Smith' }))
    await screen.findByRole('alert')
    expect(screen.getByText('Alice Smith')).toBeTruthy()
    expect(mocks.added).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Back to editing' }))
    expect(mocks.cancel).toHaveBeenCalledOnce()
    expect(mocks.add).not.toHaveBeenCalled()
  })

  it('blocks repeated submissions while checking and uses the authoritative returned ID', async () => {
    let resolve!: (matches: []) => void
    mocks.find.mockImplementation(
      () =>
        new Promise<[]>((done) => {
          resolve = done
        })
    )
    mocks.add.mockResolvedValue({ node: existing }) // Concurrent writer created the object.
    open()
    fireEvent.click(screen.getByRole('button', { name: 'Submit form', hidden: true }))
    expect(mocks.find).toHaveBeenCalledOnce()
    expect(mocks.add).not.toHaveBeenCalled()
    await act(async () => resolve([]))
    await waitFor(() => expect(mocks.added).toHaveBeenCalledWith('canonical'))
    expect(mocks.add).toHaveBeenCalledOnce()
  })
})
