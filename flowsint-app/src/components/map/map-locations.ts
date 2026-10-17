import type { GraphEdge, GraphNode } from '@/types'
import type { LocationPoint } from './map'

function coordinate(value: unknown, limit: number): number | undefined {
  if (typeof value !== 'number' && typeof value !== 'string') return undefined
  if (typeof value === 'string' && !value.trim()) return undefined
  const parsed = Number(value)
  return Number.isFinite(parsed) && Math.abs(parsed) <= limit ? parsed : undefined
}

export function getMapLocations(
  nodes: GraphNode[],
  edges: GraphEdge[],
  flightId: string | null | undefined,
  nodeColors: Record<string, string>
): LocationPoint[] {
  // Use direct Flight -> observation edges, never the aircraft's neighbors:
  // an aircraft connects observations belonging to multiple flights.
  const flightPositionIds = flightId
    ? new Set(
        edges
          .filter((edge) => edge.source === flightId && edge.label === 'HAS_POSITION_OBSERVATION')
          .map((edge) => edge.target)
      )
    : null

  return nodes.flatMap((node) => {
    if (flightPositionIds && !flightPositionIds.has(node.id)) return []
    const properties = node.nodeProperties
    const lat = coordinate(properties.latitude, 90)
    const lon = coordinate(properties.longitude, 180)
    if (node.nodeType !== 'location' && (lat === undefined || lon === undefined)) return []
    const address = [properties.address, properties.city, properties.country]
      .filter((part): part is string => typeof part === 'string' && !!part.trim())
      .join(', ')
    return [
      {
        nodeId: node.id,
        lat,
        lon,
        address,
        label: node.nodeLabel || address,
        nodeType: node.nodeType,
        observedAt: typeof properties.observed_at === 'string' ? properties.observed_at : undefined,
        color: node.nodeColor || nodeColors[node.nodeType] || null,
        icon: node.nodeIcon
      }
    ]
  })
}
