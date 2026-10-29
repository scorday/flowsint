import type { GraphEdge, GraphNode } from '@/types'

const endpointId = (endpoint: string | { id: string }) =>
  typeof endpoint === 'object' ? endpoint.id : endpoint

export const getNeighborhoodView = (
  nodes: GraphNode[],
  edges: GraphEdge[],
  rootId: string | null,
  hideRootAndIsolated: boolean
) => {
  if (!hideRootAndIsolated || !rootId || !nodes.some((n) => n.id === rootId)) {
    return { nodes, edges, active: false }
  }

  const availableIds = new Set(nodes.filter((node) => node.id !== rootId).map((node) => node.id))
  const connectedIds = new Set<string>()
  const visibleEdges = edges.filter((edge) => {
    const source = endpointId(edge.source)
    const target = endpointId(edge.target)
    if (!availableIds.has(source) || !availableIds.has(target)) return false
    connectedIds.add(source)
    connectedIds.add(target)
    return true
  })

  return {
    nodes: nodes.filter((node) => connectedIds.has(node.id)),
    edges: visibleEdges,
    active: true
  }
}
