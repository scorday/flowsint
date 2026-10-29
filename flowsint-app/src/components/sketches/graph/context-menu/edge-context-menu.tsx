import { useTranslation } from '@/i18n'
import React, { ChangeEvent, useCallback, useRef } from 'react'
import { Button } from '@/components/ui/button'
import { Trash2, Unlink } from 'lucide-react'
import { GraphEdge } from '@/types'
import BaseContextMenu from '@/components/xyflow/context-menu'
import { CopyButton } from '@/components/copy'
import { sketchService } from '@/api/sketch-service'
import { useParams } from '@tanstack/react-router'
import { useGraphStore } from '@/stores/graph-store'
import { useConfirm } from '@/components/use-confirm-dialog'
import { toast } from 'sonner'
import { Input } from '@/components/ui/input'
import { usePermissions } from '@/hooks/use-can'
import { useQueryClient } from '@tanstack/react-query'
import { useGraphControls } from '@/stores/graph-controls-store'

interface EdgeContextMenuProps {
  edge?: GraphEdge
  edges?: GraphEdge[]
  top?: number
  left?: number
  right?: number
  bottom?: number
  rawTop?: number
  rawLeft?: number
  wrapperWidth: number
  wrapperHeight: number
  setMenu: (menu: any | null) => void
  // For newly created edges: save to DB on submit, remove from store on dismiss
  onSubmitNew?: (edgeId: string, label: string) => void
  onDismissNew?: (edgeId: string) => void
  [key: string]: any
}

export default function EdgeContextMenu({
  edge,
  edges,
  top,
  left,
  right,
  bottom,
  wrapperWidth,
  wrapperHeight,
  setMenu,
  onSubmitNew,
  onDismissNew,
  ...props
}: EdgeContextMenuProps) {
  const { t } = useTranslation()

  const { id: sketchId, investigationId } = useParams({ strict: false })
  const { canEdit, canDelete } = usePermissions()
  const queryClient = useQueryClient()
  const refetchGraph = useGraphControls((s) => s.refetchGraph)
  const removeEdges = useGraphStore((s) => s.removeEdges)
  const updateEdge = useGraphStore((s) => s.updateEdge)
  const clearSelectedEdges = useGraphStore((s) => s.clearSelectedEdges)
  const labelRef = useRef<HTMLInputElement>(null)
  const { confirm } = useConfirm()

  // Determine if multi-select or single
  const isMultiSelect = edges && edges.length > 0
  const edgesToDelete = isMultiSelect ? edges : edge ? [edge] : []
  const edgeIds = edgesToDelete.map((e) => e.id)

  const handleInputChange = useCallback((e: ChangeEvent<HTMLInputElement>) => {
    e.stopPropagation()
  }, [])

  const savedRef = useRef(false)

  const handleBlur = useCallback(async () => {
    if (!edge || !labelRef.current?.value || !sketchId) return
    const newLabel = labelRef.current.value.trim()

    // New edge: always save on blur (triggered by Enter)
    if (onSubmitNew) {
      savedRef.current = true
      updateEdge(edge.id, { label: newLabel })
      setMenu(null)
      onSubmitNew(edge.id, newLabel)
      return
    }

    if (newLabel !== edge.label) {
      const previousLabel = edge.label

      // Optimistic update
      updateEdge(edge.id, { label: newLabel })
      setMenu(null)

      // Call API
      try {
        await sketchService.updateEdge(
          sketchId,
          JSON.stringify({
            relationshipId: edge.id,
            data: { label: newLabel }
          })
        )
        await queryClient.invalidateQueries({ queryKey: ['investigations', investigationId] })
        await refetchGraph()
        toast.success(t('Relationship updated successfully.'))
      } catch {
        // Rollback on error
        updateEdge(edge.id, { label: previousLabel })
        toast.error(t('Failed to update relationship.'))
      }
    }
  }, [
    edge,
    updateEdge,
    sketchId,
    setMenu,
    onSubmitNew,
    t,
    queryClient,
    investigationId,
    refetchGraph
  ])

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      labelRef.current?.blur()
    }
  }, [])

  const handleDelete = useCallback(
    async (e: React.MouseEvent, fromInvestigation = false) => {
      e.stopPropagation()
      if (edgeIds.length === 0 || !sketchId) return
      const count = edgeIds.length
      if (onSubmitNew && onDismissNew && edge) {
        onDismissNew(edge.id)
        setMenu(null)
        return
      }
      if (
        !(await confirm({
          title: fromInvestigation
            ? t('Delete relations from investigation?')
            : t('Remove {{v0}} relation{{v1}} from this sketch?', {
                v0: count,
                v1: count > 1 ? 's' : ''
              }),
          message: fromInvestigation
            ? t(
                'The selected relations will disappear from every sketch in this investigation. The objects will remain.'
              )
            : t('The relations remain in the investigation and on other sketches.')
        }))
      ) {
        return
      }
      setMenu(null)
      toast.promise(
        (async () => {
          if (fromInvestigation) await sketchService.deleteFromInvestigation(sketchId, [], edgeIds)
          else
            await sketchService.deleteEdges(sketchId, JSON.stringify({ relationshipIds: edgeIds }))
          removeEdges(edgeIds)
          if (isMultiSelect) clearSelectedEdges()
          await queryClient.invalidateQueries({ queryKey: ['investigations', investigationId] })
          await refetchGraph()
        })(),
        {
          loading: t('Deleting {{v0}} relationship{{v1}}...', {
            v0: count,
            v1: count > 1 ? 's' : ''
          }),
          success: fromInvestigation ? t('Deleted from investigation.') : t('Removed from sketch.'),
          error: t('Failed to delete relationship.')
        }
      )
    },
    [
      edgeIds,
      sketchId,
      setMenu,
      removeEdges,
      clearSelectedEdges,
      isMultiSelect,
      confirm,
      t,
      queryClient,
      investigationId,
      refetchGraph,
      onSubmitNew,
      onDismissNew,
      edge
    ]
  )

  // Wrap setMenu to handle dismissing new edges (Escape / click outside)
  const wrappedSetMenu = useCallback(
    (menu: any | null) => {
      if (menu === null && onDismissNew && edge && !savedRef.current) {
        onDismissNew(edge.id)
      }
      setMenu(menu)
    },
    [setMenu, onDismissNew, edge]
  )

  return (
    <BaseContextMenu
      top={top}
      left={left}
      right={right}
      bottom={bottom}
      wrapperWidth={wrapperWidth}
      wrapperHeight={wrapperHeight}
      setMenu={wrappedSetMenu}
      {...props}
    >
      <div className="px-3 py-1 flex items-center justify-between shrink-0">
        <div className="flex text-xs items-center gap-1 truncate">
          {isMultiSelect ? (
            <span className="block truncate">
              {edgeIds.length} {t(' relationships selected')}
            </span>
          ) : (
            <div className="p-1">
              <Input
                ref={labelRef}
                className="h-7"
                defaultValue={edge?.label ?? '??'}
                onChange={handleInputChange}
                onFocus={(e) => {
                  e.stopPropagation()
                  if (onSubmitNew) e.currentTarget.select()
                }}
                onBlur={canEdit ? handleBlur : undefined}
                onKeyDown={canEdit ? handleKeyDown : undefined}
                readOnly={!canEdit}
                autoFocus
              />
            </div>
          )}
        </div>
        <div className="p-1 flex gap-1">
          {!isMultiSelect && edge && (
            <CopyButton size="icon" content={edge.label} className="h-7 w-7" />
          )}
          {canDelete && !onSubmitNew && (
            <Button
              onClick={(event) => handleDelete(event, true)}
              size="icon"
              variant="ghost"
              className="h-7 w-7 text-destructive"
              aria-label={t('Delete from investigation')}
              title={t('Delete from investigation')}
            >
              <Trash2 className="h-3.5! w-3.5!" />
            </Button>
          )}
          {canEdit && (
            <Button
              onClick={(event) => handleDelete(event)}
              size="icon"
              variant="ghost"
              className="h-7 w-7"
              aria-label={t('Remove from sketch')}
              title={t('Remove from sketch')}
            >
              <Unlink className="h-3.5! w-3.5! opacity-50" />
            </Button>
          )}
        </div>
      </div>
    </BaseContextMenu>
  )
}
