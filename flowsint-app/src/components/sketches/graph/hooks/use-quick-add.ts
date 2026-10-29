import { useCallback, useEffect, useRef, useState } from 'react'
import { sketchService } from '@/api/sketch-service'
import { type GraphNode, type NodeProperties } from '@/types/graph'
import { type DetectionResult } from '@/types/sketch'
import { useDebounce } from '@/hooks/use-debounce'
import { v4 as uuidv4 } from 'uuid'
import { toast } from 'sonner'
import { useTranslation } from '@/i18n'
import { useManualNodeAdd } from '../../use-manual-node-add'

interface QuickAddState {
  active: boolean
  position: { x: number; y: number } | null // screen coords
  graphPosition: { x: number; y: number } | null // graph coords
  text: string
  detection: DetectionResult | null
  loading: boolean
}

const INITIAL_STATE: QuickAddState = {
  active: false,
  position: null,
  graphPosition: null,
  text: '',
  detection: null,
  loading: false
}

export const useQuickAdd = (sketchId?: string) => {
  const { t } = useTranslation()
  const submitting = useRef(false)
  const [state, setState] = useState<QuickAddState>(INITIAL_STATE)
  const debouncedText = useDebounce(state.text, 300)

  const manualAdd = useManualNodeAdd(sketchId)

  // Reset detection immediately when there's no text or quick-add isn't
  // active — adjusted during render rather than in an effect.
  const shouldDetect = Boolean(debouncedText.trim()) && state.active
  const [prevShouldDetect, setPrevShouldDetect] = useState(shouldDetect)
  if (shouldDetect !== prevShouldDetect) {
    setPrevShouldDetect(shouldDetect)
    if (!shouldDetect) {
      setState((prev) => ({ ...prev, detection: null, loading: false }))
    }
  }

  // Detect type when debounced text changes
  useEffect(() => {
    if (!shouldDetect) return

    let cancelled = false
    // Kicking off a loading flag synchronously at the start of a fetch
    // effect is the standard pattern (see react.dev's own data-fetching
    // examples) — not the "derived state from a prop" case this rule
    // mainly targets.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState((prev) => ({ ...prev, loading: true }))

    sketchService
      .detectType(debouncedText)
      .then((result: DetectionResult) => {
        if (!cancelled) {
          setState((prev) => ({ ...prev, detection: result, loading: false }))
        }
      })
      .catch(() => {
        if (!cancelled) {
          setState((prev) => ({ ...prev, detection: null, loading: false }))
        }
      })

    return () => {
      cancelled = true
    }
  }, [debouncedText, shouldDetect])

  const open = useCallback((screenX: number, screenY: number, graphX: number, graphY: number) => {
    setState({
      active: true,
      position: { x: screenX, y: screenY },
      graphPosition: { x: graphX, y: graphY },
      text: '',
      detection: null,
      loading: false
    })
  }, [])

  const close = useCallback(() => {
    setState(INITIAL_STATE)
  }, [])

  const setText = useCallback((text: string) => {
    setState((prev) => ({ ...prev, text }))
  }, [])

  const submit = useCallback(async () => {
    if (!state.text.trim() || !sketchId || !state.graphPosition || submitting.current) return
    submitting.current = true
    try {
      // Enter may arrive before the debounced preview. Check the actual submitted text.
      const detection = await sketchService.detectType(state.text.trim())
      const nodeType = detection?.type?.toLowerCase() || 'phrase'
      const label = state.text.trim()

      // Build nodeProperties from detection fields
      const nodeProperties: NodeProperties = {}
      if (detection?.fields) {
        for (const field of detection.fields) {
          if (field.primary && field.value) {
            nodeProperties[field.name] = field.value
          }
        }
      }
      // Fallback: if no primary field was set, use 'text' for phrase
      if (Object.keys(nodeProperties).length === 0) {
        nodeProperties['text'] = label
      }

      const tempId = uuidv4()
      const node: GraphNode = {
        id: tempId,
        nodeType,
        nodeLabel: label,
        x: state.graphPosition.x,
        y: state.graphPosition.y,
        nodeSize: 4,
        nodeColor: null,
        nodeShape: 'circle',
        nodeFlag: null,
        nodeIcon: null,
        nodeImage: null,
        nodeProperties,
        nodeMetadata: {}
      }

      const previous = state
      setState(INITIAL_STATE)
      await manualAdd.add(node, { onCancel: () => setState(previous) })
    } catch {
      toast.error(t('Could not detect the object type. Please retry.'))
    } finally {
      submitting.current = false
    }
  }, [state, sketchId, manualAdd, t])

  return {
    quickAdd: state,
    nodeMatch: manualAdd,
    openQuickAdd: open,
    closeQuickAdd: close,
    setQuickAddText: setText,
    submitQuickAdd: submit
  }
}
