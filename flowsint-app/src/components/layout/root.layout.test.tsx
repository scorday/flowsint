// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createJSONStorage } from 'zustand/middleware'
import { useLayoutStore } from '@/stores/layout-store'
import RootLayout from './root.layout'

const route = vi.hoisted(() => ({ pathname: '/dashboard/admin/enrichers' }))
vi.mock('@tanstack/react-router', () => ({
  useParams: () => ({}),
  useLocation: ({ select }: { select: (location: { pathname: string }) => string }) => select(route)
}))
vi.mock('./sidebar', () => ({ Sidebar: () => <nav aria-label="Main navigation" /> }))
vi.mock('./top-navbar', () => ({ TopNavbar: () => <header>Flowsint</header> }))
vi.mock('./secondary-navigation', () => ({ default: () => <nav aria-label="Cases navigation" /> }))
vi.mock('./persistent-log-panel', () => ({ PersistentLogPanel: () => null }))
vi.mock('../analyses/notes-panel', () => ({ default: () => null }))
vi.mock('../sketches/details-panel/details-panel', () => ({ default: () => null }))
vi.mock('../sketches/details-panel/edge-details-panel', () => ({ default: () => null }))
vi.mock('@/hooks/use-keyboard-shortcut', () => ({ useKeyboardShortcut: () => {} }))
vi.mock('@/stores/graph-store', () => ({
  useGraphStore: (
    select: (store: { getCurrentNode: () => null; getCurrentEdge: () => null }) => unknown
  ) => select({ getCurrentNode: () => null, getCurrentEdge: () => null })
}))
vi.mock('@/components/use-confirm-dialog', () => ({
  ConfirmContextProvider: ({ children }: { children: ReactNode }) => <>{children}</>
}))
// Panel geometry depends on the browser; these tests exercise route transitions and saved preferences.
vi.mock('../ui/resizable', () => ({
  ResizablePanelGroup: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  ResizablePanel: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  ResizableHandle: () => <div role="separator" />
}))

beforeEach(() => {
  route.pathname = '/dashboard/admin/enrichers'
  const saved = new Map<string, string>()
  useLayoutStore.persist.setOptions({
    storage: createJSONStorage(() => ({
      getItem: (key) => saved.get(key) ?? null,
      setItem: (key, value) => {
        saved.set(key, value)
      },
      removeItem: (key) => {
        saved.delete(key)
      }
    }))
  })
  useLayoutStore.setState({ isOpenPanel: true, isOpenConsole: false })
})
afterEach(cleanup)

describe('dashboard administration layout', () => {
  it('gives administration the content area while preserving the Cases preference on navigation', () => {
    const view = render(
      <RootLayout>
        <main>Enricher administration</main>
      </RootLayout>
    )
    expect(screen.getByRole('main').textContent).toBe('Enricher administration')
    expect(screen.queryByRole('navigation', { name: 'Cases navigation' })).toBeNull()
    expect(useLayoutStore.getState().isOpenPanel).toBe(true)

    route.pathname = '/dashboard/flows'
    view.rerender(
      <RootLayout>
        <main>Flows</main>
      </RootLayout>
    )
    expect(screen.getByRole('navigation', { name: 'Cases navigation' })).toBeTruthy()

    route.pathname = '/dashboard/admin/enrichers'
    view.rerender(
      <RootLayout>
        <main>Enricher administration</main>
      </RootLayout>
    )
    expect(screen.queryByRole('navigation', { name: 'Cases navigation' })).toBeNull()
    expect(useLayoutStore.getState().isOpenPanel).toBe(true)
  })

  it('keeps a user-closed Cases pane closed after leaving administration', () => {
    useLayoutStore.setState({ isOpenPanel: false })
    const view = render(
      <RootLayout>
        <main>Enricher administration</main>
      </RootLayout>
    )
    route.pathname = '/dashboard/flows'
    view.rerender(
      <RootLayout>
        <main>Flows</main>
      </RootLayout>
    )
    expect(screen.queryByRole('navigation', { name: 'Cases navigation' })).toBeNull()
    expect(useLayoutStore.getState().isOpenPanel).toBe(false)
  })
})
