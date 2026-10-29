import type { GraphEdge, GraphNode } from '@/types'

const endpointId = (endpoint: string | { id: string }) =>
  typeof endpoint === 'object' ? endpoint.id : endpoint

export const getNeighborhoodView = (
  nodes: GraphNode[],
  edges: GraphEdge[],
  rootId: string | null,
  onlyRootNeighborhood: boolean,
  hideRootLinks: boolean
) => {
  if ((!onlyRootNeighborhood && !hideRootLinks) || !rootId || !nodes.some((n) => n.id === rootId)) {
    return { nodes, edges, active: false }
  }

  const availableIds = new Set(nodes.map((node) => node.id))
  const neighborhood = new Set([rootId])
  edges.forEach((edge) => {
    const source = endpointId(edge.source)
    const target = endpointId(edge.target)
    if (source === rootId && availableIds.has(target)) neighborhood.add(target)
    if (target === rootId && availableIds.has(source)) neighborhood.add(source)
  })

  return {
    nodes: onlyRootNeighborhood ? nodes.filter((node) => neighborhood.has(node.id)) : nodes,
    edges: edges.filter((edge) => {
      const source = endpointId(edge.source)
      const target = endpointId(edge.target)
      return (
        neighborhood.has(source) &&
        neighborhood.has(target) &&
        (!hideRootLinks || (source !== rootId && target !== rootId))
      )
    }),
    active: true
  }
}
