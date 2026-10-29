import { useLayoutEffect, useRef, useState } from 'react'
import { useParams } from '@tanstack/react-router'
import { toast } from 'sonner'
import { sketchService } from '@/api/sketch-service'
import { useGraphStore } from '@/stores/graph-store'
import { useTranslation } from '@/i18n'

export function usePromoteNode(nodeId: string) {
  const { id: sketchId } = useParams({ strict: false })
  const { t } = useTranslation()
  const [pending, setPending] = useState(false)
  const currentSketch = useRef(sketchId)
  useLayoutEffect(() => {
    currentSketch.current = sketchId
    return () => {
      currentSketch.current = undefined
    }
  }, [sketchId])

  async function promote() {
    if (!sketchId || pending) return
    setPending(true)
    try {
      await sketchService.updateNode(
        sketchId,
        JSON.stringify({ nodeId, updates: { nodeRole: 'primary' } })
      )
      // A response from a previously open sketch must not change the new view.
      if (currentSketch.current === sketchId) {
        useGraphStore.getState().updateNode(nodeId, { nodeRole: 'primary' })
      }
    } catch {
      toast.error(t('Could not make the object primary.'))
    } finally {
      setPending(false)
    }
  }

  return { promote, pending }
}
