import type { FeatureCollection, LineString, MultiLineString } from 'geojson'
import type { GraphEdge, GraphNode } from '@/types'
import type { LocationPoint } from './map'

export type FlightRoutes = FeatureCollection<
  LineString | MultiLineString,
  { flightId: string; color: string }
>
type Coordinate = [number, number]

// Cut at the dateline so a Pacific flight does not draw across the whole map.
function routeGeometry(coordinates: Coordinate[]): LineString | MultiLineString {
  const segments: Coordinate[][] = [[coordinates[0]]]
  for (const next of coordinates.slice(1)) {
    const segment = segments[segments.length - 1]
    const previous = segment[segment.length - 1]
    const delta = next[0] - previous[0]
    if (Math.abs(delta) <= 180) {
      segment.push(next)
      continue
    }
    const longitude = next[0] + (delta > 180 ? -360 : 360)
    if (longitude === previous[0]) {
      segment.push([previous[0], next[1]])
      continue
    }
    const boundary = longitude > previous[0] ? 180 : -180
    const fraction = (boundary - previous[0]) / (longitude - previous[0])
    const latitude = previous[1] + (next[1] - previous[1]) * fraction
    segment.push([boundary, latitude])
    segments.push([[-boundary, latitude], next])
  }
  return segments.length === 1
    ? { type: 'LineString', coordinates: segments[0] }
    : { type: 'MultiLineString', coordinates: segments }
}

export function getFlightRoutes(
  locations: LocationPoint[],
  nodes: GraphNode[],
  edges: GraphEdge[],
  selectedFlightId: string | null | undefined,
  nodeColors: Record<string, string>
): FlightRoutes {
  const positions = new Map(
    locations.flatMap((point) => {
      const time = point.observedAt ? Date.parse(point.observedAt) : NaN
      if (
        point.nodeType !== 'aircraftposition' ||
        !point.nodeId ||
        point.lat === undefined ||
        point.lon === undefined ||
        !Number.isFinite(point.lat) ||
        !Number.isFinite(point.lon) ||
        Math.abs(point.lat) > 90 ||
        Math.abs(point.lon) > 180 ||
        !Number.isFinite(time)
      )
        return []
      return [[point.nodeId, { time, coordinates: [point.lon, point.lat] as Coordinate }] as const]
    })
  )
  const flightPositions = new Map<string, Set<string>>()
  for (const edge of edges) {
    if (edge.label !== 'HAS_POSITION_OBSERVATION' || !positions.has(edge.target)) continue
    const ids = flightPositions.get(edge.source) ?? new Set<string>()
    ids.add(edge.target)
    flightPositions.set(edge.source, ids)
  }

  return {
    type: 'FeatureCollection',
    features: nodes.flatMap((flight) => {
      if (flight.nodeType !== 'flight' || (selectedFlightId && flight.id !== selectedFlightId))
        return []
      const ordered = [...(flightPositions.get(flight.id) ?? [])]
        .map((id) => positions.get(id)!)
        .sort((a, b) => a.time - b.time)
      if (ordered.length < 2) return []
      return [
        {
          type: 'Feature' as const,
          id: flight.id,
          properties: {
            flightId: flight.id,
            color: flight.nodeColor || nodeColors.flight || '#38bdf8'
          },
          geometry: routeGeometry(ordered.map((point) => point.coordinates))
        }
      ]
    })
  }
}
