import { useMemo, useSyncExternalStore } from 'react'
import { enUS, ru } from 'date-fns/locale'
import en from './locales/en.json'
import ruMessages from './locales/ru.json'
import enricherEn from './locales/enrichers.en.json'
import enricherRu from './locales/enrichers.ru.json'

export const languages = ['en', 'ru'] as const
export type Language = (typeof languages)[number]
export type TranslationKey = keyof typeof en | keyof typeof enricherEn
export type TranslationValues = Record<string, string | number>
export const LANGUAGE_STORAGE_KEY = 'flowsint-language'
const dictionaries: Record<Language, Record<string, string>> = {
  en: { ...en, ...enricherEn },
  ru: { ...ruMessages, ...enricherRu }
}
const listeners = new Set<() => void>()

export function resolveLanguage(value: string | null | undefined): Language | undefined {
  const base = value?.toLowerCase().split(/[-_]/)[0]
  return languages.find((language) => language === base)
}

export function detectLanguage(): Language {
  try {
    const saved = resolveLanguage(window.localStorage.getItem(LANGUAGE_STORAGE_KEY))
    if (saved) return saved
  } catch {
    // Language switching still works when browser storage is unavailable.
  }
  if (typeof navigator !== 'undefined') {
    for (const preferred of navigator.languages?.length
      ? navigator.languages
      : [navigator.language]) {
      const supported = resolveLanguage(preferred)
      if (supported) return supported
    }
  }
  return 'en'
}

let language = detectLanguage()

function updateDocumentLanguage() {
  if (typeof document !== 'undefined') document.documentElement.lang = language
}
updateDocumentLanguage()

export function getLanguage(): Language {
  return language
}

export function setLanguage(next: Language) {
  if (!languages.includes(next)) return
  try {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, next)
  } catch {
    // Keep the in-memory preference even in private or restricted contexts.
  }
  if (next === language) return
  language = next
  updateDocumentLanguage()
  listeners.forEach((listener) => listener())
}

if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
  const onStorage = (event: StorageEvent) => {
    if (event.key !== LANGUAGE_STORAGE_KEY && event.key !== null) return
    const next = detectLanguage()
    if (next === language) return
    language = next
    updateDocumentLanguage()
    listeners.forEach((listener) => listener())
  }
  window.addEventListener('storage', onStorage)
  if (import.meta.hot)
    import.meta.hot.dispose(() => window.removeEventListener('storage', onStorage))
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function translateFor(
  locale: Language,
  key: string,
  values: TranslationValues = {}
): string {
  const count = values.count
  const pluralKey =
    typeof count === 'number' ? `${key}_${new Intl.PluralRules(locale).select(count)}` : key
  const lookup = (messages: Record<string, string>, name: string) =>
    Object.prototype.hasOwnProperty.call(messages, name) ? messages[name] : undefined
  const template =
    lookup(dictionaries[locale], pluralKey) ??
    lookup(dictionaries[locale], key) ??
    lookup(dictionaries.en, pluralKey) ??
    lookup(dictionaries.en, key) ??
    key
  return template.replace(/\{\{(\w+)\}\}/g, (match, name: string) =>
    values[name] === undefined ? match : String(values[name])
  )
}

/** For event handlers and non-React code. Components should use useTranslation. */
export function translate(key: string, values?: TranslationValues) {
  return translateFor(language, key, values)
}

export function getDateLocale() {
  return language === 'ru' ? ru : enUS
}

export function useTranslation() {
  const locale = useSyncExternalStore(subscribe, getLanguage, () => 'en' as const)
  return useMemo(
    () => ({
      language: locale,
      setLanguage,
      t: (key: string, values?: TranslationValues) => translateFor(locale, key, values),
      dateLocale: locale === 'ru' ? ru : enUS
    }),
    [locale]
  )
}
