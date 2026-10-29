// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import EdgeContextMenu from './context-menu/edge-context-menu'
import SelectedItemsPanel from './panels/selected-items-panel'

const mocks = vi.hoisted(() => ({
  detachEdges: vi.fn(),
  detachNodes: vi.fn(),
  globalDelete: vi.fn(),
  confirm: vi.fn(),
  removeEdges: vi.fn(),
  removeNodes: vi.fn(),
  clearNodes: vi.fn(),
  clearEdges: vi.fn(),
  refresh: vi.fn(),
  updateEdge: vi.fn(),
  canDelete: true,
  selectedNodes: [{ id: 'alice', nodeType: 'individual', nodeLabel: 'Alice' }]
}))
vi.mock('@/api/sketch-service', () => ({
  sketchService: {
    deleteEdges: mocks.detachEdges,
    deleteNodes: mocks.detachNodes,
    deleteFromInvestigation: mocks.globalDelete
  }
}))
vi.mock('@/i18n', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@tanstack/react-router', () => ({
  useParams: () => ({ id: 'work', investigationId: 'case' })
}))
vi.mock('@/hooks/use-can', () => ({
  usePermissions: () => ({ canEdit: true, canDelete: mocks.canDelete })
}))
vi.mock('@/components/use-confirm-dialog', () => ({
  useConfirm: () => ({ confirm: mocks.confirm })
}))
vi.mock('@/stores/graph-controls-store', () => ({
  useGraphControls: (select: any) => select({ refetchGraph: mocks.refresh })
}))
vi.mock('@/stores/graph-store', () => ({
  useGraphStore: (select: any) =>
    select({
      selectedNodes: mocks.selectedNodes,
      removeEdges: mocks.removeEdges,
      removeNodes: mocks.removeNodes,
      clearSelectedNodes: mocks.clearNodes,
      clearSelectedEdges: mocks.clearEdges,
      updateEdge: mocks.updateEdge
    })
}))
vi.mock('@/stores/layout-store', () => ({
  useLayoutStore: (select: any) => select({ openChat: vi.fn() })
}))
vi.mock('@/stores/node-display-settings', () => ({
  useNodesDisplaySettings: (select: any) => select({ colors: {} })
}))
vi.mock('@/stores/graph-settings-store', () => ({
  useGraphSettingsStore: (select: any) => select({ settings: {} })
}))
vi.mock('@/components/sketches/launch-enricher', () => ({ default: () => null }))
vi.mock('@/components/type-badge', () => ({ TypeBadge: () => null }))
vi.mock('@/components/copy', () => ({ CopyButton: () => null }))
vi.mock('@/components/xyflow/context-menu', () => ({
  default: ({ children }: any) => <div>{children}</div>
}))
vi.mock('sonner', () => ({
  toast: {
    promise: (promise: Promise<unknown>) => {
      promise.catch(() => {})
    },
    success: vi.fn(),
    error: vi.fn()
  }
}))

beforeEach(() => {
  vi.clearAllMocks()
  mocks.canDelete = true
  mocks.confirm.mockResolvedValue(true)
  mocks.detachEdges.mockResolvedValue({})
  mocks.detachNodes.mockResolvedValue({})
  mocks.globalDelete.mockResolvedValue({})
})
afterEach(cleanup)

function show(component: React.ReactNode) {
  const client = new QueryClient()
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  render(<QueryClientProvider client={client}>{component}</QueryClientProvider>)
  return invalidate
}
function edge() {
  return (
    <EdgeContextMenu
      edge={{ id: 'employment', source: 'alice', target: 'company', label: 'WORKS_AT' }}
      wrapperWidth={500}
      wrapperHeight={400}
      setMenu={vi.fn()}
    />
  )
}

describe('Investigation actions', () => {
  it('detaches an edge only after the server succeeds', async () => {
    let complete!: () => void
    mocks.detachEdges.mockReturnValue(
      new Promise<void>((resolve) => {
        complete = resolve
      })
    )
    const invalidate = show(edge())
    fireEvent.click(screen.getByRole('button', { name: 'Remove from sketch' }))
    await waitFor(() =>
      expect(mocks.detachEdges).toHaveBeenCalledWith(
        'work',
        JSON.stringify({ relationshipIds: ['employment'] })
      )
    )
    expect(mocks.removeEdges).not.toHaveBeenCalled()
    complete()
    await waitFor(() => expect(mocks.removeEdges).toHaveBeenCalledWith(['employment']))
    expect(mocks.globalDelete).not.toHaveBeenCalled()
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['investigations', 'case'] })
  })
  it('deletes a canonical edge with a separate confirmation', async () => {
    show(edge())
    fireEvent.click(screen.getByRole('button', { name: 'Delete from investigation' }))
    await waitFor(() => expect(mocks.globalDelete).toHaveBeenCalledWith('work', [], ['employment']))
    expect(mocks.confirm).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Delete relations from investigation?' })
    )
    expect(mocks.detachEdges).not.toHaveBeenCalled()
  })
  it('keeps an edge on the screen when deletion fails', async () => {
    mocks.globalDelete.mockRejectedValue(new Error('unavailable'))
    show(edge())
    fireEvent.click(screen.getByRole('button', { name: 'Delete from investigation' }))
    await waitFor(() => expect(mocks.globalDelete).toHaveBeenCalledOnce())
    expect(mocks.removeEdges).not.toHaveBeenCalled()
  })
  it('editors only see detach and cancelling causes no mutation', async () => {
    mocks.canDelete = false
    mocks.confirm.mockResolvedValue(false)
    show(edge())
    expect(screen.queryByRole('button', { name: 'Delete from investigation' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Remove from sketch' }))
    await waitFor(() => expect(mocks.confirm).toHaveBeenCalledOnce())
    expect(mocks.detachEdges).not.toHaveBeenCalled()
  })
  it('globally deletes selected nodes and invalidates the investigation', async () => {
    const invalidate = show(<SelectedItemsPanel />)
    fireEvent.click(screen.getByRole('button', { name: 'Delete from investigation' }))
    await waitFor(() => expect(mocks.removeNodes).toHaveBeenCalledWith(['alice']))
    expect(mocks.globalDelete).toHaveBeenCalledWith('work', ['alice'], [])
    expect(mocks.detachNodes).not.toHaveBeenCalled()
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['investigations', 'case'] })
  })
  it('keeps selected nodes on a failed detach', async () => {
    mocks.detachNodes.mockRejectedValue(new Error('unavailable'))
    show(<SelectedItemsPanel />)
    fireEvent.click(screen.getByRole('button', { name: 'Remove from sketch' }))
    await waitFor(() => expect(mocks.detachNodes).toHaveBeenCalledOnce())
    expect(mocks.removeNodes).not.toHaveBeenCalled()
    expect(mocks.clearNodes).not.toHaveBeenCalled()
  })
})
