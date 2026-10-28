import { useMemo } from 'react'
import type { GraphEdge } from '@/types'
import type { LinkObject } from 'react-force-graph-2d'

const endpointId = (endpoint: LinkObject['source']) =>
  typeof endpoint === 'object' ? endpoint?.id : endpoint

export const useComputedHighlights = (highlightedNodeIds: string[], edges: GraphEdge[]) => {
  const highlightNodes = useMemo(() => new Set(highlightedNodeIds), [highlightedNodeIds])

  const highlightLinks = useMemo(() => {
    const links = new Set<string>()
    const nodeIdSet = new Set(highlightedNodeIds)

    edges.forEach((edge) => {
      const sourceId = endpointId(edge.source)
      const targetId = endpointId(edge.target)

      // Only highlight links where BOTH nodes are highlighted
      if (
        sourceId !== undefined &&
        targetId !== undefined &&
        nodeIdSet.has(String(sourceId)) &&
        nodeIdSet.has(String(targetId))
      ) {
        links.add(`${sourceId}-${targetId}`)
      }
    })

    return links
  }, [highlightedNodeIds, edges])

  return { highlightNodes, highlightLinks }
}
