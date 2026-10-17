import { useTranslation } from '@/i18n'
import { useGraphStore } from '@/stores/graph-store'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Separator } from '@/components//ui/separator'
import TypeFilters from './type-filters'
import FlightFilter from './flight-filter'
import { useGraphControls } from '@/stores/graph-controls-store'

const Filters = ({ children }: { children: React.ReactNode }) => {
  const { t } = useTranslation()

  const filters = useGraphStore((s) => s.filters)
  const toggleTypeFilter = useGraphStore((s) => s.toggleTypeFilter)
  const view = useGraphControls((s) => s.view)

  return (
    <Popover>
      <PopoverTrigger asChild>
        <div>{children}</div>
      </PopoverTrigger>
      <PopoverContent className="w-112 bg-background max-h-[60vh] overflow-auto">
        <div className="grid gap-2">
          <div className="space-y-1">
            <h5 className="leading-none font-medium text-sm">{t('Filters')}</h5>
          </div>
          <Separator />
          <TypeFilters filters={filters} toggleTypeFilter={toggleTypeFilter} />
          {view === 'map' && <FlightFilter />}
          {/* <Separator />
          <RuleFilters filters={filters} setFilters={setFilters} /> */}
        </div>
      </PopoverContent>
    </Popover>
  )
}

export default Filters
