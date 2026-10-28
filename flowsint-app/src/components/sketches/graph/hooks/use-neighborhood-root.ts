import { useEffect } from 'react'
import { useGraphControls } from '@/stores/graph-controls-store'

// Inspector selection and filter root are independent. An explicit action is
// required to replace an existing root while a view filter is enabled.
export const useNeighborhoodRoot = (
  currentNodeId: string | null,
  enabled: boolean,
  graphId?: string,
  manageRoot = true
) => {
  const root = useGraphControls((s) => s.neighborhoodRoot)
  const setRoot = useGraphControls((s) => s.setNeighborhoodRoot)
  const pinnedRoot = root?.graphId === graphId ? root?.nodeId : null
  const nodeId = enabled ? (pinnedRoot ?? currentNodeId) : null

  useEffect(() => {
    // Secondary neighbor previews must not clear the main graph's root.
    if (!manageRoot) return
    if (nodeId === null) {
      if (root !== null) setRoot(null)
    } else if (root?.graphId !== graphId || root?.nodeId !== nodeId) {
      setRoot({ graphId, nodeId })
    }
  }, [root, graphId, nodeId, manageRoot, setRoot])

  return nodeId
}
