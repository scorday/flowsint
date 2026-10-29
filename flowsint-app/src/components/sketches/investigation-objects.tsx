import { useMemo, useState } from 'react'
import { useParams } from '@tanstack/react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Network } from 'lucide-react'
import { toast } from 'sonner'
import { sketchService } from '@/api/sketch-service'
import { useTranslation } from '@/i18n'
import { useGraphControls } from '@/stores/graph-controls-store'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogTrigger
} from '@/components/ui/dialog'

export function InvestigationObjects() {
  const { t } = useTranslation()
  const { id: sketchId, investigationId } = useParams({ strict: false })
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [selectedEdges, setSelectedEdges] = useState<Set<string>>(new Set())
  const [saving, setSaving] = useState(false)
  const refetchGraph = useGraphControls((s) => s.refetchGraph)
  const queryClient = useQueryClient()
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['investigations', investigationId, 'shared-graph'],
    queryFn: () => sketchService.getInvestigationGraph(sketchId!),
    enabled: open && !!sketchId,
    staleTime: 0
  })
  const filtered = useMemo(() => {
    const query = search.toLocaleLowerCase()
    return (data?.nds ?? []).filter((n) =>
      `${n.nodeLabel} ${n.nodeType}`.toLocaleLowerCase().includes(query)
    )
  }, [data, search])
  const edges = (data?.rls ?? []).filter((e) => selected.has(e.source) && selected.has(e.target))
  const names = new Map((data?.nds ?? []).map((n) => [n.id, n.nodeLabel]))

  const toggle = (id: string, checked: boolean) => {
    setSelected((previous) => {
      const next = new Set(previous)
      if (checked) next.add(id)
      else next.delete(id)
      return next
    })
  }
  const add = async () => {
    if (!sketchId) return
    setSaving(true)
    try {
      await sketchService.attachSubgraph(
        sketchId,
        [...selected],
        edges.filter((e) => selectedEdges.has(e.id)).map((e) => e.id)
      )
      await queryClient.invalidateQueries({ queryKey: ['investigations', investigationId] })
      await refetchGraph()
      setOpen(false)
      setSelected(new Set())
      setSelectedEdges(new Set())
      toast.success(t('Objects added to sketch.'))
    } catch {
      toast.error(t('Failed to add investigation objects.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (!saving) setOpen(value)
      }}
    >
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm" className="h-7" title={t('Investigation objects')}>
          <Network className="h-4 w-4" />
          <span className="hidden md:inline">{t('Investigation objects')}</span>
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('Investigation objects')}</DialogTitle>
          <DialogDescription>
            {t(
              'Add existing objects and relations to this sketch. Object data is shared; positions and visible relations belong to each sketch.'
            )}
          </DialogDescription>
        </DialogHeader>
        <Input
          aria-label={t('Search investigation objects')}
          placeholder={t('Search investigation objects')}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        {isLoading && <p role="status">{t('Loading...')}</p>}
        {isError && (
          <Button variant="outline" onClick={() => refetch()}>
            {t('Retry')}
          </Button>
        )}
        {!isLoading && !isError && (
          <>
            <div className="max-h-64 overflow-y-auto space-y-1">
              {filtered.slice(0, 200).map((node) => (
                <label key={node.id} className="flex gap-3 items-center rounded p-2 hover:bg-muted">
                  <Checkbox
                    aria-label={`${node.nodeLabel} ${node.nodeType}`}
                    checked={selected.has(node.id)}
                    onCheckedChange={(checked) => toggle(node.id, checked === true)}
                  />
                  <span className="truncate flex-1">{node.nodeLabel}</span>
                  <span className="text-xs text-muted-foreground">{node.nodeType}</span>
                </label>
              ))}
              {!filtered.length && (
                <p className="text-sm text-muted-foreground">{t('No objects found.')}</p>
              )}
              {filtered.length > 200 && (
                <p className="text-sm text-muted-foreground">
                  {t('Showing the first 200 matches. Refine your search.')}
                </p>
              )}
            </div>
            {edges.length > 0 && (
              <div className="border-t pt-2 max-h-40 overflow-y-auto">
                <p className="text-sm font-medium mb-2">{t('Relations to show')}</p>
                {edges.map((edge) => (
                  <label key={edge.id} className="flex gap-3 items-center p-2">
                    <Checkbox
                      aria-label={`${names.get(edge.source)} → ${edge.label} → ${names.get(edge.target)}`}
                      checked={selectedEdges.has(edge.id)}
                      onCheckedChange={(checked) =>
                        setSelectedEdges((previous) => {
                          const next = new Set(previous)
                          if (checked === true) next.add(edge.id)
                          else next.delete(edge.id)
                          return next
                        })
                      }
                    />
                    <span className="text-sm truncate">
                      {names.get(edge.source)} → {edge.label} → {names.get(edge.target)}
                    </span>
                  </label>
                ))}
              </div>
            )}
          </>
        )}
        <DialogFooter>
          <Button variant="outline" disabled={saving} onClick={() => setOpen(false)}>
            {t('Cancel')}
          </Button>
          <Button disabled={saving || !selected.size || isError || isLoading} onClick={add}>
            {saving ? t('Saving...') : t('Add to sketch')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
