import { Languages } from 'lucide-react'
import { useTranslation, type Language } from '@/i18n'

export function LanguageSwitcher() {
  const { language, setLanguage, t } = useTranslation()
  return (
    <label className="inline-flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
      <Languages className="size-4" aria-hidden="true" />
      <span className="sr-only">{t('Language')}</span>
      <select
        aria-label={t('Language')}
        title={t('Change language')}
        value={language}
        onChange={(event) => setLanguage(event.target.value as Language)}
        className="h-8 max-w-28 rounded-md border border-input bg-background px-2 text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <option value="en" lang="en">
          English
        </option>
        <option value="ru" lang="ru">
          Русский
        </option>
      </select>
    </label>
  )
}
