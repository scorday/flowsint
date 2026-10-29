import { useQuery } from '@tanstack/react-query'
import {
  enricherAdministrationKeys,
  enricherAdministrationService
} from '@/api/enricher-administration-service'

export function useEnricherAdministrationAccess() {
  return useQuery({
    queryKey: enricherAdministrationKeys.access,
    queryFn: enricherAdministrationService.access,
    retry: false
  })
}
