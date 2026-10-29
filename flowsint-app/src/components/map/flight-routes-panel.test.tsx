// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type { GraphEdge, GraphNode } from '@/types'
import { useGraphStore } from '@/stores/graph-store'
import MapPanel from './map-panel'
import { MapFromAddress } from './map'

const mapApi = vi.hoisted(() => ({
  loaded: vi.fn(() => false),
  once: vi.fn((_event: string, _callback: () => void) => {}),
  off: vi.fn(),
  on: vi.fn(),
  setProjection: vi.fn(),
  fitBounds: vi.fn(),
  flyTo: vi.fn()
}))

vi.hoisted(() => {
  const storage = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key)
  })
})
vi.mock('../theme-provider', () => ({ useTheme: () => ({ theme: 'dark' }) }))
vi.mock('maplibre-gl', () => ({
  default: {
    setWorkerUrl: vi.fn(),
    LngLatBounds: class {
      extend() {
        return this
      }
    }
  }
}))
vi.mock('@/components/sketches/graph/utils/image-cache', () => ({
  preloadImage: vi.fn(async () => undefined),
  getCachedImage: vi.fn()
}))
vi.mock('react-map-gl/maplibre', async () => {
  const { forwardRef, useImperativeHandle } = await import('react')
  return {
    default: forwardRef(
      ({ children, onLoad }: { children: ReactNode; onLoad: () => void }, ref) => {
        useImperativeHandle(ref, () => ({ getMap: () => mapApi }))
        return (
          <div>
            <button onClick={onLoad}>Map ready</button>
            {children}
          </div>
        )
      }
    ),
    Marker: () => null,
    Popup: () => null,
    Source: ({ id, data, children }: { id: string; data: unknown; children: ReactNode }) => (
      <div data-testid={id} data-geojson={JSON.stringify(data)}>
        {children}
      </div>
    ),
    Layer: ({ id }: { id: string }) => <div data-testid={id} />
  }
})

let client: QueryClient
afterEach(() => {
  cleanup()
  client.clear()
  useGraphStore.getState().reset()
  vi.clearAllMocks()
})

it('fits the route once map data is ready, including subsequent route changes', () => {
  client = new QueryClient()
  const locations = [
    { lat: 50, lon: 1 },
    { lat: 51, lon: 2 }
  ]
  const view = (points: typeof locations) => (
    <QueryClientProvider client={client}>
      <MapFromAddress locations={points} centerOnFirst={false} />
    </QueryClientProvider>
  )
  const { rerender, unmount } = render(view(locations))
  expect(mapApi.fitBounds).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Map ready' }))
  expect(mapApi.once).toHaveBeenLastCalledWith('idle', expect.any(Function))
  const firstReady = mapApi.once.mock.calls[mapApi.once.mock.calls.length - 1][1]
  act(() => firstReady())
  expect(mapApi.fitBounds).toHaveBeenCalledTimes(1)

  rerender(
    view([
      { lat: 48, lon: 2 },
      { lat: 50, lon: 4 }
    ])
  )
  expect(mapApi.off).toHaveBeenCalledWith('idle', firstReady)
  const nextReady = mapApi.once.mock.calls[mapApi.once.mock.calls.length - 1][1]
  act(() => nextReady())
  expect(mapApi.fitBounds).toHaveBeenCalledTimes(2)
  unmount()
  expect(mapApi.off).toHaveBeenCalledWith('idle', nextReady)
})

it('updates the actual map source when switching flights and removes it with hidden positions', () => {
  const node = (id: string, nodeType: string, nodeProperties = {}): GraphNode => ({
    id,
    nodeType,
    nodeProperties,
    nodeLabel: id,
    nodeSize: 1,
    nodeColor: null,
    nodeIcon: null,
    nodeImage: null,
    nodeFlag: null,
    nodeShape: null,
    nodeMetadata: {},
    x: 0,
    y: 0
  })
  const flight = (id: string) => node(id, 'flight')
  const position = (id: string, hour: number) =>
    node(id, 'aircraftposition', {
      latitude: 50,
      longitude: hour,
      observed_at: `2026-10-16T${hour}:00:00Z`
    })
  const nodes = [
    flight('a'),
    flight('b'),
    position('a1', 10),
    position('a2', 11),
    position('b1', 12),
    position('b2', 13)
  ]
  const edges = ['a1', 'a2', 'b1', 'b2'].map((id) => ({
    id,
    source: id[0],
    target: id,
    label: 'HAS_POSITION_OBSERVATION'
  })) as GraphEdge[]
  useGraphStore.getState().reset()
  useGraphStore.getState().updateGraphData(nodes, edges)
  useGraphStore.getState().setFilters({ types: [], rules: [], mapFlightId: 'a' })
  client = new QueryClient()
  render(
    <QueryClientProvider client={client}>
      <MapPanel />
    </QueryClientProvider>
  )
  const routeIds = () =>
    JSON.parse(
      screen.getByTestId('observed-flight-routes').getAttribute('data-geojson')!
    ).features.map((f: { id: string }) => f.id)
  expect(routeIds()).toEqual(['a'])
  expect(screen.getByTestId('observed-flight-routes-line')).toBeTruthy()
  act(() => {
    const { filters, setFilters } = useGraphStore.getState()
    setFilters({ ...filters, mapFlightId: 'b' })
  })
  expect(routeIds()).toEqual(['b'])
  act(() => {
    const { filters, setFilters } = useGraphStore.getState()
    setFilters({ ...filters, mapFlightId: null })
  })
  expect(routeIds()).toEqual(['a', 'b'])
  act(() => {
    const { filters, setFilters } = useGraphStore.getState()
    setFilters({ ...filters, types: [{ type: 'aircraftposition', checked: false }] })
  })
  expect(screen.queryByTestId('observed-flight-routes')).toBeNull()
})
