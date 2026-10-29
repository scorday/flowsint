import { useTranslation } from '@/i18n'
import { toast } from 'sonner'
import { useConfirm } from '@/components/use-confirm-dialog'
import { enricherService } from '@/api/enricher-service'
import { useLayoutStore } from '@/stores/layout-store'
import { useQueryClient } from '@tanstack/react-query'
import { queryKeys } from '@/api/query-keys'

export function useLaunchEnricher(askUser: boolean = false) {
  const { t } = useTranslation()

  const { confirm } = useConfirm()
  const openClonsole = useLayoutStore((s) => s.openConsole)
  const queryClient = useQueryClient()

  const launchEnricher = async (
    node_ids: string[],
    enricherName: string,
    sketch_id: string | null | undefined,
    params?: Record<string, string>
  ) => {
    if (!sketch_id) return toast.error(t('Could not find the graph.'))
    if (askUser) {
      const confirmed = await confirm({
        title: `${enricherName} scan`,
        message: t("You're about to launch {{v0}} enricher on {{v1}} items.", {
          v0: enricherName,
          v1: node_ids.length
        })
      })
      if (!confirmed) return
    }
    // Omitted rather than sent as null when the enricher declares no params,
    // so callers that never had params keep sending the exact same payload.
    const body = JSON.stringify(params ? { node_ids, sketch_id, params } : { node_ids, sketch_id })
    const count = node_ids.length
    toast.promise(enricherService.launch(enricherName, body), {
      loading: t('Loading...'),
      success: () =>
        t('Enricher {{v0}} has been launched on {{v1}} node{{v2}}.', {
          v0: enricherName,
          v1: count,
          v2: count > 1 ? 's' : ''
        }),
      error: () => t('An error occurred launching enricher.')
    })
    queryClient.invalidateQueries({
      queryKey: queryKeys.scans.list
    })
    openClonsole()
    return
  }
  return {
    launchEnricher
  }
}
