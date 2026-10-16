import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Eye, EyeOff, Loader2, Search, ShieldCheck } from 'lucide-react'
import {
  type AdminEnricher,
  enricherAdministrationKeys,
  enricherAdministrationService
} from '@/api/enricher-administration-service'
import { useEnricherAdministrationAccess } from '@/hooks/use-enricher-administration-access'
import { isAvl4 } from '@/platform/runtime-config'
import { PageLayout } from '@/components/layout/page-layout'
import { ErrorState } from '@/components/shared/error-state'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table'

function isForbidden(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false
  if ('status' in error && error.status === 403) return true
  return (
    'response' in error &&
    typeof error.response === 'object' &&
    error.response !== null &&
    'status' in error.response &&
    error.response.status === 403
  )
}

function VisibilityControl({ enricher }: { enricher: AdminEnricher }) {
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: (isVisible: boolean) =>
      enricherAdministrationService.setVisibility(enricher, isVisible),
    onSuccess: async (updated) => {
      queryClient.setQueryData<AdminEnricher[]>(enricherAdministrationKeys.list, (previous) =>
        previous?.map((item) =>
          item.kind === updated.kind && item.id === updated.id ? updated : item
        )
      )
      await Promise.all(
        [['enrichers'], ['raw_material'], ['actionItems'], ['template', 'enrichers']].map(
          (queryKey) => queryClient.invalidateQueries({ queryKey })
        )
      )
    }
  })

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3">
        <Switch
          checked={enricher.is_visible}
          disabled={mutation.isPending}
          onCheckedChange={(checked) => mutation.mutate(checked)}
          aria-label={`Show ${enricher.name} (${enricher.kind}) in catalog and launch menus`}
        />
        <Badge variant={enricher.is_visible ? 'secondary' : 'outline'}>
          {enricher.is_visible ? <Eye aria-hidden="true" /> : <EyeOff aria-hidden="true" />}
          {enricher.is_visible ? 'Visible' : 'Hidden'}
        </Badge>
        {mutation.isPending && <Loader2 className="size-3 animate-spin" aria-label="Saving" />}
      </div>
      {mutation.isError && (
        <p role="alert" className="max-w-52 whitespace-normal text-xs text-destructive">
          Couldn&apos;t save visibility. Try the switch again.
        </p>
      )}
    </div>
  )
}

export function EnricherAdministration() {
  const access = useEnricherAdministrationAccess()
  const catalog = useQuery({
    queryKey: enricherAdministrationKeys.list,
    queryFn: enricherAdministrationService.list,
    enabled: access.data?.can_manage === true,
    retry: false
  })
  const [search, setSearch] = useState('')
  const [kind, setKind] = useState('all')
  const [visibility, setVisibility] = useState('all')
  const enrichers = catalog.data ?? []
  const visibleCount = enrichers.filter((enricher) => enricher.is_visible).length
  const term = search.trim().toLowerCase()
  const filtered = enrichers.filter(
    (enricher) =>
      (kind === 'all' || enricher.kind === kind) &&
      (visibility === 'all' || enricher.is_visible === (visibility === 'visible')) &&
      [
        enricher.name,
        enricher.description,
        enricher.category,
        enricher.input_type,
        enricher.output_type
      ].some((value) => value?.toLowerCase().includes(term))
  )
  const isLoading = access.isPending || (access.data?.can_manage && catalog.isPending)
  const error = access.error ?? catalog.error
  const forbidden = access.data?.can_manage === false || isForbidden(error)

  return (
    <PageLayout
      title="Enricher administration"
      description="Control which enrichers appear in the catalog and launch menus."
      isLoading={Boolean(isLoading)}
      loadingComponent={
        <div role="status" className="flex items-center gap-2 py-12 text-muted-foreground">
          <Loader2 className="size-4 animate-spin" aria-hidden="true" />
          Loading enricher administration…
        </div>
      }
      error={forbidden ? null : error}
      errorComponent={
        <ErrorState
          title="Couldn't load enricher administration"
          description="Check your access and connection, then try again."
          onRetry={() => (access.isError ? access.refetch() : catalog.refetch())}
        />
      }
    >
      {forbidden ? (
        <div className="flex flex-col items-center gap-3 py-16 text-center">
          <ShieldCheck className="size-8 text-muted-foreground" aria-hidden="true" />
          <h2 className="text-lg font-semibold">Administrator access required</h2>
          <p className="max-w-md text-sm text-muted-foreground">
            Your account cannot manage enricher visibility. Contact your administrator for access.
          </p>
        </div>
      ) : (
        <div className="min-w-0 space-y-6">
          <Alert>
            <ShieldCheck aria-hidden="true" />
            <AlertDescription>
              <p>
                {isAvl4
                  ? 'Visibility settings apply to the current AVL4 project.'
                  : 'Visibility settings apply to this Flowsint instance.'}{' '}
                Hidden enrichers are removed from the catalog and launch menus. Saved flows remain
                runnable. You can restore a hidden enricher here at any time.
              </p>
            </AlertDescription>
          </Alert>

          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm" aria-live="polite">
            <span className="text-muted-foreground">
              All <strong className="ml-1 text-foreground">{enrichers.length}</strong>
            </span>
            <span className="flex items-center gap-2 text-muted-foreground">
              <Eye className="size-3.5" aria-hidden="true" />
              Visible <strong className="text-foreground">{visibleCount}</strong>
            </span>
            <span className="flex items-center gap-2 text-muted-foreground">
              <EyeOff className="size-3.5" aria-hidden="true" />
              Hidden <strong className="text-foreground">{enrichers.length - visibleCount}</strong>
            </span>
          </div>

          <div className="flex flex-wrap gap-3">
            <div className="relative min-w-52 flex-1">
              <Search
                className="absolute left-3 top-2.5 size-4 text-muted-foreground"
                aria-hidden="true"
              />
              <Input
                aria-label="Search enrichers"
                placeholder="Search name, description, category or type…"
                className="pl-9"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </div>
            <Select value={kind} onValueChange={setKind}>
              <SelectTrigger aria-label="Enricher kind" className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All kinds</SelectItem>
                <SelectItem value="builtin">Built-in</SelectItem>
                <SelectItem value="template">Template</SelectItem>
              </SelectContent>
            </Select>
            <Select value={visibility} onValueChange={setVisibility}>
              <SelectTrigger aria-label="Visibility filter" className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All visibility</SelectItem>
                <SelectItem value="visible">Visible</SelectItem>
                <SelectItem value="hidden">Hidden</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="min-w-0 overflow-hidden rounded-md border bg-card">
            <Table className="min-w-[760px]" aria-label="All enrichers">
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-4">Enricher</TableHead>
                  <TableHead>Kind</TableHead>
                  <TableHead>Category</TableHead>
                  <TableHead>Input → Output</TableHead>
                  <TableHead className="pr-4">Visibility</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((enricher) => (
                  <TableRow key={`${enricher.kind}:${enricher.id}`}>
                    <TableCell className="max-w-96 whitespace-normal py-4 pl-4">
                      <div className="font-medium break-words">{enricher.name}</div>
                      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                        {enricher.description || 'No description available.'}
                      </p>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">
                        {enricher.kind === 'builtin' ? 'Built-in' : 'Template'}
                      </Badge>
                    </TableCell>
                    <TableCell className="capitalize">
                      {enricher.category.replace(/_/g, ' ')}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2 text-xs">
                        <span>{enricher.input_type}</span>
                        <ArrowRight className="size-3 text-muted-foreground" aria-label="to" />
                        <span>{enricher.output_type}</span>
                      </div>
                    </TableCell>
                    <TableCell className="pr-4">
                      <VisibilityControl enricher={enricher} />
                    </TableCell>
                  </TableRow>
                ))}
                {filtered.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} className="whitespace-normal py-12 text-center">
                      <p className="font-medium">
                        {enrichers.length ? 'No matching enrichers' : 'No enrichers available'}
                      </p>
                      <p className="mt-1 text-sm text-muted-foreground">
                        {enrichers.length
                          ? 'Try a different search or clear your filters.'
                          : 'Registered enrichers and templates will appear here.'}
                      </p>
                      {enrichers.length > 0 && (
                        <Button
                          variant="outline"
                          size="sm"
                          className="mt-4"
                          onClick={() => {
                            setSearch('')
                            setKind('all')
                            setVisibility('all')
                          }}
                        >
                          Clear filters
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
          <p className="text-xs text-muted-foreground">
            Showing {filtered.length} of {enrichers.length} enrichers
          </p>
        </div>
      )}
    </PageLayout>
  )
}
