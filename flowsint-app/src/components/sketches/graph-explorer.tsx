import { Fragment, useEffect, useMemo, useState } from 'react'
import { useParams } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Network, Route } from 'lucide-react'
import { toast } from 'sonner'
import { sketchService, type ExplorationOptions, type GraphExploration } from '@/api/sketch-service'
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

type Selection = {
  result: GraphExploration
  nodes: Set<string>
  edges: Set<string>
  paths: Set<number>
}

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

function ExplorationDialog({ request }: { request: ExplorationRequest }) {
  const { t } = useTranslation()
  const { investigationId } = useParams({ strict: false })
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
  const [selection, setSelection] = useState<Selection | null>(null)
  const catalog = useQuery({
    queryKey: ['investigations', investigationId, request.sketchId, 'exploration-catalog'],
    queryFn: ({ signal }) => sketchService.explorationCatalog(request.sketchId, signal),
    retry: false
  })
  const preview = useQuery({
    queryKey: ['investigations', investigationId, request.sketchId, 'exploration', submitted],
    queryFn: ({ signal }) => sketchService.explore(request.sketchId, submitted!, signal),
    enabled: !!submitted,
    retry: false,
    staleTime: 0,
    gcTime: 0,
    refetchOnWindowFocus: false
  })
  const result = submitted ? preview.data : undefined
  const defaultSelection = useMemo<Selection | null>(
    () =>
      result
        ? {
            result,
            nodes: new Set(result.nds.map((n) => n.id)),
            edges: new Set(result.rls.map((e) => e.id)),
            paths: new Set(result.paths.length ? [0] : [])
          }
        : null,
    [result]
  )
  const chosen = selection?.result === result ? selection : defaultSelection
  const nodeIds =
    options.mode === 'path'
      ? [
          ...new Set(
            result?.paths.flatMap((path, index) =>
              chosen?.paths.has(index) ? path.node_ids : []
            ) ?? []
          )
        ]
      : [...(chosen?.nodes ?? [])]
  const edgeIds =
    options.mode === 'path'
      ? [
          ...new Set(
            result?.paths.flatMap((path, index) =>
              chosen?.paths.has(index) ? path.edge_ids : []
            ) ?? []
          )
        ]
      : [...(chosen?.edges ?? [])]
  const names = new Map(result?.nds.map((node) => [node.id, node.nodeLabel]))
  const relations = new Map(result?.rls.map((edge) => [edge.id, edge]))
  const views = new Map(catalog.data?.sketches.map((view) => [view.id, view.title]))
  const edgeViews = (id: string) =>
    (result?.edge_views[id] ?? []).map((view) => views.get(view) ?? t('Sketch')).join(', ') ||
    t('Not shown on a sketch')

  const attach = useMutation({
    mutationFn: () => sketchService.attachSubgraph(request.sketchId, nodeIds, edgeIds),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['investigations', investigationId] })
      if (useGraphExploration.getState().request !== request) return
      await useGraphControls.getState().refetchGraph()
      if (useGraphExploration.getState().request !== request) return
      useGraphStore.getState().setHighlightedNodes(nodeIds)
      toast.success(t('Objects added to sketch.'))
      close()
    },
    onError: () => toast.error(t('Failed to add investigation objects.'))
  })
  const busy = preview.isFetching || attach.isPending
  function change(patch: Partial<ExplorationOptions>) {
    setOptions((old) => ({ ...old, ...patch }))
    setSubmitted(null)
  }
  function run(depth = options.depth) {
    const next = { ...options, depth }
    setOptions(next)
    if (JSON.stringify(next) === JSON.stringify(submitted)) void preview.refetch()
    else setSubmitted(next)
  }
  function toggleNode(id: string, checked: boolean) {
    if (!chosen || !result) return
    const nodes = new Set(chosen.nodes)
    if (checked) nodes.add(id)
    else nodes.delete(id)
    const edges = new Set(
      [...chosen.edges].filter((uid) => {
        const edge = relations.get(uid)
        return edge && nodes.has(edge.source) && nodes.has(edge.target)
      })
    )
    setSelection({ ...chosen, nodes, edges })
  }
  function toggleEdge(id: string, checked: boolean) {
    if (!chosen) return
    const edges = new Set(chosen.edges)
    const nodes = new Set(chosen.nodes)
    if (checked) {
      edges.add(id)
      const edge = relations.get(id)
      if (edge) {
        nodes.add(edge.source)
        nodes.add(edge.target)
      }
    } else edges.delete(id)
    setSelection({ ...chosen, nodes, edges })
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !attach.isPending && close()}>
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
              disabled={busy || !options.root_id || (result?.depth ?? 0) >= 5}
              onClick={() => run(result ? result.depth + 1 : 1)}
            >
              {t('Expand one more step')}
            </Button>
          )}
        </div>
        {preview.isFetching && <p role="status">{t('Searching the investigation...')}</p>}
        {submitted && preview.isError && (
          <p role="alert" className="text-destructive">
            {t('Could not explore the graph. Retry the search.')}
          </p>
        )}
        {result && !preview.isFetching && (
          <>
            <p role="status" className="text-sm">
              {t('Preview: {{v0}} objects, {{v1}} relations.', {
                v0: result.nds.length,
                v1: result.rls.length
              })}
            </p>
            {result.truncated && (
              <p role="alert" className="border border-amber-600 rounded p-2 text-sm">
                {t(
                  'The search reached a limit. This is a partial result; missing paths may still exist. Reduce depth or refine filters.'
                )}{' '}
                {t('Limits: {{v0}} objects, {{v1}} relations, {{v2}} paths.', {
                  v0: result.limits.nodes,
                  v1: result.limits.edges,
                  v2: result.limits.paths
                })}
              </p>
            )}
            {options.mode === 'path' ? (
              <div className="max-h-72 overflow-y-auto space-y-3">
                {!result.paths.length && (
                  <p>
                    {t(
                      result.truncated
                        ? 'No path was found in the examined part of the graph.'
                        : 'No path found within the selected depth and filters.'
                    )}
                  </p>
                )}
                {result.paths.map((path, index) => (
                  <label
                    key={path.edge_ids.join(':')}
                    className="block border rounded p-3 space-y-2"
                  >
                    <span className="flex gap-2 items-center">
                      <Checkbox
                        aria-label={t('Select path {{v0}}', { v0: index + 1 })}
                        checked={chosen?.paths.has(index)}
                        onCheckedChange={(value) => {
                          if (!chosen) return
                          const paths = new Set(chosen.paths)
                          if (value === true) paths.add(index)
                          else paths.delete(index)
                          setSelection({ ...chosen, paths })
                        }}
                      />
                      {t('Path {{v0}}: {{v1}} steps', { v0: index + 1, v1: path.edge_ids.length })}
                    </span>
                    <span className="flex flex-wrap items-center gap-2 text-sm">
                      {path.node_ids.map((id, step) => (
                        <Fragment key={id}>
                          <span className="font-medium">{names.get(id)}</span>
                          {path.edge_ids[step] && (
                            <span className="text-xs text-muted-foreground">
                              {relations.get(path.edge_ids[step])?.source === id ? '→' : '←'}{' '}
                              {relations.get(path.edge_ids[step])?.label} (
                              {edgeViews(path.edge_ids[step])})
                            </span>
                          )}
                        </Fragment>
                      ))}
                    </span>
                  </label>
                ))}
              </div>
            ) : (
              <div className="grid sm:grid-cols-2 gap-4">
                <div className="max-h-64 overflow-y-auto space-y-2">
                  <p className="text-sm font-medium">{t('Objects to show')}</p>
                  {result.nds.map((node) => (
                    <label key={node.id} className="flex gap-2 items-start text-sm">
                      <Checkbox
                        aria-label={node.nodeLabel}
                        checked={chosen?.nodes.has(node.id)}
                        onCheckedChange={(value) => toggleNode(node.id, value === true)}
                      />
                      <span>
                        {node.nodeLabel}{' '}
                        <span className="text-xs text-muted-foreground">
                          · {result.distances[node.id]} {t('steps')}{' '}
                          {result.on_sketch.includes(node.id) && `· ${t('Already on this sketch')}`}
                        </span>
                      </span>
                    </label>
                  ))}
                </div>
                <div className="max-h-64 overflow-y-auto space-y-2">
                  <p className="text-sm font-medium">{t('Relations to show')}</p>
                  {result.rls.map((edge) => (
                    <label key={edge.id} className="flex gap-2 items-start text-xs">
                      <Checkbox
                        aria-label={`${names.get(edge.source)} ${edge.label} ${names.get(edge.target)}`}
                        checked={chosen?.edges.has(edge.id)}
                        onCheckedChange={(value) => toggleEdge(edge.id, value === true)}
                      />
                      <span>
                        {names.get(edge.source)} → {edge.label} → {names.get(edge.target)}
                        <br />
                        <span className="text-muted-foreground">{edgeViews(edge.id)}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            )}
            <p className="text-xs text-muted-foreground">
              {t(
                'A path shows a chain of recorded relations; it does not imply a direct relation between its endpoints.'
              )}
            </p>
            <div className="flex flex-wrap justify-end gap-2">
              {canCreate && (
                <NewSketch selection={{ nodeIds, edgeIds }}>
                  <Button variant="outline" disabled={!nodeIds.length || busy || preview.isError}>
                    {t('Create sketch from result')}
                  </Button>
                </NewSketch>
              )}
              {canEdit && (
                <Button
                  disabled={!nodeIds.length || busy || preview.isError}
                  onClick={() => attach.mutate()}
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
