import { useTranslation } from '@/i18n'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Eye, EyeOff, Info, Loader2, Search, ShieldCheck } from 'lucide-react'
import {
  type AdminEnricher,
  enricherAdministrationKeys,
  enricherAdministrationService
} from '@/api/enricher-administration-service'
import { useEnricherAdministrationAccess } from '@/hooks/use-enricher-administration-access'
import { PageLayout } from '@/components/layout/page-layout'
import { ErrorState } from '@/components/shared/error-state'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog'
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

function friendlyCategory(category: string): string {
  return category.replace(/[_\s]+/g, ' ').trim()
}

const apiKeyLabels: Record<AdminEnricher['api_key_requirement'], string> = {
  required: 'Required',
  optional: 'Optional',
  conditional: 'Conditional',
  not_required: 'Not required',
  unknown: 'Unknown'
}

function ApiKeyRequirement({ enricher }: { enricher: AdminEnricher }) {
  const { t } = useTranslation()

  return (
    <Badge
      variant="outline"
      className={
        enricher.api_key_requirement === 'required'
          ? 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400'
          : undefined
      }
    >
      {t(apiKeyLabels[enricher.api_key_requirement] ?? 'Unknown')}
    </Badge>
  )
}

function EnricherDetails({ enricher }: { enricher: AdminEnricher }) {
  const { t } = useTranslation()

  return (
    <Dialog>
      <DialogTrigger asChild>
        <button
          type="button"
          aria-label={t('View details for {{v0}}', { v0: enricher.name })}
          className="inline-flex max-w-full items-center gap-2 rounded-sm text-left font-medium text-primary underline decoration-primary/40 underline-offset-4 hover:decoration-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="min-w-0 break-words">{enricher.name}</span>
          <Info className="size-3.5 shrink-0" aria-hidden="true" />
        </button>
      </DialogTrigger>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-2xl">
        <DialogHeader className="text-left">
          <DialogTitle className="break-words pr-8 leading-snug">{enricher.name}</DialogTitle>
          <DialogDescription className="whitespace-pre-wrap break-words leading-relaxed">
            {t(enricher.description || 'No description available.')}
          </DialogDescription>
        </DialogHeader>
        <dl className="grid gap-4 border-t pt-4 text-sm sm:grid-cols-2">
          <div className="space-y-1">
            <dt className="text-xs text-muted-foreground">{t('Provider')}</dt>
            <dd className="break-words">
              {enricher.providers?.length
                ? enricher.providers.join(', ')
                : t('No named external provider specified.')}
            </dd>
          </div>
          <div className="space-y-1">
            <dt className="text-xs text-muted-foreground">{t('API key')}</dt>
            <dd>
              <ApiKeyRequirement enricher={enricher} />
            </dd>
          </div>
          {enricher.api_key_notes && (
            <div className="space-y-1 sm:col-span-2">
              <dt className="text-xs text-muted-foreground">{t('API key notes')}</dt>
              <dd className="whitespace-pre-wrap break-words leading-relaxed">
                {t(enricher.api_key_notes)}
              </dd>
            </div>
          )}
          <div className="space-y-1">
            <dt className="text-xs text-muted-foreground">{t('Kind')}</dt>
            <dd>{enricher.kind === 'builtin' ? t('Built-in') : t('Template')}</dd>
          </div>
          <div className="space-y-1">
            <dt className="text-xs text-muted-foreground">{t('Category')}</dt>
            <dd className="capitalize">{friendlyCategory(enricher.category)}</dd>
          </div>
          <div className="space-y-1">
            <dt className="text-xs text-muted-foreground">{t('Input')}</dt>
            <dd className="break-words">{enricher.input_type}</dd>
          </div>
          <div className="space-y-1">
            <dt className="text-xs text-muted-foreground">{t('Output')}</dt>
            <dd className="break-words">{enricher.output_type}</dd>
          </div>
        </dl>
      </DialogContent>
    </Dialog>
  )
}

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
  const { t } = useTranslation()

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
          aria-label={t('Show {{v0}} ({{v1}}) in catalog and launch menus', {
            v0: enricher.name,
            v1: enricher.kind
          })}
        />
        <Badge variant={enricher.is_visible ? 'secondary' : 'outline'}>
          {enricher.is_visible ? <Eye aria-hidden="true" /> : <EyeOff aria-hidden="true" />}
          {enricher.is_visible ? t('Visible') : t('Hidden')}
        </Badge>
        {mutation.isPending && <Loader2 className="size-3 animate-spin" aria-label={t('Saving')} />}
      </div>
      {mutation.isError && (
        <p role="alert" className="max-w-52 whitespace-normal text-xs text-destructive">
          {t("Couldn't save visibility. Try the switch again.")}
        </p>
      )}
    </div>
  )
}

export function EnricherAdministration() {
  const { t, language } = useTranslation()

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
  const [category, setCategory] = useState('all')
  const [apiKeyRequirement, setApiKeyRequirement] = useState('all')
  const enrichers = catalog.data ?? []
  const categories = [...new Set(enrichers.map((enricher) => enricher.category))].sort(
    (left, right) => friendlyCategory(left).localeCompare(friendlyCategory(right), language)
  )
  const visibleCount = enrichers.filter((enricher) => enricher.is_visible).length
  const term = search.trim().toLowerCase()
  const filtered = enrichers.filter(
    (enricher) =>
      (kind === 'all' || enricher.kind === kind) &&
      (visibility === 'all' || enricher.is_visible === (visibility === 'visible')) &&
      (category === 'all' || `category:${enricher.category}` === category) &&
      (apiKeyRequirement === 'all' || enricher.api_key_requirement === apiKeyRequirement) &&
      [
        enricher.name,
        enricher.description,
        t(enricher.description ?? ''),
        enricher.category,
        friendlyCategory(enricher.category),
        enricher.input_type,
        enricher.output_type
      ]
        .concat(enricher.providers ?? [])
        .some((value) => value?.toLowerCase().includes(term))
  )
  const isLoading = access.isPending || (access.data?.can_manage && catalog.isPending)
  const error = access.error ?? catalog.error
  const forbidden = access.data?.can_manage === false || isForbidden(error)

  return (
    <PageLayout
      title={t('Enricher administration')}
      description={t('Control which enrichers appear in the catalog and launch menus.')}
      isLoading={Boolean(isLoading)}
      loadingComponent={
        <div role="status" className="flex items-center gap-2 py-12 text-muted-foreground">
          <Loader2 className="size-4 animate-spin" aria-hidden="true" />
          {t('Loading enricher administration…')}
        </div>
      }
      error={forbidden ? null : error}
      errorComponent={
        <ErrorState
          title={t("Couldn't load enricher administration")}
          description={t('Check your access and connection, then try again.')}
          onRetry={() => (access.isError ? access.refetch() : catalog.refetch())}
        />
      }
    >
      {forbidden ? (
        <div className="flex flex-col items-center gap-3 py-16 text-center">
          <ShieldCheck className="size-8 text-muted-foreground" aria-hidden="true" />
          <h2 className="text-lg font-semibold">{t('Administrator access required')}</h2>
          <p className="max-w-md text-sm text-muted-foreground">
            {t(
              'Your account cannot manage enricher visibility. Contact your administrator for access.'
            )}
          </p>
        </div>
      ) : (
        <div className="min-w-0 space-y-6">
          <Alert>
            <ShieldCheck aria-hidden="true" />
            <AlertDescription>
              <p>
                {t('Visibility settings apply to all Flowsint users and projects.')}{' '}
                {t(
                  'Hidden enrichers are removed from the catalog and launch menus. Saved flows remain runnable. You can restore a hidden enricher here at any time.'
                )}
              </p>
            </AlertDescription>
          </Alert>

          <div
            className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm"
            aria-live="polite"
            role="group"
            aria-label={t('Enricher counts')}
          >
            <span className="text-muted-foreground">
              {t('All ')}
              <strong className="ml-1 text-foreground">{enrichers.length}</strong>
            </span>
            <span className="flex items-center gap-2 text-muted-foreground">
              <Eye className="size-3.5" aria-hidden="true" />
              {t('Visible ')}
              <strong className="text-foreground">{visibleCount}</strong>
            </span>
            <span className="flex items-center gap-2 text-muted-foreground">
              <EyeOff className="size-3.5" aria-hidden="true" />
              {t('Hidden ')}
              <strong className="text-foreground">{enrichers.length - visibleCount}</strong>
            </span>
          </div>

          <div className="flex flex-wrap gap-3">
            <div className="relative min-w-52 flex-1">
              <Search
                className="absolute left-3 top-2.5 size-4 text-muted-foreground"
                aria-hidden="true"
              />
              <Input
                aria-label={t('Search enrichers')}
                placeholder={t('Search name, provider, description or type…')}
                className="pl-9"
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value)
                }}
              />
            </div>
            <Select
              value={kind}
              onValueChange={(value) => {
                setKind(value)
              }}
            >
              <SelectTrigger aria-label={t('Enricher kind')} className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('All kinds')}</SelectItem>
                <SelectItem value="builtin">{t('Built-in')}</SelectItem>
                <SelectItem value="template">{t('Template')}</SelectItem>
              </SelectContent>
            </Select>
            <Select
              value={visibility}
              onValueChange={(value) => {
                setVisibility(value)
              }}
            >
              <SelectTrigger aria-label={t('Visibility filter')} className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('All visibility')}</SelectItem>
                <SelectItem value="visible">{t('Visible')}</SelectItem>
                <SelectItem value="hidden">{t('Hidden')}</SelectItem>
              </SelectContent>
            </Select>
            <Select value={category} onValueChange={setCategory}>
              <SelectTrigger aria-label={t('Category filter')} className="w-48">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('All Categories')}</SelectItem>
                {categories.map((value) => (
                  <SelectItem key={value} value={`category:${value}`} className="capitalize">
                    {friendlyCategory(value)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={apiKeyRequirement} onValueChange={setApiKeyRequirement}>
              <SelectTrigger aria-label={t('API key requirement filter')} className="w-64">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('All API key requirements')}</SelectItem>
                {Object.entries(apiKeyLabels).map(([value, label]) => (
                  <SelectItem key={value} value={value}>
                    {t(label)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {filtered.length > 0 ? (
            <div className="min-w-0 overflow-hidden rounded-md border bg-card">
              <Table className="min-w-[1100px]" aria-label={t('All enrichers')}>
                <TableHeader>
                  <TableRow>
                    <TableHead className="pl-4">{t('Enricher')}</TableHead>
                    <TableHead>{t('Kind')}</TableHead>
                    <TableHead>{t('Category')}</TableHead>
                    <TableHead>{t('Provider')}</TableHead>
                    <TableHead>{t('API key')}</TableHead>
                    <TableHead>{t('Input → Output')}</TableHead>
                    <TableHead
                      className="right-0 z-10 min-w-52 border-l bg-card pr-4"
                      style={{ position: 'sticky' }}
                    >
                      {t('Visibility')}
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((enricher) => (
                    <TableRow key={`${enricher.kind}:${enricher.id}`}>
                      <TableCell className="max-w-96 whitespace-normal py-4 pl-4">
                        <EnricherDetails enricher={enricher} />
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">
                          {enricher.kind === 'builtin' ? t('Built-in') : t('Template')}
                        </Badge>
                      </TableCell>
                      <TableCell className="capitalize">
                        {friendlyCategory(enricher.category)}
                      </TableCell>
                      <TableCell>
                        {enricher.providers?.length ? (
                          <div className="flex max-w-56 flex-wrap gap-1">
                            {enricher.providers.map((provider) => (
                              <Badge
                                key={provider}
                                variant="secondary"
                                className="max-w-full whitespace-normal break-words"
                              >
                                {provider}
                              </Badge>
                            ))}
                          </div>
                        ) : (
                          <span
                            className="text-muted-foreground"
                            aria-label={t('No named provider')}
                          >
                            —
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        <ApiKeyRequirement enricher={enricher} />
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2 text-xs">
                          <span>{enricher.input_type}</span>
                          <ArrowRight
                            className="size-3 text-muted-foreground"
                            aria-label={t('to')}
                          />
                          <span>{enricher.output_type}</span>
                        </div>
                      </TableCell>
                      <TableCell className="sticky right-0 z-10 min-w-52 border-l bg-card pr-4">
                        <VisibilityControl enricher={enricher} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <div className="rounded-md border bg-card py-12 text-center">
              <p className="font-medium">
                {enrichers.length ? t('No matching enrichers') : t('No enrichers available')}
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                {enrichers.length
                  ? t('Try a different search or clear your filters.')
                  : t('Registered enrichers and templates will appear here.')}
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
                    setCategory('all')
                    setApiKeyRequirement('all')
                  }}
                >
                  {t('Clear filters')}
                </Button>
              )}
            </div>
          )}
          <p className="text-xs text-muted-foreground">
            {t('Showing ')}
            {filtered.length} {t(' of ')}
            {enrichers.length} {t(' enrichers')}
          </p>
        </div>
      )}
    </PageLayout>
  )
}
