// @vitest-environment jsdom
import { memo, useEffect, useState } from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { formatDistanceToNow } from 'date-fns'
import en from './locales/en.json'
import ru from './locales/ru.json'
import {
  detectLanguage,
  getLanguage,
  LANGUAGE_STORAGE_KEY,
  resolveLanguage,
  setLanguage,
  translate,
  translateFor,
  useTranslation
} from './index'
import { LanguageSwitcher } from '@/components/language-switcher'
import { ViewToggle } from '@/components/sketches/view-toggle'
import { TooltipProvider } from '@/components/ui/tooltip'

beforeEach(() => {
  const values = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      values.set(key, value)
    },
    removeItem: (key: string) => {
      values.delete(key)
    },
    clear: () => values.clear()
  })
  localStorage.clear()
  setLanguage('en')
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  setLanguage('en')
  localStorage.clear()
  vi.unstubAllGlobals()
})

describe('language selection', () => {
  it('recognizes supported language regions', () => {
    expect(resolveLanguage('ru-RU')).toBe('ru')
    expect(resolveLanguage('en_US')).toBe('en')
    expect(resolveLanguage('fr-FR')).toBeUndefined()
  })
  it('prefers the saved language over browser preferences', () => {
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['ru-RU'])
    expect(detectLanguage()).toBe('en')
    localStorage.removeItem(LANGUAGE_STORAGE_KEY)
    expect(detectLanguage()).toBe('ru')
  })
  it('finds a supported browser preference and falls back to English', () => {
    localStorage.removeItem(LANGUAGE_STORAGE_KEY)
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['fr', 'ru-RU', 'en'])
    expect(detectLanguage()).toBe('ru')
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['fr'])
    expect(detectLanguage()).toBe('en')
  })
  it('keeps switching functional when storage is blocked', () => {
    vi.spyOn(localStorage, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(() => setLanguage('ru')).not.toThrow()
    expect(getLanguage()).toBe('ru')
    expect(document.documentElement.lang).toBe('ru')
    expect(translate('Investigations')).toBe('Расследования')
  })
  it('synchronizes other tabs and a cleared preference', () => {
    render(<LanguageSwitcher />)
    act(() => {
      localStorage.setItem(LANGUAGE_STORAGE_KEY, 'ru')
      window.dispatchEvent(
        new StorageEvent('storage', { key: LANGUAGE_STORAGE_KEY, newValue: 'ru' })
      )
    })
    expect((screen.getByRole('combobox', { name: 'Язык' }) as HTMLSelectElement).value).toBe('ru')
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['en'])
    act(() => {
      localStorage.clear()
      window.dispatchEvent(new StorageEvent('storage', { key: null }))
    })
    expect(getLanguage()).toBe('en')
  })
})

describe('translations', () => {
  it('provides matching nonempty English and Russian catalogs', () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(ru).sort())
    expect(Object.values(ru).every((value) => value.trim().length > 0)).toBe(true)
  })
  it('falls back safely for unknown strings, including object property names', () => {
    expect(translateFor('ru', 'My investigation title')).toBe('My investigation title')
    expect(translateFor('ru', '__proto__')).toBe('__proto__')
    expect(translateFor('ru', 'constructor')).toBe('constructor')
  })
  it('interpolates values without interpreting their contents', () => {
    expect(translateFor('ru', 'Enter {{v0}}', { v0: '<script>{{v1}}</script>' })).toBe(
      'Введите <script>{{v1}}</script>'
    )
  })
  it.each([
    [1, '1 поле'],
    [2, '2 поля'],
    [5, '5 полей'],
    [11, '11 полей'],
    [21, '21 поле'],
    [22, '22 поля']
  ])('uses Russian plural rules for %s', (count, expected) => {
    expect(translateFor('ru', 'counts.fields', { count })).toBe(expected)
  })
  it('uses English plural rules', () => {
    expect(translateFor('en', 'counts.fields', { count: 1 })).toBe('1 field')
    expect(translateFor('en', 'counts.fields', { count: 2 })).toBe('2 fields')
  })
})

it('updates memoized UI and dates without resetting editor state', () => {
  const mount = vi.fn()
  const Editor = memo(function Editor() {
    const { t, dateLocale } = useTranslation()
    const [draft, setDraft] = useState('')
    useEffect(() => {
      mount()
    }, [])
    return (
      <>
        <h1>{t('Investigations')}</h1>
        <input
          aria-label="draft"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <p>
          {formatDistanceToNow(new Date(Date.now() - 3_600_000), {
            locale: dateLocale,
            addSuffix: true
          })}
        </p>
      </>
    )
  })
  render(
    <TooltipProvider>
      <LanguageSwitcher />
      <Editor />
      <ViewToggle view="graph" setView={() => {}} />
    </TooltipProvider>
  )
  fireEvent.change(screen.getByRole('textbox', { name: 'draft' }), {
    target: { value: 'Unsaved user data' }
  })
  expect(screen.getByText('about 1 hour ago')).toBeTruthy()
  fireEvent.change(screen.getByRole('combobox', { name: 'Language' }), { target: { value: 'ru' } })
  expect(screen.getByRole('heading', { name: 'Расследования' })).toBeTruthy()
  expect(screen.getByRole('radio', { name: 'Граф' })).toBeTruthy()
  expect(screen.getByText('около 1 часа назад')).toBeTruthy()
  expect((screen.getByRole('textbox', { name: 'draft' }) as HTMLInputElement).value).toBe(
    'Unsaved user data'
  )
  expect(mount).toHaveBeenCalledTimes(1)
  expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe('ru')
  expect(document.documentElement.lang).toBe('ru')
  fireEvent.change(screen.getByRole('combobox', { name: 'Язык' }), { target: { value: 'en' } })
  expect(screen.getByRole('heading', { name: 'Investigations' })).toBeTruthy()
})
