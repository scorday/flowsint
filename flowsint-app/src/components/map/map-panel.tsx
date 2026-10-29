import { useGraphStore } from '@/stores/graph-store'
import { useNodesDisplaySettings } from '@/stores/node-display-settings'
import { useTranslation } from '@/i18n'
import { MapFromAddress } from './map'
import { getMapLocations } from './map-locations'
import { useMemo } from 'react'
import { getFlightRoutes } from './flight-routes'
const MapPanel = () => {
  const { t } = useTranslation()
  const nodes = useGraphStore((state) => state.filteredNodes)
  const allNodes = useGraphStore((state) => state.nodes)
  const edges = useGraphStore((state) => state.edges)
  const flightId = useGraphStore((state) => state.filters.mapFlightId)
  const hasTypeFilters = useGraphStore((state) =>
    state.filters.types.some((filter) => !filter.checked)
  )
  const nodeColors = useNodesDisplaySettings((s) => s.colors)
  const locationNodes = useMemo(
    () => getMapLocations(nodes, edges, flightId, nodeColors),
    [nodes, edges, flightId, nodeColors]
  )
  const flightRoutes = useMemo(
    () => getFlightRoutes(locationNodes, allNodes, edges, flightId, nodeColors),
    [locationNodes, allNodes, edges, flightId, nodeColors]
  )
  if (locationNodes.length === 0 && (flightId || hasTypeFilters)) {
    return (
      <div className="h-full w-full flex items-center justify-center text-muted-foreground">
        {t('No locations match the current filters.')}
      </div>
    )
  }
  return (
    <div className="w-full grow h-full">
      <MapFromAddress locations={locationNodes} flightRoutes={flightRoutes} centerOnFirst={false} />
    </div>
  )
}

export default MapPanel
