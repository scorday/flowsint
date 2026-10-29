import { useLayoutEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useParams } from '@tanstack/react-router'
import { toast } from 'sonner'
import { sketchService, type NodeMatch } from '@/api/sketch-service'
import type { GraphNode } from '@/types'
import { useGraphStore } from '@/stores/graph-store'
import { useGraphControls } from '@/stores/graph-controls-store'
import { useTranslation } from '@/i18n'

type AddOptions = {
  relatedSourceId?: string
  onAdded?: (id: string) => void
  onCancel?: () => void
}
type Pending = {
  sketchId: string
  investigationId?: string
  node: GraphNode
  options: AddOptions
  matches: NodeMatch[]
  checked: boolean
}

// All manual entry points check before writing or adding a temporary canvas node.
export function useManualNodeAdd(sketchId?: string) {
  const { t } = useTranslation()
  const { investigationId } = useParams({ strict: false })
  const queryClient = useQueryClient()
  const [pending, setPending] = useState<Pending | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const locked = useRef(false)
  const currentSketch = useRef(sketchId)
  useLayoutEffect(() => {
    currentSketch.current = sketchId
    return () => {
      currentSketch.current = undefined
    }
  }, [sketchId])

  async function save(request: Pending, existing?: NodeMatch) {
    const { sketchId } = request
    let id: string
    if (existing) {
      // Reuse shared attributes and layout; explicit manual reuse makes it primary.
      if (!existing.on_sketch) {
        await sketchService.attachSubgraph(sketchId, [existing.node.id], [])
      } else if (existing.node.nodeRole === 'secondary') {
        await sketchService.updateNode(
          sketchId,
          JSON.stringify({ nodeId: existing.node.id, updates: { nodeRole: 'primary' } })
        )
      }
      id = existing.node.id
    } else {
      const response = await sketchService.addNode(sketchId, JSON.stringify(request.node))
      id = response.node.id
    }
    if (request.options.relatedSourceId && request.options.relatedSourceId !== id) {
      try {
        await sketchService.addEdge(
          sketchId,
          JSON.stringify({
            source: request.options.relatedSourceId,
            target: id,
            type: 'one-way',
            label: `HAS_${request.node.nodeType.toUpperCase()}`
          })
        )
      } catch {
        toast.error(t('Object saved, but the relation could not be added. Add it from the sketch.'))
      }
    }
    // A concurrent create can return an existing canonical ID. Reload instead of
    // replacing a temporary ID, which could leave two canvas nodes with that ID.
    setPending(null)
    try {
      await queryClient.invalidateQueries({ queryKey: ['investigations', request.investigationId] })
      if (currentSketch.current !== sketchId) return
      await useGraphControls.getState().refetchGraph(() => {
        if (currentSketch.current === sketchId) useGraphStore.getState().setCurrentNodeId(id)
      })
    } catch {
      toast.error(t('Object saved. Refresh the sketch to see the latest graph.'))
    }
    if (currentSketch.current === sketchId) {
      useGraphStore.getState().setCurrentNodeId(id)
      request.options.onAdded?.(id)
    }
  }

  async function run(action: () => Promise<void>) {
    if (locked.current) return
    locked.current = true
    setBusy(true)
    setError('')
    try {
      await action()
    } catch {
      setError(t('Could not check or add the object. Retry or return to editing.'))
    } finally {
      locked.current = false
      setBusy(false)
    }
  }

  async function check(request: Pending) {
    setPending(request)
    const matches = await sketchService.findNodeMatches(request.sketchId, request.node)
    if (currentSketch.current !== request.sketchId) return
    const checked = { ...request, matches, checked: true }
    setPending(checked)
    if (!matches.length) await save(checked)
  }

  return {
    pending: pending?.sketchId === sketchId ? pending : null,
    busy,
    error,
    add: (node: GraphNode, options: AddOptions = {}) =>
      sketchId &&
      run(() => check({ sketchId, investigationId, node, options, matches: [], checked: false })),
    retry: () => pending && run(() => (pending.checked ? save(pending) : check(pending))),
    reuse: (match: NodeMatch) => pending && run(() => save(pending, match)),
    createSeparate: () =>
      pending?.checked &&
      !pending.matches.some((m) => m.match === 'exact') &&
      run(() => save(pending)),
    cancel: () => {
      if (locked.current) return
      pending?.options.onCancel?.()
      setPending(null)
      setError('')
    }
  }
}

export type ManualNodeAdd = ReturnType<typeof useManualNodeAdd>
