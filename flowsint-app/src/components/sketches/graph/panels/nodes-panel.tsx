import { useTranslation } from '@/i18n'
import type React from 'react'
import { memo, useMemo, useState, useCallback, useRef } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useGraphStore } from '@/stores/graph-store'
import { useGraphControls } from '@/stores/graph-controls-store'
import { useGraphSettingsStore } from '@/stores/graph-settings-store'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { TypeBadge } from '@/components/type-badge'
import { Search, FunnelPlus, XIcon, ChevronDown, ChevronRight, Star } from 'lucide-react'
import { usePromoteNode } from '@/components/sketches/use-promote-node'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'
import { GraphNode } from '@/types'
import { Checkbox } from '@/components/ui/checkbox'
import { usePermissions } from '@/hooks/use-can'

const ITEM_HEIGHT = 40
type Role = 'primary' | 'secondary'
type PanelRow =
  | { kind: 'section'; role: Role; count: number; total: number }
  | { kind: 'node'; node: GraphNode }

function PromoteButton({ nodeId }: { nodeId: string }) {
  const { t } = useTranslation()
  const { promote, pending } = usePromoteNode(nodeId)
  return (
    <Button
      variant="ghost"
      size="icon"
      className="h-7 w-7 shrink-0 mr-1"
      title={t('Make primary')}
      aria-label={t('Make primary')}
      disabled={pending}
      onClick={() => void promote()}
    >
      <Star className="h-3.5 w-3.5" />
    </Button>
  )
}
// Mémoiser le composant NodeRenderer
const NodeRenderer = memo(
  ({
    node,
    setCurrentNodeId,
    onCheckboxChange,
    isNodeChecked,
    isCurrent,
    centerOnNode,
    autoZoomOnCurrentNode,
    canEdit
  }: {
    node: GraphNode
    setCurrentNodeId: (nodeId: string | null) => void
    onCheckboxChange: (node: GraphNode, checked: boolean) => void
    isNodeChecked: (nodeId: string) => boolean
    isCurrent: (nodeId: string) => boolean
    centerOnNode: (x: number, y: number) => void
    autoZoomOnCurrentNode: boolean
    canEdit: boolean
  }) => {
    const handleClick = useCallback(() => {
      setCurrentNodeId(node.id)
      // Auto-zoom if enabled and node has coordinates
      if (autoZoomOnCurrentNode && node?.x !== undefined && node?.y !== undefined) {
        setTimeout(() => {
          centerOnNode(node.x, node.y)
        }, 200)
      }
    }, [node, setCurrentNodeId, centerOnNode, autoZoomOnCurrentNode])

    const handleCheckboxChange = useCallback(
      (checked: boolean) => {
        onCheckboxChange(node, checked)
      },
      [node, onCheckboxChange]
    )

    return (
      <div
        className={cn(
          'flex items-center overflow-hidden hover:bg-muted/50 border-b h-full',
          isCurrent(node.id) && 'bg-muted/70'
        )}
      >
        {canEdit && (
          <div className="pl-2">
            <Checkbox
              checked={isNodeChecked(node.id)}
              onCheckedChange={handleCheckboxChange}
              className="mr-1 border-border"
            />
          </div>
        )}
        <button
          className={cn(
            'flex-1 flex truncate mt-0 text-sm font-medium overflow-hidden duration-0 items-center justify-start p-4 !py-5 rounded-none text-left h-full'
          )}
          onClick={handleClick}
        >
          <div className="grow truncate text-ellipsis">{node?.nodeLabel}</div>
          <TypeBadge className="ml-1" type={node?.nodeType} />
        </button>
        {canEdit && node.nodeRole === 'secondary' && <PromoteButton nodeId={node.id} />}
      </div>
    )
  }
)

// Composant pour un item virtualisé
const VirtualizedItem = memo(
  ({
    node,
    setCurrentNodeId,
    onCheckboxChange,
    isNodeChecked,
    isCurrent,
    centerOnNode,
    autoZoomOnCurrentNode,
    canEdit
  }: {
    index: number
    node: GraphNode
    setCurrentNodeId: (nodeId: string | null) => void
    onCheckboxChange: (node: GraphNode, checked: boolean) => void
    isNodeChecked: (nodeId: string) => boolean
    isCurrent: (nodeId: string) => boolean
    centerOnNode: (x: number, y: number) => void
    autoZoomOnCurrentNode: boolean
    canEdit: boolean
  }) => {
    return (
      <NodeRenderer
        node={node}
        isCurrent={isCurrent}
        setCurrentNodeId={setCurrentNodeId}
        onCheckboxChange={onCheckboxChange}
        isNodeChecked={isNodeChecked}
        centerOnNode={centerOnNode}
        autoZoomOnCurrentNode={autoZoomOnCurrentNode}
        canEdit={canEdit}
      />
    )
  }
)

const NodesPanel = memo(({ nodes, isLoading }: { nodes: GraphNode[]; isLoading?: boolean }) => {
  const { t } = useTranslation()

  const { canEdit } = usePermissions()
  const currentNodeId = useGraphStore((state) => state.currentNodeId)
  const setCurrentNodeId = useGraphStore((state) => state.setCurrentNodeId)
  const setSelectedNodes = useGraphStore((state) => state.setSelectedNodes)
  const selectedNodes = useGraphStore((state) => state.selectedNodes || [])
  const centerOnNode = useGraphControls((state) => state.centerOnNode)
  // getSettingValue returns number | boolean | undefined (generic getter
  // over any category/key pair) — this setting is always boolean-valued.
  const autoZoomOnCurrentNode = useGraphSettingsStore((s) =>
    Boolean(s.getSettingValue('general', 'autoZoomOnCurrentNode'))
  )
  const [searchQuery, setSearchQuery] = useState<string>('')
  const [filters, setFilters] = useState<string[] | null>(null)
  const [collapsed, setCollapsed] = useState<Record<Role, boolean>>({
    primary: false,
    secondary: false
  })

  const types = useMemo(() => Array.from(new Set(nodes.map((n) => n.nodeType))), [nodes])

  // Ref pour le conteneur parent du virtualizer
  const parentRef = useRef<HTMLDivElement>(null)

  const filteredNodes = useMemo(() => {
    const searchText = searchQuery.toLowerCase()
    return nodes
      ?.filter((node) => {
        const matchesSearch =
          node?.nodeLabel?.toLowerCase().includes(searchText) ||
          node?.id?.toLowerCase().includes(searchText)

        const matchesFilter =
          !filters ||
          filters.some(
            (filter) => filter.toLowerCase() === (node.nodeType as string)?.toLowerCase()
          )

        return matchesSearch && matchesFilter
      })
      .sort((a, b) => a.nodeType.localeCompare(b.nodeType))
  }, [nodes, searchQuery, filters])

  const rows = useMemo<PanelRow[]>(() => {
    const result: PanelRow[] = []
    for (const role of ['primary', 'secondary'] as const) {
      const matchesRole = (node: GraphNode) =>
        (node.nodeRole === 'secondary' ? 'secondary' : 'primary') === role
      const group = filteredNodes.filter(matchesRole)
      result.push({
        kind: 'section',
        role,
        count: group.length,
        total: nodes.filter(matchesRole).length
      })
      if (!collapsed[role]) result.push(...group.map((node) => ({ kind: 'node' as const, node })))
    }
    return result
  }, [nodes, filteredNodes, collapsed])

  // Keep one virtualized scroll container even for large enrichment results.
  const virtualizer = useVirtualizer({
    count: rows.length,
    getItemKey: (index) => {
      const row = rows[index]
      return row.kind === 'section' ? row.role : row.node.id
    },
    getScrollElement: () => parentRef.current,
    estimateSize: () => ITEM_HEIGHT,
    overscan: 5 // Nombre d'éléments à pré-rendre en dehors de la zone visible
  })

  const toggleFilter = useCallback(
    (filter: string | null) => {
      if (filter === null) {
        setFilters(null)
      } else {
        const currentFilters = filters || []
        const isChecked = currentFilters.includes(filter)
        const newFilters = isChecked
          ? currentFilters.filter((f) => f !== filter)
          : [...currentFilters, filter.toLowerCase()]
        setFilters(newFilters.length === 0 ? null : newFilters)
      }
    },
    [filters, setFilters]
  )

  const handleSearchChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setSearchQuery(e.target.value)
  }, [])

  const clearFilters = useCallback(() => {
    setFilters(null)
  }, [])

  const isNodeChecked = useCallback(
    (nodeId: string) => {
      return selectedNodes.some((node) => node.id === nodeId)
    },
    [selectedNodes]
  )

  const isCurrent = useCallback(
    (nodeId: string) => {
      return currentNodeId === nodeId
    },
    [currentNodeId]
  )

  const handleCheckAll = useCallback(
    (checked: boolean) => {
      if (!checked) {
        setSelectedNodes([])
        return
      }
      if (filters?.length || searchQuery) {
        setSelectedNodes(filteredNodes)
      } else setSelectedNodes(nodes)
    },
    [nodes, filteredNodes, filters, searchQuery, setSelectedNodes]
  )

  const handleCheckboxChange = useCallback(
    (node: GraphNode, checked: boolean) => {
      if (checked) {
        setSelectedNodes([...selectedNodes.filter((n) => n.id !== node.id), node])
      } else {
        setSelectedNodes(selectedNodes.filter((n) => n.id !== node.id))
      }
    },
    [selectedNodes, setSelectedNodes]
  )

  return (
    <div className="overflow-hidden bg-card h-full flex flex-col w-full !p-0 !m-0">
      {/* Header fixe */}
      <div className="sticky border-b top-0 p-2 bg-card z-10 shrink-0">
        <div className="flex items-center gap-2">
          {canEdit && (
            <div>
              <Checkbox onCheckedChange={handleCheckAll} className="mr-1" />
            </div>
          )}
          <Badge className="h-7" variant={'outline'}>
            <span className="font-semibold">
              {filters?.length || searchQuery
                ? `${filteredNodes?.length} / ${nodes?.length || 0}`
                : nodes?.length || 0}
            </span>{' '}
            <span className="font-normal opacity-60">{t('nodes')}</span>
          </Badge>
          <div className="relative grow">
            <Search className="absolute left-2.5 top-1.5 h-4 w-4 text-muted-foreground" />
            <Input
              type="search"
              placeholder={t('Search...')}
              className="pl-8 h-7 border-border"
              value={searchQuery}
              onChange={handleSearchChange}
            />
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                aria-label={t('Filter by type')}
                variant={'outline'}
                className="h-7 w-8 relative border-border border"
                size={'icon'}
              >
                <FunnelPlus className={cn('opacity-60 h-3 w-3', filters && 'opacity-100')} />
                {filters && (
                  <Badge
                    className="absolute -top-2 -right-1 text-xs rounded-full h-4 w-4 text-white"
                    variant={'default'}
                  >
                    {filters.length}
                  </Badge>
                )}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent className="w-48 max-h-[50vh] space-y-1 overflow-y-auto">
              <DropdownMenuLabel>
                {filters ? (
                  <Badge variant={'outline'} className="flex items-center gap-1 pr-1">
                    {filters?.length} {t(' filter(s)')}
                    <Button
                      size={'icon'}
                      variant={'ghost'}
                      className="h-5 w-5 rounded-full"
                      onClick={clearFilters}
                    >
                      <XIcon className="h-3 w-3" />
                    </Button>
                  </Badge>
                ) : (
                  'filters'
                )}
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className={cn(filters == null && 'bg-primary')}
                onClick={() => toggleFilter(null)}
              >
                {t('All')}
              </DropdownMenuItem>
              {types.map((type: string) => (
                <DropdownMenuItem
                  className={cn(filters?.includes(type) && 'bg-primary/30')}
                  key={type}
                  onClick={() => toggleFilter(type)}
                >
                  {type || 'unknown'}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Contenu principal */}
      <div className="flex-1 min-h-0 flex flex-col">
        {!isLoading && nodes.length === 0 && searchQuery === '' && (
          <div className="text-sm p-4 text-center">
            <p className="border rounded-md border-dashed p-4 text-center">
              {t('Drag and drop you first node in the "items" section.')}
            </p>
          </div>
        )}
        {/* {isLoading || !filteredNodes?.length && (
                    <div className="p-2"><SkeletonList rowCount={7} /></div>
                )} */}

        {filteredNodes?.length === 0 && (searchQuery || filters?.length) && (
          <div className="p-4 text-center text-muted-foreground">
            {t('No nodes match your search')}
          </div>
        )}

        {/* Liste virtualisée */}
        {!isLoading && (
          <div
            ref={parentRef}
            className="flex-1 min-h-0 overflow-auto"
            style={{
              contain: 'strict'
            }}
          >
            <div
              style={{
                height: `${virtualizer.getTotalSize()}px`,
                width: '100%',
                position: 'relative'
              }}
            >
              {virtualizer.getVirtualItems().map((virtualItem) => {
                const row = rows[virtualItem.index]
                return (
                  <div
                    key={virtualItem.key}
                    style={{
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      width: '100%',
                      height: `${virtualItem.size}px`,
                      transform: `translateY(${virtualItem.start}px)`
                    }}
                  >
                    {row.kind === 'section' ? (
                      <button
                        className="flex items-center gap-2 px-3 h-full w-full border-b bg-muted/40 text-sm font-medium text-left"
                        aria-expanded={!collapsed[row.role]}
                        onClick={() =>
                          setCollapsed((value) => ({ ...value, [row.role]: !value[row.role] }))
                        }
                      >
                        {collapsed[row.role] ? (
                          <ChevronRight className="h-4 w-4" />
                        ) : (
                          <ChevronDown className="h-4 w-4" />
                        )}
                        <span className="grow">
                          {t(row.role === 'primary' ? 'Primary objects' : 'Secondary objects')}
                        </span>{' '}
                        <Badge variant="outline">
                          {row.count === row.total ? row.total : `${row.count} / ${row.total}`}
                        </Badge>
                      </button>
                    ) : (
                      <VirtualizedItem
                        index={virtualItem.index}
                        node={row.node}
                        isCurrent={isCurrent}
                        setCurrentNodeId={setCurrentNodeId}
                        onCheckboxChange={handleCheckboxChange}
                        isNodeChecked={isNodeChecked}
                        centerOnNode={centerOnNode}
                        autoZoomOnCurrentNode={autoZoomOnCurrentNode}
                        canEdit={canEdit}
                      />
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  )
})

export default NodesPanel
