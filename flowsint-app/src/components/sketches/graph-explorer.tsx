import { useEffect, useRef, useState } from 'react'
import { useParams, useRouter } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Network, Route } from 'lucide-react'
import { toast } from 'sonner'
import {
  sketchService,
  type ExplorationOptions,
  type ExplorationKind,
  type ExplorationJob
} from '@/api/sketch-service'
import { useTranslation } from '@/i18n'
import { usePermissions } from '@/hooks/use-can'
import { useGraphStore } from '@/stores/graph-store'
import { useGraphControls } from '@/stores/graph-controls-store'
import { useGraphExploration, type ExplorationRequest } from '@/stores/graph-exploration-store'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { GraphObjectPicker } from './graph-object-picker'
import NewSketch from './new-sketch'

export function GraphExplorer() {
  const { t } = useTranslation()
  const { id: sketchId } = useParams({ strict: false })
  const request = useGraphExploration((s) => s.request)
  const open = useGraphExploration((s) => s.open)
  const close = useGraphExploration((s) => s.close)
  useEffect(() => () => close(), [sketchId, close])
  const selected = useGraphStore((s) => s.selectedNodes)
  const currentId = useGraphStore((s) => s.currentNodeId)
  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        title={t('Explore investigation connections')}
        onClick={() =>
          sketchId &&
          open({
            sketchId,
            rootId: selected[0]?.id ?? currentId ?? undefined,
            targetId: selected[1]?.id,
            mode: 'path'
          })
        }
      >
        <Route className="h-4 w-4" />
        <span className="sr-only">{t('Explore investigation connections')}</span>
      </Button>
      {request && request.sketchId === sketchId && (
        <ExplorationDialog key={request.token} request={request} />
      )}
    </>
  )
}

function ExplorationDialog({ request }: { request: ExplorationRequest & { token: number } }) {
  const { t } = useTranslation()
  const { investigationId } = useParams({ strict: false })
  const router = useRouter()
  const { canEdit, canCreate } = usePermissions()
  const close = useGraphExploration((s) => s.close)
  const queryClient = useQueryClient()
  const initial: ExplorationOptions = {
    mode: request.mode,
    root_id: request.rootId ?? '',
    target_id: request.targetId,
    depth: request.depth ?? 2,
    node_types: [],
    edge_types: [],
    directed: false
  }
  const [options, setOptions] = useState(initial)
  const [submitted, setSubmitted] = useState<ExplorationOptions | null>(
    request.autoRun && request.rootId ? initial : null
  )
  const [action, setAction] = useState<'create' | 'attach'>('attach')
  const handled = useRef<string | null>(null)
  const catalog = useQuery({
    queryKey: ['investigations', investigationId, request.sketchId, 'exploration-catalog'],
    queryFn: ({ signal }) => sketchService.explorationCatalog(request.sketchId, signal),
    retry: false
  })
  const start = useQuery({
    queryKey: ['exploration-start', request.token, submitted],
    queryFn: () => sketchService.startExploration(request.sketchId, submitted!),
    enabled: !!submitted,
    retry: false,
    gcTime: 0,
    staleTime: Infinity,
    refetchOnWindowFocus: false
  })
  const jobId = submitted ? start.data?.id : undefined
  const statusKey = ['exploration-job', request.sketchId, jobId]
  const status = useQuery({
    queryKey: statusKey,
    queryFn: ({ signal }) => sketchService.explorationStatus(request.sketchId, jobId!, signal),
    enabled: !!jobId,
    initialData: start.data,
    gcTime: 0,
    retry: false,
    refetchInterval: (query) =>
      ['queued', 'running', 'applying'].includes(query.state.data?.status ?? '') ? 1000 : false
  })
  const result = submitted && jobId ? status.data : undefined
  const select = useMutation({
    mutationFn: (data: { kind: ExplorationKind | 'all'; checked: boolean; ids: string[] | null }) =>
      sketchService.selectExploration(request.sketchId, jobId!, {
        ...data,
        revision: result!.revision
      }),
    onSuccess: (job) => {
      queryClient.setQueryData(statusKey, job)
    },
    onError: () => {
      toast.error(t('Could not update selection. Retry.'))
      void status.refetch()
    }
  })
  const apply = useMutation({
    mutationFn: (data: { action: 'create' | 'attach'; title?: string }) =>
      sketchService.applyExploration(request.sketchId, jobId!, {
        ...data,
        revision: result!.revision
      }),
    onSuccess: (job, data) => {
      setAction(data.action)
      queryClient.setQueryData(statusKey, job)
    },
    onError: () => {
      toast.error(t('Failed to add investigation objects.'))
      void status.refetch()
    }
  })
  const cancel = useMutation({
    mutationFn: () => sketchService.cancelExploration(request.sketchId, jobId!),
    onSuccess: (job) => queryClient.setQueryData(statusKey, job),
    onError: () => toast.error(t('Could not cancel search. Retry.'))
  })
  const running = result?.status === 'running' || result?.status === 'queued'
  const applying = result?.status === 'applying'
  const busy =
    start.isFetching ||
    running ||
    applying ||
    select.isPending ||
    apply.isPending ||
    cancel.isPending
  const ready = result?.status === 'completed'
  const hasSelection = result
    ? result.selected[options.mode === 'path' ? 'paths' : 'nodes'] > 0
    : false
  useEffect(() => {
    if (result?.status !== 'applied' || !result.sketch_id || handled.current === result.id) return
    handled.current = result.id
    void (async () => {
      await queryClient.invalidateQueries({ queryKey: ['investigations', investigationId] })
      if (useGraphExploration.getState().request !== request) return
      if (action === 'create') {
        toast.success(t('New sketch created.'))
        void router.navigate({
          to: `/dashboard/investigations/${investigationId}/graph/${result.sketch_id}`
        })
      } else {
        await useGraphControls.getState().refetchGraph()
        toast.success(t('Objects added to sketch.'))
      }
      if (useGraphExploration.getState().request === request) close()
    })()
  }, [result, action, queryClient, investigationId, request, router, close, t])
  function change(patch: Partial<ExplorationOptions>) {
    setOptions((old) => ({ ...old, ...patch }))
    setSubmitted(null)
  }
  function run(depth = options.depth) {
    const next = { ...options, depth }
    setOptions(next)
    if (JSON.stringify(next) === JSON.stringify(submitted)) void start.refetch()
    else setSubmitted(next)
  }
  function dismiss() {
    if (applying || apply.isPending || start.isFetching) return
    if (running) {
      void cancel
        .mutateAsync()
        .then(close)
        .catch(() => {})
      return
    }
    close()
  }
  return (
    <Dialog open onOpenChange={(open) => !open && dismiss()}>
      <DialogContent className="sm:max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogTitle>{t('Explore investigation connections')}</DialogTitle>
        <DialogDescription>
          {t(
            'Search across every sketch in this investigation. Preview results before adding shared objects and relations to a sketch.'
          )}
        </DialogDescription>
        <div className="flex flex-wrap gap-2">
          <Button
            variant={options.mode === 'path' ? 'default' : 'outline'}
            disabled={busy}
            onClick={() => change({ mode: 'path' })}
          >
            <Route className="h-4 w-4" />
            {t('Find connections')}
          </Button>
          <Button
            variant={options.mode === 'neighborhood' ? 'default' : 'outline'}
            disabled={busy}
            onClick={() => change({ mode: 'neighborhood' })}
          >
            <Network className="h-4 w-4" />
            {t('Expand neighborhood')}
          </Button>
        </div>
        <details
          key={result ? 'preview' : 'edit'}
          open={!result}
          className="border rounded p-3 space-y-3"
        >
          <summary className="cursor-pointer text-sm font-medium">
            {t('Search settings')} · {options.depth} {t('steps')}
          </summary>
          <div className={options.mode === 'path' ? 'grid sm:grid-cols-2 gap-4' : ''}>
            <GraphObjectPicker
              sketchId={request.sketchId}
              label={t('Starting object')}
              value={options.root_id}
              onChange={(id) => change({ root_id: id })}
              disabled={busy}
            />
            {options.mode === 'path' && (
              <GraphObjectPicker
                sketchId={request.sketchId}
                label={t('Target object')}
                value={options.target_id ?? ''}
                onChange={(id) => change({ target_id: id })}
                disabled={busy}
              />
            )}
          </div>
          <label className="flex gap-2 items-center text-sm">
            {t('Maximum steps')}
            <select
              aria-label={t('Maximum steps')}
              value={options.depth}
              disabled={busy}
              className="border rounded bg-background p-2"
              onChange={(event) => change({ depth: Number(event.target.value) })}
            >
              {[1, 2, 3, 4, 5].map((depth) => (
                <option key={depth} value={depth}>
                  {depth}
                </option>
              ))}
            </select>
          </label>
          <details className="border rounded p-3">
            <summary className="cursor-pointer text-sm">{t('Traversal filters')}</summary>
            <p className="text-xs text-muted-foreground my-2">
              {t(
                'Empty type filters include all types. Starting and target objects are always allowed; filters restrict intermediate objects.'
              )}
            </p>
            {catalog.isError && (
              <Button onClick={() => catalog.refetch()} variant="outline">
                {t('Retry')}
              </Button>
            )}
            {catalog.data?.truncated && (
              <p role="status">
                {t('Only the first 100 types are listed. Unselected filters include all types.')}
              </p>
            )}
            <div className="grid sm:grid-cols-2 gap-3">
              {(['node_types', 'edge_types'] as const).map((key) => (
                <fieldset key={key} disabled={busy}>
                  <legend className="text-sm font-medium mb-2">
                    {t(key === 'node_types' ? 'Object types' : 'Relation types')}
                  </legend>
                  <div className="max-h-32 overflow-y-auto space-y-1">
                    {catalog.data?.[key].map((kind) => (
                      <label key={kind} className="flex items-center gap-2 text-xs">
                        <Checkbox
                          checked={options[key].includes(kind)}
                          disabled={
                            busy || (!options[key].includes(kind) && options[key].length >= 50)
                          }
                          onCheckedChange={(value) =>
                            change({
                              [key]:
                                value === true
                                  ? [...options[key], kind]
                                  : options[key].filter((type) => type !== kind)
                            })
                          }
                        />
                        {kind}
                      </label>
                    ))}
                  </div>
                </fieldset>
              ))}
            </div>
            <label className="flex items-center gap-2 text-sm mt-3">
              <Checkbox
                disabled={busy}
                checked={options.directed}
                onCheckedChange={(value) => change({ directed: value === true })}
              />
              {t('Follow relation direction')}
            </label>
            <p className="text-xs text-muted-foreground mt-1">
              {t(
                'By default traversal works in both directions. Original relation arrows are preserved in results.'
              )}
            </p>
          </details>
        </details>
        <div className="flex flex-wrap gap-2">
          <Button
            disabled={
              busy ||
              !options.root_id ||
              (options.mode === 'path' &&
                (!options.target_id || options.root_id === options.target_id))
            }
            onClick={() => run()}
          >
            {t(options.mode === 'path' ? 'Find connections' : 'Preview neighborhood')}
          </Button>
          {options.mode === 'neighborhood' && (
            <Button
              variant="outline"
              disabled={busy || !options.root_id || (result?.options.depth ?? 0) >= 5}
              onClick={() => run(result ? result.options.depth + 1 : 1)}
            >
              {t('Expand one more step')}
            </Button>
          )}
        </div>
        {(start.isFetching || running) && (
          <div className="flex items-center justify-between gap-3" role="status">
            <p>
              {t('Searching the investigation...')}
              {result && ` ${result.totals.nodes} / ${result.totals.edges}`}
            </p>
            {running && (
              <Button variant="outline" disabled={cancel.isPending} onClick={() => cancel.mutate()}>
                {t('Cancel search')}
              </Button>
            )}
          </div>
        )}
        {applying && (
          <p role="status">
            {t('Creating the sketch with all selected results. This may take a while.')}
          </p>
        )}
        {(start.isError || status.isError) && (
          <p role="alert" className="text-destructive">
            {t('Could not explore the graph. Retry the search.')}
          </p>
        )}
        {result?.error && (
          <p role="alert" className="text-destructive">
            {t(
              'Search did not complete. Run it again; partial results cannot be added to a sketch.'
            )}
          </p>
        )}
        {result?.status === 'cancelled' && (
          <p role="status">{t('Search cancelled. Partial results cannot be added to a sketch.')}</p>
        )}
        {running && result.stalled && (
          <p role="alert">{t('No recent search progress. You can cancel and retry.')}</p>
        )}
        {result && (ready || applying) && (
          <>
            <p role="status" className="text-sm">
              {t('Found: {{v0}} objects, {{v1}} relations, {{v2}} paths.', {
                v0: result.totals.nodes,
                v1: result.totals.edges,
                v2: result.totals.paths
              })}
            </p>
            <p className="text-xs text-muted-foreground">
              {t(
                'Selection applies to all pages. New sketches include every selected object and relation.'
              )}
            </p>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => select.mutate({ kind: 'all', checked: true, ids: null })}
              >
                {t('Select all results')}
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => select.mutate({ kind: 'all', checked: false, ids: null })}
              >
                {t('Clear all results')}
              </Button>
            </div>
            <div className={options.mode === 'path' ? '' : 'grid sm:grid-cols-2 gap-4'}>
              {(options.mode === 'path' ? (['paths'] as const) : (['nodes', 'edges'] as const)).map(
                (kind) => (
                  <ResultPage
                    key={`${result.id}:${kind}`}
                    kind={kind}
                    job={result}
                    sketchId={request.sketchId}
                    disabled={busy}
                    onSelect={(checked, ids) => select.mutate({ kind, checked, ids })}
                    viewNames={new Map(catalog.data?.sketches.map((view) => [view.id, view.title]))}
                  />
                )
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              {t(
                'A path shows a chain of recorded relations; it does not imply a direct relation between its endpoints.'
              )}
            </p>
            <div className="flex flex-wrap justify-end gap-2">
              {canCreate && (
                <NewSketch
                  onCreate={async ({ title }) => {
                    await apply.mutateAsync({ action: 'create', title })
                  }}
                >
                  <Button
                    variant="outline"
                    disabled={!hasSelection || busy || !ready || status.isError}
                  >
                    {t('Create sketch from result')}
                  </Button>
                </NewSketch>
              )}
              {canEdit && (
                <Button
                  disabled={!hasSelection || busy || !ready || status.isError}
                  onClick={() => apply.mutate({ action: 'attach' })}
                >
                  {t('Add selected result to sketch')}
                </Button>
              )}
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

function ResultPage({
  kind,
  job,
  sketchId,
  disabled,
  onSelect,
  viewNames
}: {
  kind: ExplorationKind
  job: ExplorationJob
  sketchId: string
  disabled: boolean
  onSelect: (checked: boolean, ids: string[] | null) => void
  viewNames: Map<string, string>
}) {
  const { t } = useTranslation()
  const [page, setPage] = useState(0)
  const query = useQuery({
    queryKey: ['exploration-page', sketchId, job.id, kind, page, job.revision],
    queryFn: ({ signal }) => sketchService.explorationPage(sketchId, job.id, kind, page, signal),
    gcTime: 0,
    retry: false,
    refetchOnWindowFocus: false
  })
  const rows = query.data?.items ?? []
  const pages = Math.max(1, Math.ceil(job.totals[kind] / 50))
  const busy = disabled || query.isFetching || query.isError
  return (
    <section
      className="min-w-0 space-y-3 border rounded p-3"
      aria-label={t(
        kind === 'nodes'
          ? 'Objects to show'
          : kind === 'edges'
            ? 'Relations to show'
            : 'Paths to show'
      )}
    >
      <p className="text-sm font-medium">
        {t(
          kind === 'nodes'
            ? 'Objects to show'
            : kind === 'edges'
              ? 'Relations to show'
              : 'Paths to show'
        )}{' '}
        · {job.selected[kind]} / {job.totals[kind]}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="outline"
          disabled={busy || !rows.length}
          onClick={() =>
            onSelect(
              true,
              rows.map((row) => row.id)
            )
          }
        >
          {t('Select page')}
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={busy || !rows.length}
          onClick={() =>
            onSelect(
              false,
              rows.map((row) => row.id)
            )
          }
        >
          {t('Clear page')}
        </Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => onSelect(true, null)}>
          {t('Select all')}
        </Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => onSelect(false, null)}>
          {t('Clear selection')}
        </Button>
      </div>
      {query.isFetching && <p role="status">{t('Loading...')}</p>}
      {query.isError && (
        <Button variant="outline" onClick={() => query.refetch()}>
          {t('Retry')}
        </Button>
      )}
      <div className="max-h-64 overflow-y-auto space-y-3">
        {rows.map((row, index) => {
          const label =
            'nodeLabel' in row
              ? row.nodeLabel
              : 'node_ids' in row
                ? t('Path {{v0}}: {{v1}} steps', {
                    v0: page * 50 + index + 1,
                    v1: row.edge_ids.length
                  })
                : `${row.sourceLabel} → ${row.label} → ${row.targetLabel}`
          return (
            <label key={row.id} className="flex gap-2 items-start text-sm break-words">
              <Checkbox
                checked={row.selected}
                disabled={busy}
                aria-label={label}
                onCheckedChange={(checked) => onSelect(checked === true, [row.id])}
              />
              <span className="min-w-0">
                {label}
                {'nodeLabel' in row && (
                  <span className="text-xs text-muted-foreground">
                    {' '}
                    · {row.distance} {t('steps')}{' '}
                    {row.on_sketch && `· ${t('Already on this sketch')}`}
                  </span>
                )}
                {'sourceLabel' in row && (
                  <span className="block text-xs text-muted-foreground">
                    {row.views.map((id) => viewNames.get(id) ?? t('Sketch')).join(', ') ||
                      t('Not shown on a sketch')}
                  </span>
                )}
                {'node_ids' in row && (
                  <span className="block text-xs text-muted-foreground">
                    {row.nodes.map((node, step) => (
                      <span key={node.id}>
                        {node.nodeLabel}
                        {row.edges[step] && (
                          <span>
                            {' '}
                            {row.edges[step].source === node.id ? '→' : '←'} {row.edges[step].label}{' '}
                            (
                            {row.edges[step].views
                              .map((id) => viewNames.get(id) ?? t('Sketch'))
                              .join(', ') || t('Not shown on a sketch')}
                            ){' '}
                          </span>
                        )}
                      </span>
                    ))}
                  </span>
                )}
              </span>
            </label>
          )
        })}
      </div>
      <div className="flex items-center justify-between gap-2 text-xs">
        <Button
          size="sm"
          variant="outline"
          disabled={busy || page === 0}
          onClick={() => setPage(page - 1)}
        >
          <ChevronLeft className="h-4 w-4" />
          <span className="sr-only">{t('Previous page')}</span>
        </Button>
        <span>{t('Page {{v0}} of {{v1}}', { v0: page + 1, v1: pages })}</span>
        <Button
          size="sm"
          variant="outline"
          disabled={busy || page + 1 >= pages}
          onClick={() => setPage(page + 1)}
        >
          <ChevronRight className="h-4 w-4" />
          <span className="sr-only">{t('Next page')}</span>
        </Button>
      </div>
    </section>
  )
}
