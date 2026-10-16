import { fetchWithAuth } from './api'

export interface AdminEnricher {
  id: string
  kind: 'builtin' | 'template'
  name: string
  description: string | null
  category: string
  input_type: string
  output_type: string
  is_visible: boolean
}

export const enricherAdministrationKeys = {
  access: ['enricher-administration', 'access'] as const,
  list: ['enricher-administration', 'list'] as const
}

export const enricherAdministrationService = {
  access: (): Promise<{ can_manage: boolean }> =>
    fetchWithAuth('/api/enrichers/administration/access'),
  list: (): Promise<AdminEnricher[]> => fetchWithAuth('/api/enrichers/administration'),
  setVisibility: (enricher: AdminEnricher, isVisible: boolean): Promise<AdminEnricher> =>
    fetchWithAuth(
      `/api/enrichers/administration/${encodeURIComponent(enricher.kind)}/${encodeURIComponent(enricher.id)}`,
      { method: 'PATCH', body: JSON.stringify({ is_visible: isVisible }) }
    )
}
