import { useState } from 'react'

// Clearing the inspector selection must not clear the active view's root.
// Keep it scoped to this graph and release it when both view filters are off.
export const useNeighborhoodRoot = (
  currentNodeId: string | null,
  enabled: boolean,
  graphId?: string
) => {
  const [root, setRoot] = useState({
    graphId,
    nodeId: enabled ? currentNodeId : null
  })
  const previousRoot = root.graphId === graphId ? root.nodeId : null
  const nodeId = enabled ? (currentNodeId ?? previousRoot) : null

  // Derive before committing the render, avoiding a frame with an unfiltered graph.
  if (root.graphId !== graphId || root.nodeId !== nodeId) {
    setRoot({ graphId, nodeId })
  }

  return nodeId
}
