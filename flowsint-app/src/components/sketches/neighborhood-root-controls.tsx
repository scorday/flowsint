import { Pin } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useTranslation } from '@/i18n'
import { useGraphControls } from '@/stores/graph-controls-store'
import { useGraphStore } from '@/stores/graph-store'
import type { GraphNode } from '@/types'

export const NeighborhoodRootStatus = ({ graphId }: { graphId?: string }) => {
  const { t } = useTranslation()
  const enabled = useGraphControls((s) => s.onlyRootNeighborhood || s.hideRootLinks)
  const anchor = useGraphControls((s) => s.neighborhoodRoot)
  const rootId = anchor?.graphId === graphId ? anchor?.nodeId : null
  const root = useGraphStore((s) => (rootId ? s.getNode(rootId) : null))
  const setCurrentNodeId = useGraphStore((s) => s.setCurrentNodeId)

  if (!enabled) return null

  return (
    <div className="min-w-0 px-1 py-0.5">
      {root ? (
        <Button
          variant="ghost"
          size="sm"
          className="h-7 max-w-full justify-start gap-2 px-1"
          aria-label={t('Show filter root: {{name}}', { name: root.nodeLabel || root.id })}
          onClick={() => setCurrentNodeId(root.id)}
        >
          <Pin className="size-3.5 shrink-0 text-primary" />
          <span className="truncate">
            {t('Filter root: {{name}}', { name: root.nodeLabel || root.id })}
          </span>
        </Button>
      ) : (
        <p className="px-1 text-xs">{t('Select a node to pin the filter root')}</p>
      )}
      <p className="px-1 text-[11px] text-muted-foreground">
        {t('Change the root with “Make filter root” in node properties.')}
      </p>
    </div>
  )
}

export const NeighborhoodRootAction = ({
  node,
  graphId
}: {
  node: GraphNode
  graphId?: string
}) => {
  const { t } = useTranslation()
  const enabled = useGraphControls((s) => s.onlyRootNeighborhood || s.hideRootLinks)
  const root = useGraphControls((s) => s.neighborhoodRoot)
  const setRoot = useGraphControls((s) => s.setNeighborhoodRoot)
  const isRoot = root?.graphId === graphId && root?.nodeId === node.id

  if (!enabled) return null

  return (
    <div className="px-6 pb-4 shrink-0">
      <Button
        variant="outline"
        size="sm"
        className="w-full justify-start gap-2"
        disabled={isRoot}
        onClick={() => setRoot({ graphId, nodeId: node.id })}
      >
        <Pin className="size-3.5 shrink-0" />
        {isRoot ? t('Filter root pinned') : t('Make filter root')}
      </Button>
      <p className="mt-1.5 text-xs text-muted-foreground">
        {isRoot
          ? t('Inspect other nodes without changing this root.')
          : t('Rebuild the filtered graph around this node.')}
      </p>
    </div>
  )
}
