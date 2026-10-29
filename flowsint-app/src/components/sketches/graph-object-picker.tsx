import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { sketchService } from '@/api/sketch-service'
import { useDebounce } from '@/hooks/use-debounce'
import { useTranslation } from '@/i18n'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'

export function GraphObjectPicker({
  sketchId,
  label,
  value,
  onChange,
  disabled
}: {
  sketchId: string
  label: string
  value: string
  onChange: (id: string) => void
  disabled: boolean
}) {
  const { t } = useTranslation()
  const [search, setSearch] = useState('')
  const query = useDebounce(search, 250)
  const matches = useQuery({
    queryKey: ['graph-object-search', sketchId, query],
    queryFn: ({ signal }) => sketchService.searchGraphObjects(sketchId, query, [], signal),
    retry: false
  })
  const selected = useQuery({
    queryKey: ['graph-object', sketchId, value],
    queryFn: ({ signal }) => sketchService.searchGraphObjects(sketchId, '', [value], signal),
    enabled: !!value,
    retry: false
  })
  return (
    <div className="space-y-2 min-w-0">
      <label className="text-sm font-medium">
        {label}
        <Input
          value={search}
          disabled={disabled}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={t('Search all investigation objects')}
        />
      </label>
      {value && (
        <p className="text-sm break-words">
          {t('Selected object')}: {selected.data?.nodes[0]?.nodeLabel ?? t('Loading...')}
        </p>
      )}
      <div className="border rounded max-h-28 overflow-y-auto">
        {matches.isFetching && (
          <p role="status" className="p-2 text-sm">
            {t('Loading...')}
          </p>
        )}
        {matches.isError && (
          <Button variant="ghost" onClick={() => matches.refetch()}>
            {t('Retry')}
          </Button>
        )}
        {!matches.isFetching &&
          matches.data?.nodes.map((node) => (
            <button
              type="button"
              key={node.id}
              disabled={disabled}
              aria-pressed={node.id === value}
              onClick={() => onChange(node.id)}
              className="block w-full text-left p-2 text-sm hover:bg-muted aria-pressed:bg-muted"
            >
              {node.nodeLabel}{' '}
              <span className="text-xs text-muted-foreground">{node.nodeType}</span>
            </button>
          ))}
        {!matches.isFetching && !matches.isError && !matches.data?.nodes.length && (
          <p className="p-2 text-sm">{t('No objects found.')}</p>
        )}
      </div>
      {matches.data?.has_more && (
        <p className="text-xs text-muted-foreground">
          {t('Showing the first 50 objects. Refine your search.')}
        </p>
      )}
    </div>
  )
}
