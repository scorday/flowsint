import { useTranslation } from '@/i18n'
import { sketchService } from '@/api/sketch-service'
import Loader from '@/components/loader'
import { TypeBadge } from '@/components/type-badge'
import { useGraphStore } from '@/stores/graph-store'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, ArrowRight, Repeat2 } from 'lucide-react'
import { memo, useCallback, useMemo, useRef } from 'react'
import type { GraphEdge, GraphNode } from '@/types'
import { useVirtualizer } from '@tanstack/react-virtual'

const ITEM_HEIGHT = 36

type Relation = {
  id: string
  neighbor: GraphNode
  direction: 'incoming' | 'outgoing' | 'self'
  label: string
}

const endpointId = (endpoint: string | { id: string }) =>
  typeof endpoint === 'object' ? endpoint.id : endpoint

const getInlineRelationships = (
  nodes: GraphNode[],
  edges: GraphEdge[],
  nodeId: string
): Relation[] => {
  const nodesById = new Map(nodes.map((node) => [node.id, node]))
  const relationships: Relation[] = []
  edges.forEach((edge) => {
    const sourceId = endpointId(edge.source)
    const targetId = endpointId(edge.target)
    if (sourceId !== nodeId && targetId !== nodeId) return
    const neighbor = nodesById.get(sourceId === nodeId ? targetId : sourceId)
    if (!neighbor) return
    relationships.push({
      id: edge.id,
      neighbor,
      direction: sourceId === targetId ? 'self' : sourceId === nodeId ? 'outgoing' : 'incoming',
      label: String(edge.caption || edge.label || 'RELATED_TO')
    })
  })
  return relationships
}

const Relationships = memo(
  ({ sketchId, nodeId, nodeLength }: { sketchId: string; nodeId: string; nodeLength: number }) => {
    const { t } = useTranslation()

    const {
      data: neighborsData,
      isLoading,
      error
    } = useQuery({
      queryKey: ['neighbors', sketchId, nodeId, nodeLength],
      queryFn: () => sketchService.getNodeNeighbors(sketchId, nodeId)
    })

    const relationships = useMemo(
      () => getInlineRelationships(neighborsData?.nds || [], neighborsData?.rls || [], nodeId),
      [neighborsData, nodeId]
    )

    if (isLoading) {
      return (
        <div className="flex items-center justify-center h-full">
          <Loader />
        </div>
      )
    }

    if (error) {
      return (
        <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
          {t('Could not load relationships.')}
        </div>
      )
    }

    if (relationships.length === 0) {
      return (
        <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
          {t('No relationships found')}
        </div>
      )
    }

    return <VirtualizedList relationships={relationships} />
  }
)

const VirtualizedList = memo(({ relationships }: { relationships: Relation[] }) => {
  const { t } = useTranslation()
  const parentRef = useRef<HTMLDivElement>(null)
  const getItemKey = useCallback((index: number) => relationships[index].id, [relationships])

  const virtualizer = useVirtualizer({
    count: relationships.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ITEM_HEIGHT,
    getItemKey,
    overscan: 5
  })

  const virtualItems = virtualizer.getVirtualItems()

  const totalSize = virtualizer.getTotalSize()

  return (
    <div ref={parentRef} className="h-full overflow-auto" role="list" aria-label={t('Relations')}>
      <div
        style={{
          height: `${totalSize}px`,
          width: '100%',
          position: 'relative'
        }}
      >
        {virtualItems.map((virtualRow) => {
          const rel = relationships[virtualRow.index]
          const DirectionIcon =
            rel.direction === 'incoming'
              ? ArrowLeft
              : rel.direction === 'self'
                ? Repeat2
                : ArrowRight
          const directionLabel = t(
            rel.direction === 'incoming'
              ? 'Incoming relationship'
              : rel.direction === 'self'
                ? 'Self relationship'
                : 'Outgoing relationship'
          )

          return (
            <div
              key={virtualRow.key}
              role="listitem"
              aria-posinset={virtualRow.index + 1}
              aria-setsize={relationships.length}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                height: `${virtualRow.size}px`,
                transform: `translateY(${virtualRow.start}px)`
              }}
              className="pb-1 px-1"
            >
              <div className="flex h-8 w-full min-w-0 items-center gap-2 rounded-md border px-2 py-1">
                <span
                  title={directionLabel}
                  role="img"
                  aria-label={directionLabel}
                  className="shrink-0 text-muted-foreground"
                >
                  <DirectionIcon className="h-4 w-4" aria-hidden="true" />
                </span>
                <RelationshipItem node={rel.neighbor} isSelf={rel.direction === 'self'} />
                <span
                  className="max-w-[35%] truncate text-xs text-muted-foreground"
                  title={rel.label}
                >
                  {rel.label}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
})

export default Relationships

const RelationshipItem = memo(({ node, isSelf }: { node: GraphNode; isSelf: boolean }) => {
  const { t } = useTranslation()
  const label = isSelf ? t('This node') : node.nodeLabel || node.id
  const setCurrentNodeId = useGraphStore((s) => s.setCurrentNodeId)
  const handleClick = useCallback(() => {
    setCurrentNodeId(node.id)
  }, [setCurrentNodeId, node.id])
  return (
    <button
      className="min-w-0 flex-1 h-full text-left hover:underline cursor-pointer flex items-center rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      title={node.nodeLabel || node.id}
      aria-label={label}
      onClick={handleClick}
    >
      <TypeBadge className="w-full truncate block text-left" type={node.nodeType}>
        {label}
      </TypeBadge>
    </button>
  )
})
