import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { useTranslation } from '@/i18n'
import type { ManualNodeAdd } from './use-manual-node-add'

export function NodeMatchDialog({ controller }: { controller: ManualNodeAdd }) {
  const { t } = useTranslation()
  const { pending, busy, error, cancel, retry, reuse, createSeparate } = controller
  const exact = pending?.matches.some((match) => match.match === 'exact')
  return (
    <Dialog open={!!pending} onOpenChange={(open) => !open && cancel()}>
      <DialogContent className="sm:max-w-xl" onInteractOutside={(event) => event.preventDefault()}>
        <DialogTitle>
          {t(exact ? 'Object already exists' : 'Check investigation objects')}
        </DialogTitle>
        <DialogDescription>
          {t(
            exact
              ? 'This identifier belongs to an existing object. Use it on this sketch; its shared data will be preserved.'
              : 'Similar names may belong to different objects. Choose an existing object or create a separate one.'
          )}
        </DialogDescription>
        {busy && <p role="status">{t('Checking or saving...')}</p>}
        {error && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <div className="max-h-80 overflow-y-auto space-y-3">
          {pending?.matches.map((match) => (
            <div key={match.node.id} className="border rounded p-3 space-y-2">
              <p className="font-medium break-words">{match.node.nodeLabel}</p>
              <p className="text-xs text-muted-foreground">
                {match.node.nodeType} ·{' '}
                {t(match.match === 'exact' ? 'Same identifier' : 'Similar name')}
                {match.on_sketch && ` · ${t('Already on this sketch')}`}
              </p>
              <p className="text-xs break-words text-muted-foreground">
                {Object.entries(match.node.nodeProperties ?? {})
                  .filter(([, value]) => typeof value === 'string' || typeof value === 'number')
                  .slice(0, 5)
                  .map(([, value]) => String(value))
                  .join(' · ')}
              </p>
              <Button
                disabled={busy}
                onClick={() => reuse(match)}
                aria-label={`${t('Use existing object')}: ${match.node.nodeLabel}`}
              >
                {t(match.on_sketch ? 'Show existing object' : 'Add existing object to sketch')}
              </Button>
            </div>
          ))}
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" disabled={busy} onClick={cancel}>
            {t('Back to editing')}
          </Button>
          {error && !pending?.matches.length && (
            <Button disabled={busy} onClick={retry}>
              {t('Retry')}
            </Button>
          )}
          {!!pending?.matches.length && !exact && (
            <Button disabled={busy} variant="secondary" onClick={createSeparate}>
              {t('Create separate object')}
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
