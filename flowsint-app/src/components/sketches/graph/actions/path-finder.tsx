import { GraphExplorer } from '../../graph-explorer'
import { useTranslation } from '@/i18n'
import { useCallback } from 'react'
import { X } from 'lucide-react'
import { useGraphStore } from '@/stores/graph-store'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ResizableContainer } from '@/components/ui/resizable-container'
import { useNodesDisplaySettings } from '@/stores/node-display-settings'

export function PathFinder() {
  return <GraphExplorer />
}

export function PathPanel() {
  const { t } = useTranslation()

  const path = useGraphStore((s) => s.path)
  const setPath = useGraphStore((s) => s.setPath)
  const setHighlightedNodes = useGraphStore((s) => s.setHighlightedNodes)
  const setCurrentNodeId = useGraphStore((s) => s.setCurrentNodeId)
  const nodesMapping = useGraphStore((s) => s.nodesMapping)
  const nodeColors = useNodesDisplaySettings((s) => s.colors)

  const handleClose = useCallback(() => {
    setPath(null)
    setHighlightedNodes([])
  }, [setPath, setHighlightedNodes])

  const handleNodeClick = useCallback(
    (nodeId: string) => {
      setCurrentNodeId(nodeId)
    },
    [setCurrentNodeId]
  )

  if (!path) return null

  return (
    <div className="absolute top-2 right-2 z-50">
      <ResizableContainer
        defaultWidth={260}
        defaultHeight={320}
        minWidth={200}
        minHeight={160}
        maxWidth={500}
        maxHeight={600}
        handles={['se', 'sw']}
        storageKey="resizable-path-panel"
        className="rounded-xl border bg-card shadow-lg"
      >
        <div className="flex flex-col h-full">
          <div className="flex items-center justify-between px-3 py-2 border-b shrink-0">
            <span className="text-sm font-medium truncate">
              {t('Path (')}
              {path.nodes.length} {t(' nodes)')}
            </span>
            <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0" onClick={handleClose}>
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden">
            <div className="p-2 space-y-1">
              {path.nodes.map((node, index) => {
                const edge = index < path.edges.length ? path.edges[index] : null
                const graphNode = nodesMapping.get(node.id)
                const color =
                  graphNode?.nodeColor ||
                  nodeColors[node.node_type as keyof typeof nodeColors] ||
                  '#888'

                return (
                  <div key={node.id} className="overflow-hidden">
                    <button
                      onClick={() => handleNodeClick(node.id)}
                      className="w-full text-left px-2 py-1.5 rounded hover:bg-muted flex items-center gap-2 overflow-hidden"
                    >
                      <div
                        className="w-2 h-2 rounded-full shrink-0"
                        style={{ backgroundColor: color }}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="text-sm truncate">{node.label}</div>
                        <Badge variant="secondary" className="px-1 max-w-full truncate block">
                          {node.node_type}
                        </Badge>
                      </div>
                    </button>
                    {edge && (
                      <div className="flex items-center gap-2 px-2 py-0.5 ml-3 overflow-hidden">
                        <div className="w-px h-4 bg-border shrink-0" />
                        <span className="text-[10px] text-muted-foreground truncate block min-w-0">
                          {edge.label}
                        </span>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      </ResizableContainer>
    </div>
  )
}
