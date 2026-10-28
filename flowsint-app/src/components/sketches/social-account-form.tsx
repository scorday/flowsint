import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { useTranslation } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { DynamicForm } from './dynamic-form'
import type { ActionItem } from '@/lib/action-items'
import { socialAccountService, type ResolvedSocialAccount } from '@/api/social-account-service'

interface SocialAccountFormProps {
  currentNodeType: ActionItem
  sketchId: string
  onSubmit: (data: Record<string, unknown>, loadFriends?: boolean) => Promise<void>
}

export function SocialAccountForm({ currentNodeType, sketchId, onSubmit }: SocialAccountFormProps) {
  const { t } = useTranslation()
  const [manual, setManual] = useState(false)
  const [url, setUrl] = useState('')
  const [profile, setProfile] = useState<ResolvedSocialAccount | null>(null)
  const [loadFriends, setLoadFriends] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const handleResolve = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      setProfile(await socialAccountService.resolve(sketchId, url.trim()))
      setLoadFriends(false)
    } catch {
      setError(t('Could not retrieve the VK profile. Check the link and try again.'))
    } finally {
      setBusy(false)
    }
  }

  const handleAdd = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!profile) return
    setBusy(true)
    try {
      await onSubmit(profile, loadFriends && profile.vk_profile_status === 'open')
    } finally {
      setBusy(false)
    }
  }

  const status = profile?.vk_profile_status
  const statusLabel =
    status === 'open'
      ? t('Open profile')
      : status === 'closed'
        ? t('Closed profile')
        : status === 'deactivated'
          ? t('Deactivated profile')
          : t('Profile privacy unknown')

  return (
    <div className="space-y-4 p-1">
      <div className="flex gap-2" role="group" aria-label={t('Account entry method')}>
        <Button
          type="button"
          variant={manual ? 'outline' : 'secondary'}
          disabled={busy}
          aria-pressed={!manual}
          onClick={() => setManual(false)}
        >
          {t('From profile link')}
        </Button>
        <Button
          type="button"
          variant={manual ? 'secondary' : 'outline'}
          disabled={busy}
          aria-pressed={manual}
          onClick={() => setManual(true)}
        >
          {t('Enter manually')}
        </Button>
      </div>
      {manual ? (
        <DynamicForm currentNodeType={currentNodeType} onSubmit={onSubmit} />
      ) : profile ? (
        <form onSubmit={handleAdd} className="space-y-4">
          <div className="space-y-2 rounded-md border p-4">
            <p className="font-medium">{profile.display_name || profile.username.value}</p>
            <a
              href={profile.profile_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm text-primary break-all"
            >
              {profile.profile_url}
            </a>
            <p className="text-sm">VK · {statusLabel}</p>
          </div>
          {status === 'open' ? (
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={loadFriends}
                disabled={busy}
                onChange={(event) => setLoadFriends(event.target.checked)}
                className="mt-1"
              />
              {t('Load friends after adding (up to 1000)')}
            </label>
          ) : (
            <p className="text-sm text-muted-foreground">
              {t('Friend loading is available after VK confirms the profile is open.')}
            </p>
          )}
          <div className="flex justify-between gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => setProfile(null)}
            >
              {t('Change link')}
            </Button>
            <Button type="submit" disabled={busy}>
              {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {t('Add profile')}
            </Button>
          </div>
        </form>
      ) : (
        <form onSubmit={handleResolve} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="social-profile-url">{t('Social profile link')}</Label>
            <Input
              id="social-profile-url"
              type="url"
              required
              autoFocus
              disabled={busy}
              placeholder="https://vk.ru/id515596"
              value={url}
              onChange={(event) => {
                setUrl(event.target.value)
                setError('')
              }}
            />
            <p className="text-sm text-muted-foreground">
              {t(
                'Paste a VK profile link. VK and the account ID will be detected automatically. For other platforms, use manual entry.'
              )}
            </p>
          </div>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <div className="flex justify-end">
            <Button type="submit" disabled={busy || !url.trim()}>
              {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {t('Get profile')}
            </Button>
          </div>
        </form>
      )}
    </div>
  )
}
