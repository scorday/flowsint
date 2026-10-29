// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useGraphStore } from '@/stores/graph-store'
import { useGraphControls } from '@/stores/graph-controls-store'
import { setLanguage, translateFor } from '@/i18n'
import type { GraphEdge, GraphNode } from '@/types'
import type { LocationPoint } from './map'
import MapPanel from './map-panel'
import Filters from '@/components/sketches/filters/filters'

vi.hoisted(() => {
  const storage = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key)
  })
})

// Assert the actual locations passed to the renderer without requiring WebGL
// or external map tiles/geocoding in a component integration test.
vi.mock('./map', () => ({
  MapFromAddress: ({ locations }: { locations: LocationPoint[] }) => (
    <ul aria-label="Map locations">
      {locations.map((loc) => (
        <li key={loc.nodeId}>{loc.label}</li>
      ))}
    </ul>
  )
}))

const node = (id: string, nodeType: string, nodeProperties = {}): GraphNode => ({
  id,
  nodeType,
  nodeLabel: id,
  nodeProperties,
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
const nodes = [
  node('aircraft', 'aircraft'),
  node('flight-a', 'flight', {
    aircraft_hex: '405455',
    callsigns: ['ABC123'],
    first_seen_at: '2026-10-16T10:00:00Z',
    last_seen_at: '2026-10-16T11:00:00Z'
  }),
  node('flight-b', 'flight', {
    aircraft_hex: '405455',
    callsigns: ['ABC456'],
    first_seen_at: '2026-10-16T12:00:00Z',
    last_seen_at: '2026-10-16T13:00:00Z'
  }),
  node('position-a', 'aircraftposition', { latitude: 0, longitude: 12 }),
  node('position-b', 'aircraftposition', { latitude: 51, longitude: 0 }),
  node('location', 'location', { latitude: 48, longitude: 2 })
]
const edge = (source: string, target: string, label = 'HAS_POSITION_OBSERVATION'): GraphEdge => ({
  id: `${source}-${target}-${label}`,
  source,
  target,
  label
})
const edges = [
  edge('aircraft', 'flight-a', 'HAS_OBSERVED_FLIGHT'),
  edge('aircraft', 'flight-b', 'HAS_OBSERVED_FLIGHT'),
  edge('aircraft', 'position-a'),
  edge('aircraft', 'position-b'),
  edge('flight-a', 'position-a'),
  edge('flight-b', 'position-b'),
  edge('flight-a', 'location', 'RELATED_TO')
]

beforeEach(() => {
  setLanguage('en')
  useGraphControls.getState().setView('map')
  useGraphStore.getState().reset()
  useGraphStore.getState().updateGraphData(nodes, edges)
  useGraphStore.getState().setFilters({
    types: ['aircraft', 'flight', 'aircraftposition', 'location'].map((type) => ({
      type,
      checked: true
    })),
    rules: [],
    mapFlightId: null
  })
})
afterEach(() => {
  cleanup()
  useGraphStore.getState().reset()
  setLanguage('en')
})

it('applies type filters to map markers and hides everything when all types are unchecked', () => {
  render(<MapPanel />)
  expect(screen.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
    'position-a',
    'position-b',
    'location'
  ])
  act(() => useGraphStore.getState().toggleTypeFilter({ type: 'aircraftposition', checked: true }))
  expect(screen.getAllByRole('listitem').map((item) => item.textContent)).toEqual(['location'])
  act(() => {
    const { filters, setFilters } = useGraphStore.getState()
    setFilters({
      ...filters,
      types: filters.types.map((filter) => ({ ...filter, checked: false }))
    })
  })
  expect(screen.queryByRole('listitem')).toBeNull()
  expect(screen.getByText('No locations match the current filters.')).toBeTruthy()
  expect(useGraphStore.getState().filteredEdges).toEqual([])
})

it('restricts the map to direct observations of one flight, intersects type filters, and resets', () => {
  render(<MapPanel />)
  act(() => {
    const { filters, setFilters } = useGraphStore.getState()
    setFilters({ ...filters, mapFlightId: 'flight-a' })
  })
  expect(screen.getAllByRole('listitem').map((item) => item.textContent)).toEqual(['position-a'])
  // The Flight type can be hidden without losing its observation links.
  act(() => useGraphStore.getState().toggleTypeFilter({ type: 'flight', checked: true }))
  expect(screen.getAllByRole('listitem').map((item) => item.textContent)).toEqual(['position-a'])
  act(() => useGraphStore.getState().toggleTypeFilter({ type: 'aircraftposition', checked: true }))
  expect(screen.queryByRole('listitem')).toBeNull()
  act(() => useGraphStore.getState().reset())
  expect(useGraphStore.getState().filters.mapFlightId).toBeNull()
  expect(screen.getAllByRole('listitem')).toHaveLength(3)
})

it('does not fall back to every position for a missing flight or a flight with no observations', () => {
  render(<MapPanel />)
  act(() => {
    const { filters, setFilters } = useGraphStore.getState()
    setFilters({ ...filters, mapFlightId: 'missing-flight' })
  })
  expect(screen.queryByRole('listitem')).toBeNull()
  act(() => {
    const { filters, setFilters, setEdges } = useGraphStore.getState()
    setFilters({ ...filters, mapFlightId: 'flight-a' })
    setEdges([])
  })
  expect(screen.queryByRole('listitem')).toBeNull()
})

it.each(['en', 'ru'] as const)('selects and clears a flight from map Filters in %s', (language) => {
  setLanguage(language)
  // Keyboard navigation exercises the real Radix Select and its store wiring.
  HTMLElement.prototype.scrollIntoView = vi.fn()
  render(
    <>
      <Filters>
        <button>Filters</button>
      </Filters>
      <MapPanel />
    </>
  )
  fireEvent.click(screen.getByRole('button', { name: 'Filters' }))
  const select = screen.getByRole('combobox', {
    name: translateFor(language, 'Flight')
  })
  fireEvent.keyDown(select, { key: 'ArrowDown' })
  const option = screen.getByRole('option', { name: /ABC123/ })
  fireEvent.click(option)
  expect(useGraphStore.getState().filters.mapFlightId).toBe('flight-a')
  expect(
    screen
      .getAllByRole('listitem')
      .map((item) => item.textContent)
      .filter((text) => text?.startsWith('position'))
  ).toEqual(['position-a'])
  fireEvent.keyDown(select, { key: 'ArrowDown' })
  fireEvent.click(
    screen.getByRole('option', { name: language === 'ru' ? 'Все полёты' : 'All flights' })
  )
  expect(useGraphStore.getState().filters.mapFlightId).toBeNull()
  expect(screen.getByText('position-b')).toBeTruthy()
})

it('excludes invalid coordinates while accepting zero and numeric coordinate strings', () => {
  act(() =>
    useGraphStore
      .getState()
      .setNodes([
        node('zero', 'aircraftposition', { latitude: 0, longitude: '0' }),
        node('invalid', 'aircraftposition', { latitude: 'invalid', longitude: 5 }),
        node('missing', 'aircraftposition', { latitude: null, longitude: 5 }),
        node('outside', 'aircraftposition', { latitude: 100, longitude: 5 })
      ])
  )
  render(<MapPanel />)
  expect(screen.getAllByRole('listitem').map((item) => item.textContent)).toEqual(['zero'])
})
