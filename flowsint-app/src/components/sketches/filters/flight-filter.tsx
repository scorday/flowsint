import { useTranslation } from '@/i18n'
import { useGraphStore } from '@/stores/graph-store'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select'
import type { GraphNode } from '@/types'

function flightLabel(node: GraphNode, language: string) {
  const properties = node.nodeProperties
  const formatTime = (value: unknown) => {
    if (typeof value !== 'string' || !Number.isFinite(Date.parse(value))) return ''
    return new Intl.DateTimeFormat(language, {
      dateStyle: 'short',
      timeStyle: 'short',
      timeZone: 'UTC'
    }).format(new Date(value))
  }
  const times = [properties.first_seen_at, properties.last_seen_at].map(formatTime).filter(Boolean)
  return (
    [
      properties.aircraft_hex,
      Array.isArray(properties.callsigns) ? properties.callsigns.join(', ') : '',
      times.length ? `${times.join(' – ')} UTC` : ''
    ]
      .filter(Boolean)
      .join(' · ') || node.nodeLabel
  )
}

export default function FlightFilter() {
  const { t, language } = useTranslation()
  const nodes = useGraphStore((s) => s.nodes)
  const flightId = useGraphStore((s) => s.filters.mapFlightId)
  const flights = nodes
    .filter((node) => node.nodeType === 'flight')
    .sort((a, b) =>
      String(b.nodeProperties.first_seen_at ?? '').localeCompare(
        String(a.nodeProperties.first_seen_at ?? '')
      )
    )
  const selectedFlight = flights.find((flight) => flight.id === flightId)

  if (flights.length === 0 && !flightId) return null

  return (
    <>
      <Separator />
      <div className="space-y-2">
        <Label htmlFor="map-flight-filter">{t('Flight')}</Label>
        <Select
          value={flightId || 'all'}
          onValueChange={(value) => {
            const { filters, setFilters } = useGraphStore.getState()
            setFilters({ ...filters, mapFlightId: value === 'all' ? null : value })
          }}
        >
          <SelectTrigger
            id="map-flight-filter"
            className="w-full min-w-0"
            title={selectedFlight ? flightLabel(selectedFlight, language) : undefined}
          >
            <SelectValue className="block! min-w-0 truncate" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('All flights')}</SelectItem>
            {flightId && !selectedFlight && (
              <SelectItem value={flightId} disabled>
                {t('Flight no longer available')}
              </SelectItem>
            )}
            {flights.map((flight) => (
              <SelectItem key={flight.id} value={flight.id}>
                {flightLabel(flight, language)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-xs text-muted-foreground">
          {t('Shows only positions linked to the selected flight. Times are in UTC.')}
        </p>
      </div>
    </>
  )
}
