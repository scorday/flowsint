import { createFileRoute } from '@tanstack/react-router'
import { EnricherAdministration } from '@/components/admin/enricher-administration'

export const Route = createFileRoute('/_auth/dashboard/admin/enrichers')({
  component: EnricherAdministration
})
