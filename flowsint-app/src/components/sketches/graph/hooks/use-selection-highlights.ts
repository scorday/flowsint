import { useMemo } from 'react'
import type { GraphEdge } from '@/types'
import { useComputedHighlights } from './use-computed-highlights'

// Include the existing neighborhood/hover/path highlight as well as manual
// selection, without expanding that group to friends of friends.
export const useSelectionHighlights = (
  nodes: Set<string>,
  links: Set<string>,
  selectedNodeIds: Set<string>,
  edges: GraphEdge[],
  enabled: boolean
) => {
  const nodeIds = useMemo(
    () => (enabled ? Array.from(new Set([...nodes, ...selectedNodeIds])) : []),
    [nodes, selectedNodeIds, enabled]
  )
  const computed = useComputedHighlights(nodeIds, edges)
  const highlightLinks = useMemo(() => {
    if (!enabled) return links
    return new Set([...links, ...computed.highlightLinks])
  }, [links, computed.highlightLinks, enabled])

  return {
    highlightNodes: enabled ? computed.highlightNodes : nodes,
    highlightLinks
  }
}
