// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { setLanguage } from '@/i18n'
import { useGraphSettingsStore } from '@/stores/graph-settings-store'
import GlobalSettings from './settings'

vi.hoisted(() => {
  const storage = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key)
  })
})

vi.mock('@tanstack/react-router', () => ({
  useParams: () => ({ id: 'sketch-id', investigationId: 'investigation-id' })
}))
vi.mock('@/hooks/use-can', () => ({ usePermissions: () => ({ canEdit: true }) }))
vi.mock('@/api/sketch-service', () => ({ sketchService: { getById: vi.fn() } }))
vi.mock('@/components/shared/icon-picker', () => ({
  default: () => null,
  NodeIconTrigger: () => null
}))
vi.mock('@/components/sketches/graph/utils/image-cache', () => ({
  clearIconTypeCache: vi.fn()
}))

let client: QueryClient
beforeEach(() => {
  setLanguage('en')
  useGraphSettingsStore.getState().setSettingsModalOpen(false)
  client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } })
  client.setQueryData(['investigations', 'investigation-id', 'graph', 'sketch-id'], {
    id: 'sketch-id',
    title: 'Existing sketch',
    description: '',
    status: 'active'
  })
})
afterEach(() => {
  cleanup()
  client.clear()
  useGraphSettingsStore.getState().setSettingsModalOpen(false)
  setLanguage('en')
})

it.each(['en', 'ru'] as const)(
  'keeps the investigation mounted with closed settings in %s',
  (language) => {
    setLanguage(language)
    expect(() =>
      render(
        <QueryClientProvider client={client}>
          <GlobalSettings />
        </QueryClientProvider>
      )
    ).not.toThrow()
    expect(screen.queryByRole('dialog')).toBeNull()

    act(() => useGraphSettingsStore.getState().setSettingsModalOpen(true))
    expect(screen.getByRole('dialog')).toBeTruthy()
    expect(
      screen.getByRole('tab', { name: language === 'ru' ? 'Основные' : 'General' })
    ).toBeTruthy()
    expect(screen.getByRole('tab', { name: language === 'ru' ? 'Граф' : 'Graph' })).toBeTruthy()
  }
)
