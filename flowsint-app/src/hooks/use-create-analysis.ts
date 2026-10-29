import { useTranslation } from '@/i18n'
import { analysisService } from '@/api/analysis-service'
import { Analysis } from '@/types'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import default_content from '@/components/analyses/default_content.json'
import { queryKeys } from '@/api/query-keys'
import { toast } from 'sonner'

export const useCreateAnalysis = (
  investigationId: string,
  onAnalysisCreate?: (investigationId: string) => void
) => {
  const { t } = useTranslation()

  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async () => {
      const newAnalysis: Partial<Analysis> = {
        title: t('Untitled Analysis'),
        investigation_id: investigationId,
        content: default_content
      }
      const res = await analysisService.create(JSON.stringify(newAnalysis))
      return res
    },
    onSuccess: async () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.analyses.byInvestigation(investigationId || '')
      })
      onAnalysisCreate?.(investigationId)
      toast.success(t('New analysis created'))
    },
    onError: (error) => {
      toast.error(
        t('Failed to create analysis: ') +
          (error instanceof Error ? error.message : t('Unknown error'))
      )
    }
  })
}
