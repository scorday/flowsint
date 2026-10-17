import { expect, it } from 'vitest'
import type { GraphEdge, GraphNode } from '@/types'
import type { LocationPoint } from './map'
import { getFlightRoutes } from './flight-routes'

const flight = (id: string): GraphNode => ({ id, nodeType: 'flight', nodeColor: null }) as GraphNode
const edge = (source: string, target: string, label = 'HAS_POSITION_OBSERVATION'): GraphEdge =>
  ({ id: `${source}-${target}`, source, target, label }) as GraphEdge
const point = (nodeId: string, hour: number, lon = hour, lat = 50): LocationPoint => ({
  nodeId,
  nodeType: 'aircraftposition',
  observedAt: `2026-10-16T${String(hour).padStart(2, '0')}:00:00Z`,
  lat,
  lon
})
const flights = [flight('a'), flight('b')]
const locations = [point('a2', 12), point('b1', 14), point('a1', 10), point('b2', 15)]
const edges = [edge('a', 'a2'), edge('a', 'a1'), edge('b', 'b1'), edge('b', 'b2')]

it('orders samples by observation time and keeps flights of the same aircraft separate', () => {
  const routes = getFlightRoutes(locations, flights, edges, null, { flight: '#80BF80' })
  expect(routes.features.map((feature) => feature.id)).toEqual(['a', 'b'])
  expect(routes.features[0].geometry).toEqual({
    type: 'LineString',
    coordinates: [
      [10, 50],
      [12, 50]
    ]
  })
  expect(routes.features[1].geometry).toEqual({
    type: 'LineString',
    coordinates: [
      [14, 50],
      [15, 50]
    ]
  })
  expect(routes.features[0].properties.color).toBe('#80BF80')
})

it('uses only direct flight edges and deduplicates repeated relationships', () => {
  const routes = getFlightRoutes(
    locations,
    flights,
    [...edges, edge('aircraft', 'b1'), edge('a', 'b1', 'RELATED_TO'), edge('a', 'a1')],
    'a',
    {}
  )
  expect(routes.features).toHaveLength(1)
  expect(routes.features[0].geometry.coordinates).toEqual([
    [10, 50],
    [12, 50]
  ])
})

it('respects selection and visible points without falling back to other flights', () => {
  expect(getFlightRoutes(locations, flights, edges, 'b', {}).features.map((f) => f.id)).toEqual([
    'b'
  ])
  expect(getFlightRoutes(locations, flights, edges, 'missing', {}).features).toEqual([])
  expect(getFlightRoutes([locations[0]], flights, edges, 'a', {}).features).toEqual([])
  expect(getFlightRoutes([], flights, edges, null, {}).features).toEqual([])
})

it('ignores undated, invalid and non-aircraft positions and accepts zero coordinates', () => {
  const samples = [
    point('zero', 1, 0, 0),
    point('next', 2, 1, 0),
    { ...point('no-time', 3), observedAt: undefined },
    { ...point('bad-time', 4), observedAt: 'bad' },
    point('invalid', 5, NaN),
    point('outside', 6, 190),
    { ...point('location', 7), nodeType: 'location' }
  ]
  const routes = getFlightRoutes(
    samples,
    [flight('a')],
    samples.map((p) => edge('a', p.nodeId!)),
    null,
    {}
  )
  expect(routes.features[0].geometry.coordinates).toEqual([
    [0, 0],
    [1, 0]
  ])
})

it.each([
  [179, -179, 180],
  [-179, 179, -180]
])('splits a dateline crossing from %s to %s', (start, end, boundary) => {
  const routes = getFlightRoutes(
    [point('a', 1, start, 10), point('b', 2, end, 12)],
    [flight('f')],
    [edge('f', 'a'), edge('f', 'b')],
    null,
    {}
  )
  expect(routes.features[0].geometry).toEqual({
    type: 'MultiLineString',
    coordinates: [
      [
        [start, 10],
        [boundary, 11]
      ],
      [
        [-boundary, 11],
        [end, 12]
      ]
    ]
  })
})
