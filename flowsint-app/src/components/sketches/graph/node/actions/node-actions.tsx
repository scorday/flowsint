import { useTranslation } from '@/i18n'
import React, { memo, useCallback, useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Trash2, Sparkles, Plus, MoreHorizontal, Flag, Star } from 'lucide-react'
import { usePromoteNode } from '@/components/sketches/use-promote-node'
import { useGraphStore } from '@/stores/graph-store'
import { useParams } from '@tanstack/react-router'
import { useConfirm } from '@/components/use-confirm-dialog'
import { toast } from 'sonner'
import { sketchService } from '@/api/sketch-service'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'
import { useLayoutStore } from '@/stores/layout-store'
import { GraphNode } from '@/types'
import { useGraphSettingsStore } from '@/stores/graph-settings-store'
import { cn } from '@/lib/utils'
import { usePermissions } from '@/hooks/use-can'
import { useQueryClient } from '@tanstack/react-query'

const flagColors = {
  red: 'text-red-400 fill-red-200',
  orange: 'text-orange-400 fill-orange-200',
  blue: 'text-blue-400 fill-blue-200',
  green: 'text-green-400 fill-green-200',
  yellow: 'text-yellow-400 fill-yellow-200'
} as const

type FlagColor = keyof typeof flagColors

const NodeActions = memo(
  ({ node, setMenu }: { node: GraphNode; setMenu?: (menu: any | null) => void }) => {
    const { t } = useTranslation()
    const { promote, pending: promoting } = usePromoteNode(node.id)

    const { id: sketchId, investigationId } = useParams({ strict: false })
    const { canEdit, canDelete } = usePermissions()
    const queryClient = useQueryClient()
    const { confirm } = useConfirm()
    const setOpenMainDialog = useGraphStore((state) => state.setOpenMainDialog)
    const setRelatedNodeToAdd = useGraphStore((state) => state.setRelatedNodeToAdd)
    const removeNodes = useGraphStore((s) => s.removeNodes)
    const toggleNodeSelection = useGraphStore((s) => s.toggleNodeSelection)
    const updateNode = useGraphStore((s) => s.updateNode)
    const openChat = useLayoutStore((s) => s.openChat)
    const settings = useGraphSettingsStore((s) => s.settings)

    const [flagValue, setFlagValue] = useState<FlagColor | null>(node.nodeFlag)

    useEffect(() => {
      setFlagValue(node.nodeFlag)
    }, [node.id, node.nodeFlag])

    const handleOpenMainDialog = useCallback(() => {
      setRelatedNodeToAdd(node)
      setOpenMainDialog(true)
      setMenu?.(null)
    }, [setOpenMainDialog, setMenu, node, setRelatedNodeToAdd])

    const handleAskAI = useCallback(
      (e: React.MouseEvent) => {
        e.stopPropagation()
        toggleNodeSelection(node, false)
        openChat()
        setMenu?.(null)
      },
      [node, toggleNodeSelection, openChat, setMenu]
    )

    const handleDeleteNode = async (global: boolean) => {
      if (!node.id || !sketchId) return
      if (
        !(await confirm({
          title: global ? t('Delete from investigation?') : t('Remove from sketch?'),
          message: global
            ? t(
                'The object and its relations will disappear from every sketch in this investigation.'
              )
            : t('The object remains in the investigation and on other sketches.')
        }))
      )
        return
      toast.promise(
        (async () => {
          if (global) await sketchService.deleteFromInvestigation(sketchId, [node.id], [])
          else await sketchService.deleteNodes(sketchId, JSON.stringify({ nodeIds: [node.id] }))
          removeNodes([node.id])
          await queryClient.invalidateQueries({ queryKey: ['investigations', investigationId] })
        })(),
        {
          loading: t('Deleting {{v0}}...', { v0: String(node.nodeProperties.label) }),
          success: global ? t('Deleted from investigation.') : t('Removed from sketch.'),
          error: t('Failed to delete node.')
        }
      )
    }

    const handleUpdateFlag = useCallback(
      async (value: FlagColor) => {
        const val = value === flagValue ? null : value
        setFlagValue(val)
        try {
          updateNode(node.id, { nodeFlag: val })
          const body = JSON.stringify({
            nodeId: node.id,
            updates: { nodeFlag: val } as Partial<GraphNode>
          })
          await sketchService.updateNode(sketchId!, body)
        } catch (e) {
          console.log(e)
        }
      },
      [node, flagValue, updateNode, sketchId]
    )

    if (!canEdit) return null

    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" className="h-6 w-6">
            <MoreHorizontal className="h-3.5 w-3.5" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="min-w-[140px]">
          {node.nodeRole === 'secondary' && (
            <DropdownMenuItem disabled={promoting} onClick={() => void promote()}>
              <Star className="h-3.5 w-3.5 mr-2" />
              {t('Make primary')}
            </DropdownMenuItem>
          )}
          <DropdownMenuItem onClick={handleOpenMainDialog}>
            <Plus className="h-3.5 w-3.5 mr-2" />
            {t('Add relation')}
          </DropdownMenuItem>
          {Boolean(settings?.general?.showFlow?.value) && (
            <DropdownMenuItem onClick={handleAskAI}>
              <Sparkles className="h-3.5 w-3.5 mr-2" />
              {t('Ask AI')}
            </DropdownMenuItem>
          )}
          <DropdownMenuSub>
            <DropdownMenuSubTrigger>
              <Flag className={cn('h-3.5 w-3.5 mr-2', flagValue ? flagColors[flagValue] : '')} />
              {t('Flag')}
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              <div className="flex gap-1 p-1">
                {(Object.keys(flagColors) as FlagColor[]).map((key) => (
                  <button
                    key={key}
                    onClick={(e) => {
                      e.stopPropagation()
                      handleUpdateFlag(key)
                    }}
                    className={cn(
                      'w-7 h-7 flex items-center justify-center rounded hover:bg-muted',
                      flagValue === key && 'bg-muted'
                    )}
                  >
                    <Flag className={cn('h-4 w-4', flagColors[key])} />
                  </button>
                ))}
              </div>
            </DropdownMenuSubContent>
          </DropdownMenuSub>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onClick={() => handleDeleteNode(false)}
            className="text-destructive focus:text-destructive"
          >
            <Trash2 className="h-3.5 w-3.5 mr-2" />
            {t('Remove from sketch')}
          </DropdownMenuItem>
          {canDelete && (
            <DropdownMenuItem
              onClick={() => handleDeleteNode(true)}
              className="text-destructive focus:text-destructive"
            >
              <Trash2 className="h-3.5 w-3.5 mr-2" />
              {t('Delete from investigation')}
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    )
  }
)

export default NodeActions
