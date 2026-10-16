import { useTranslation } from '@/i18n'
import { toast } from 'sonner'
import { useConfirm } from '@/components/use-confirm-dialog'
import { flowService } from '@/api/flow-service'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { queryKeys } from '@/api/query-keys'
import { useLayoutStore } from '@/stores/layout-store'

export function useLaunchFlow(askUser: boolean = false) {
  const { t } = useTranslation()

  const { confirm } = useConfirm()
  const queryClient = useQueryClient()
  const openClonsole = useLayoutStore((s) => s.openConsole)

  // Launch flow mutation
  const launchFlowMutation = useMutation({
    mutationFn: ({ flowId, body }: { flowId: string; body: BodyInit }) =>
      flowService.launch(flowId, body),
    onSuccess: (_, variables) => {
      openClonsole()
      queryClient.invalidateQueries({
        queryKey: queryKeys.flows.detail(variables.flowId)
      })
      queryClient.invalidateQueries({
        queryKey: queryKeys.scans.list
      })
    },
    onError: (error) => {
      console.error('Error launching flow:', error)
    }
  })

  const launchFlow = async (
    node_ids: string[],
    flow_id: string,
    sketch_id: string | null | undefined
  ) => {
    if (!sketch_id) return toast.error(t('Could not find the graph.'))
    if (askUser) {
      const confirmed = await confirm({
        title: `${flow_id} scan`,
        message: t("You're about to launch {{v0}} flow on {{v1}} items.", {
          v0: flow_id,
          v1: node_ids.length
        })
      })
      if (!confirmed) return
    }
    const body = JSON.stringify({ node_ids, sketch_id })
    const count = node_ids.length

    toast.promise(launchFlowMutation.mutateAsync({ flowId: flow_id, body }), {
      loading: t('Loading...'),
      success: () =>
        t('Flow {{v0}} has been launched on {{v1}} node{{v2}}.', {
          v0: flow_id,
          v1: count,
          v2: count > 1 ? 's' : ''
        }),
      error: () => t('An error occurred launching flow.')
    })
    return
  }

  return {
    launchFlow
  }
}
