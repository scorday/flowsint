// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { GraphNode, GraphEdge } from '@/types'
import type { GraphData } from './utils/types'
import { useGraphControls } from '@/stores/graph-controls-store'
import { useGraphStore } from '@/stores/graph-store'
import GraphViewer from './index'
import { NeighborhoodRootAction, NeighborhoodRootStatus } from '../neighborhood-root-controls'
import { setLanguage } from '@/i18n'

const capture = vi.hoisted(() => {
  const storage = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key)
  })
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    }
  )
  return {
    graph: null as null | {
      graphData: GraphData
      onNodeDragEnd: (node: GraphNode) => void
      onBackgroundClick: (event: MouseEvent) => void
      onNodeClick: (node: GraphNode, event: MouseEvent) => void
    },
    layout: null as null | {
      graphData: GraphData
      saveAllNodePositions: (nodes: GraphNode[], force?: boolean) => void
    },
    minimap: [] as string[],
    selector: [] as string[],
    save: vi.fn(),
    centerAt: vi.fn(),
    zoom: vi.fn()
  }
})

vi.mock('@/components/theme-provider', () => ({ useTheme: () => ({ theme: 'dark' }) }))
vi.mock('@/hooks/use-save-node-positions', () => ({
  useSaveNodePositions: () => ({ saveAllNodePositions: capture.save })
}))
vi.mock('./hooks/use-graph-layout', () => ({
  useGraphLayout: (props: NonNullable<typeof capture.layout>) => {
    capture.layout = props
    return { isRegeneratingLayout: false, regenerateLayout: vi.fn() }
  }
}))
vi.mock('./hooks/use-keyboard-events', () => ({ useKeyboardEvents: () => {} }))
vi.mock('./background', () => ({ Background: () => null }))
vi.mock('./utils/image-cache', () => ({
  preloadImage: vi.fn(async () => {}),
  preloadIconByName: vi.fn(async () => {}),
  preloadExternalImage: vi.fn(async () => {}),
  preloadFlagImage: vi.fn(async () => {})
}))
vi.mock('./components/minimap', () => ({
  default: ({ nodes }: { nodes: GraphNode[] }) => {
    capture.minimap = nodes.map((node) => node.id)
    return null
  }
}))
vi.mock('./components/graph-selector-overlay', () => ({
  GraphSelectorOverlay: ({ nodes }: { nodes: GraphNode[] }) => {
    capture.selector = nodes.map((node) => node.id)
    return null
  }
}))
vi.mock('react-force-graph-2d', async () => {
  const { forwardRef, useImperativeHandle } = await import('react')
  return {
    default: forwardRef((props: NonNullable<typeof capture.graph>, ref) => {
      capture.graph = props
      useImperativeHandle(ref, () => ({
        zoomToFit: vi.fn(),
        centerAt: capture.centerAt,
        zoom: capture.zoom
      }))
      return null
    })
  }
})

const nodes = ['root', 'alice', 'bob', 'second-hop'].map(
  (id, x): GraphNode => ({
    id,
    nodeLabel: id,
    nodeType: 'socialaccount',
    nodeProperties: { original: id },
    nodeMetadata: {},
    nodeColor: null,
    nodeIcon: null,
    nodeImage: null,
    nodeFlag: null,
    nodeShape: null,
    nodeSize: 4,
    x,
    y: x
  })
)
const edges: GraphEdge[] = [
  { id: 'root-alice', source: 'root', target: 'alice', label: 'FRIEND_OF' },
  { id: 'bob-root', source: 'bob', target: 'root', label: 'FRIEND_OF' },
  { id: 'alice-bob', source: 'alice', target: 'bob', label: 'FRIEND_OF' },
  { id: 'second', source: 'alice', target: 'second-hop', label: 'FRIEND_OF' }
]

beforeEach(() => {
  capture.save.mockClear()
  capture.centerAt.mockClear()
  capture.zoom.mockClear()
  setLanguage('en')
  useGraphStore.getState().updateGraphData(nodes, edges)
  useGraphStore.getState().setCurrentNodeId('root')
  useGraphControls.setState({
    highlightSelectionLinks: false,
    hideRootLinks: false,
    onlyRootNeighborhood: false,
    neighborhoodRoot: null
  })
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  useGraphStore.getState().reset()
  useGraphControls.setState({
    highlightSelectionLinks: false,
    hideRootLinks: false,
    onlyRootNeighborhood: false,
    neighborhoodRoot: null
  })
})

it.each(['en', 'ru'] as const)(
  'inspects friends without changing the graph and switches root explicitly in %s',
  (language) => {
    setLanguage(language)
    const Inspector = () => {
      const node = useGraphStore((s) => s.getCurrentNode())
      return node ? (
        <section aria-label="Inspector">
          <p>{node.nodeLabel}</p>
          <NeighborhoodRootAction node={node} graphId="sketch" />
        </section>
      ) : null
    }
    render(
      <>
        <GraphViewer
          nodes={nodes}
          edges={edges}
          showIcons={false}
          showMinimap
          allowLasso
          sketchId="sketch"
          onNodeClick={(node) => useGraphStore.getState().setCurrentNodeId(node.id)}
        />
        <NeighborhoodRootStatus graphId="sketch" />
        <Inspector />
      </>
    )
    act(() => useGraphControls.getState().setOnlyRootNeighborhood(true))
    const before = capture.graph!.graphData
    const rootLabel = language === 'ru' ? 'Показать корень фильтра: root' : 'Show filter root: root'
    const makeRoot = language === 'ru' ? 'Сделать корнем фильтра' : 'Make filter root'
    expect(screen.getByRole('button', { name: rootLabel })).toBeTruthy()
    vi.useFakeTimers()
    act(() => {
      capture.graph!.onNodeClick(
        before.nodes.find((node) => node.id === 'alice')!,
        new MouseEvent('click')
      )
      vi.runAllTimers()
    })
    expect(useGraphStore.getState().currentNodeId).toBe('alice')
    expect(capture.graph!.graphData).toBe(before)
    expect(capture.minimap).toEqual(['root', 'alice', 'bob'])
    expect(capture.selector).toEqual(['root', 'alice', 'bob'])
    expect(capture.centerAt).not.toHaveBeenCalled()
    expect(capture.zoom).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: rootLabel })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: makeRoot }))
    expect(useGraphControls.getState().neighborhoodRoot).toEqual({
      graphId: 'sketch',
      nodeId: 'alice'
    })
    expect(capture.graph!.graphData.nodes.map((node) => node.id)).toEqual([
      'root',
      'alice',
      'bob',
      'second-hop'
    ])
    const pinnedLabel = language === 'ru' ? 'Корень фильтра закреплён' : 'Filter root pinned'
    expect(screen.getByRole('button', { name: pinnedLabel }).hasAttribute('disabled')).toBe(true)
    act(() => useGraphStore.getState().setCurrentNodeId('bob'))
    const showRoot =
      language === 'ru' ? 'Показать корень фильтра: alice' : 'Show filter root: alice'
    fireEvent.click(screen.getByRole('button', { name: showRoot }))
    expect(useGraphStore.getState().currentNodeId).toBe('alice')
    expect(capture.save).not.toHaveBeenCalled()
  }
)

it('filters the actual renderer, minimap and lasso together, restores the graph, and preserves hidden nodes on save', () => {
  render(
    <GraphViewer
      nodes={nodes}
      edges={edges}
      showIcons={false}
      showMinimap
      allowLasso
      sketchId="sketch"
    />
  )
  expect(capture.graph!.graphData.nodes).toHaveLength(4)
  act(() => useGraphControls.getState().setOnlyRootNeighborhood(true))
  const visible = capture.graph!.graphData
  expect(visible.nodes.map((n) => n.id)).toEqual(['root', 'alice', 'bob'])
  expect(visible.links.map((e) => e.id)).toEqual(['root-alice', 'bob-root', 'alice-bob'])
  expect(capture.minimap).toEqual(['root', 'alice', 'bob'])
  expect(capture.selector).toEqual(['root', 'alice', 'bob'])
  expect(capture.save).not.toHaveBeenCalled()

  act(() => useGraphControls.getState().setHideRootLinks(true))
  expect(capture.graph!.graphData.links.map((e) => e.id)).toEqual(['alice-bob'])
  expect(capture.graph!.graphData.nodes[0]).toBe(visible.nodes[0])

  const root = capture.graph!.graphData.nodes[0]
  root.x = 77
  root.y = 88
  act(() => capture.graph!.onNodeDragEnd(root))
  const saved: GraphNode[] = capture.save.mock.calls[0][0]
  expect(saved.map((n) => n.id)).toEqual(nodes.map((n) => n.id))
  expect(saved[0]).toMatchObject({ x: 77, y: 88, nodeProperties: { original: 'root' } })
  expect(saved[3]).toBe(nodes[3])

  act(() => capture.layout!.saveAllNodePositions(capture.graph!.graphData.nodes, true))
  expect(capture.save.mock.lastCall![0]).toHaveLength(4)
  expect(capture.save.mock.lastCall![1]).toBe(true)

  act(() => useGraphControls.setState({ hideRootLinks: false, onlyRootNeighborhood: false }))
  expect(capture.graph!.graphData.nodes.map((n) => n.id)).toEqual(nodes.map((n) => n.id))
  expect(capture.graph!.graphData.links.map((e) => e.id)).toEqual(edges.map((e) => e.id))
})

it('keeps the separate neighbors preview unaffected by main graph view toggles', () => {
  useGraphControls.setState({ hideRootLinks: true, onlyRootNeighborhood: true })
  render(
    <GraphViewer
      nodes={nodes}
      edges={edges}
      showIcons={false}
      showMinimap={false}
      showMinimalControls
    />
  )
  expect(capture.graph!.graphData.nodes).toHaveLength(4)
  expect(capture.graph!.graphData.links).toHaveLength(4)
})

it.each([
  [true, false],
  [false, true],
  [true, true]
])('keeps neighborhood=%s and hidden root links=%s after clicking the canvas', (only, hide) => {
  render(
    <GraphViewer
      nodes={nodes}
      edges={edges}
      showIcons={false}
      showMinimap
      allowLasso
      sketchId="sketch"
      onBackgroundClick={() => {
        const store = useGraphStore.getState()
        store.setCurrentNodeId(null)
        store.clearSelectedNodes()
        store.clearSelectedEdges()
        store.setCurrentEdgeId(null)
      }}
    />
  )
  act(() =>
    useGraphControls.setState({
      highlightSelectionLinks: true,
      onlyRootNeighborhood: only,
      hideRootLinks: hide
    })
  )
  const before = capture.graph!.graphData
  act(() => capture.graph!.onBackgroundClick(new MouseEvent('click')))
  expect(useGraphStore.getState().currentNodeId).toBeNull()
  expect(capture.graph!.graphData).toBe(before)
  expect(capture.graph!.graphData.nodes.map((n) => n.id)).toEqual(before.nodes.map((n) => n.id))
  expect(capture.graph!.graphData.links.map((e) => e.id)).toEqual(before.links.map((e) => e.id))
  expect(capture.minimap).toEqual(before.nodes.map((n) => n.id))
  expect(capture.selector).toEqual(before.nodes.map((n) => n.id))
  expect(useGraphControls.getState().onlyRootNeighborhood).toBe(only)
  expect(useGraphControls.getState().hideRootLinks).toBe(hide)
  act(() => useGraphControls.setState({ onlyRootNeighborhood: false, hideRootLinks: false }))
  expect(capture.graph!.graphData.nodes.map((n) => n.id)).toEqual(nodes.map((n) => n.id))
  expect(capture.graph!.graphData.links.map((e) => e.id)).toEqual(edges.map((e) => e.id))
})
